"""
定时任务调度模块
使用 APScheduler 实现 SPEC 中定义的定时任务：
- 每日6点选品
- 每5分钟预警扫描
- 每日23点套餐挖掘
- 每周日3点 Prophet 重训练

持久化心跳：每次任务执行前后更新 scheduler_heartbeat 表，
解决 fly.io auto_stop 下休眠丢失任务的可观测性问题。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_settings

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid int for %s=%s, fallback to %d", name, value, default)
        return default


_scheduler: AsyncIOScheduler | None = None
SH_TZ = ZoneInfo("Asia/Shanghai")
LOW_STOCK_MIN_UNITS = _env_int("ALERT_LOW_STOCK_MIN_UNITS", 5)
LOW_STOCK_SAFETY_DAYS = _env_int("ALERT_LOW_STOCK_SAFETY_DAYS", 5)
ORDER_ALERT_DELAY_MINUTES = _env_int("ORDER_ALERT_DELAY_MINUTES", 30)
ORDER_ALERT_CRITICAL_MINUTES = _env_int("ORDER_ALERT_CRITICAL_MINUTES", 120)
ALERT_SCAN_MAX_ROWS = _env_int("ALERT_SCAN_MAX_ROWS", 50)


def get_scheduler() -> AsyncIOScheduler:
    """获取调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


# ── 心跳持久化 ──────────────────────────────────────────────────────────────


async def _set_heartbeat(
    task_name: str,
    status: str,
    error_msg: str | None = None,
    next_run: datetime | None = None,
) -> None:
    """更新 scheduler_heartbeat 表中的任务状态记录。

    status 取值: 'running' | 'success' | 'failed'
    此函数内部吞掉所有异常，避免心跳失败影响业务逻辑。
    """
    try:
        from src.db import postgres as pg

        pool = pg._pool
        if pool is None:
            return

        # 若是 running 状态则不覆盖 last_run（由后续 success/failed 更新）
        if status == "running":
            await pool.execute(
                """
                INSERT INTO scheduler_heartbeat
                    (task_name, last_run, next_run, status, error_msg, run_count, updated_at)
                VALUES ($1, NOW(), $2, 'running', NULL, 0, NOW())
                ON CONFLICT (task_name) DO UPDATE SET
                    last_run   = NOW(),
                    next_run   = COALESCE($2, scheduler_heartbeat.next_run),
                    status     = 'running',
                    error_msg  = NULL,
                    run_count  = scheduler_heartbeat.run_count + 1,
                    updated_at = NOW()
                """,
                task_name,
                next_run,
            )
        else:
            await pool.execute(
                """
                INSERT INTO scheduler_heartbeat
                    (task_name, last_run, next_run, status, error_msg, run_count, updated_at)
                VALUES ($1, NOW(), $2, $3, $4, 1, NOW())
                ON CONFLICT (task_name) DO UPDATE SET
                    next_run   = COALESCE($2, scheduler_heartbeat.next_run),
                    status     = $3,
                    error_msg  = $4,
                    updated_at = NOW()
                """,
                task_name,
                next_run,
                status,
                error_msg,
            )
    except Exception as exc:
        logger.debug("Heartbeat update skipped for %s: %s", task_name, exc)


def _get_job_next_run(task_id: str) -> datetime | None:
    """从调度器获取任务下次运行时间。"""
    try:
        scheduler = get_scheduler()
        job = scheduler.get_job(task_id)
        return job.next_run_time if job else None
    except Exception:
        return None


def _make_heartbeat_task(task_id: str, task_func):
    """将任务函数包装为带心跳追踪的版本。

    在任务执行前记录 status='running'，
    成功后记录 status='success'，失败后记录 status='failed'。
    """

    async def _wrapper():
        next_run = _get_job_next_run(task_id)
        await _set_heartbeat(task_id, "running", next_run=next_run)
        try:
            await task_func()
            next_run = _get_job_next_run(task_id)
            await _set_heartbeat(task_id, "success", next_run=next_run)
        except Exception as exc:
            next_run = _get_job_next_run(task_id)
            await _set_heartbeat(task_id, "failed", error_msg=str(exc), next_run=next_run)
            raise

    _wrapper.__name__ = f"{task_id}_with_heartbeat"
    return _wrapper


# ── 任务实现 ────────────────────────────────────────────────────────────────


async def feedback_tracking_job() -> None:
    """追踪过去 N 天内的 AI 推荐效果，并更新模型权重 (每天凌晨 2:00 CST)。"""
    logger.info("Starting feedback tracking job")
    try:
        from src.db import postgres as pg
        from src.services.feedback_loop import FeedbackLoopService

        pool = pg.get_pool()
        feedback = FeedbackLoopService()
        all_outcomes: list[dict] = []

        # ── 1. 追踪选品推荐效果（30天前创建的 run） ────────────────────
        try:
            selection_runs = await pool.fetch(
                """
                SELECT run_id FROM selection_runs
                WHERE created_at >= NOW() - INTERVAL '31 days'
                  AND created_at < NOW() - INTERVAL '30 days'
                """
            )
            logger.info("Tracking %d selection runs", len(selection_runs))
            for row in selection_runs:
                try:
                    outcome = await feedback.track_selection_outcome(str(row["run_id"]))
                    if "error" not in outcome:
                        all_outcomes.append(
                            {"tracking_type": "selection", "performance_score": outcome.get("outcomes", [{}])[0].get("predicted_score", 0) if outcome.get("outcomes") else 0}
                        )
                except Exception as exc:
                    logger.error("Failed to track selection run %s: %s", row["run_id"], exc)
                    continue
        except Exception as exc:
            logger.error("Failed to query selection_runs for feedback tracking: %s", exc)

        # ── 2. 追踪套餐效果（30天前创建的 bundle） ──────────────────────
        try:
            bundles = await pool.fetch(
                """
                SELECT bundle_id FROM bundles
                WHERE created_at >= NOW() - INTERVAL '31 days'
                  AND created_at < NOW() - INTERVAL '30 days'
                """
            )
            logger.info("Tracking %d bundles", len(bundles))
            for row in bundles:
                try:
                    outcome = await feedback.track_bundle_outcome(str(row["bundle_id"]))
                    if "error" not in outcome:
                        all_outcomes.append(
                            {"tracking_type": "bundle", "performance_score": float(outcome.get("co_purchases", 0))}
                        )
                except Exception as exc:
                    logger.error("Failed to track bundle %s: %s", row["bundle_id"], exc)
                    continue
        except Exception as exc:
            logger.error("Failed to query bundles for feedback tracking: %s", exc)

        # ── 3. 追踪调价效果（7天前未追踪的 price_history 记录） ─────────
        try:
            price_changes = await pool.fetch(
                """
                SELECT id FROM price_history
                WHERE changed_at < NOW() - INTERVAL '7 days'
                  AND (outcome_tracked IS NULL OR outcome_tracked = FALSE)
                ORDER BY changed_at ASC
                LIMIT 200
                """
            )
            logger.info("Tracking %d price changes", len(price_changes))
            for row in price_changes:
                try:
                    outcome = await feedback.track_pricing_outcome(int(row["id"]))
                    if "error" not in outcome:
                        pct = outcome.get("sales_change_pct", 0.0)
                        all_outcomes.append(
                            {"tracking_type": "pricing", "performance_score": pct / 100.0}
                        )
                except Exception as exc:
                    logger.error("Failed to track price change %s: %s", row["id"], exc)
                    continue
        except Exception as exc:
            logger.error("Failed to query price_history for feedback tracking: %s", exc)

        # ── 4. 汇总并更新模型权重 ────────────────────────────────────────
        if all_outcomes:
            try:
                weight_result = await feedback.update_model_weights(all_outcomes)
                logger.info(
                    "Feedback tracking job done: tracked=%d weight_update=%s",
                    len(all_outcomes),
                    weight_result.get("status"),
                )
            except Exception as exc:
                logger.error("Failed to update model weights: %s", exc)
        else:
            logger.info("Feedback tracking job done: no outcomes to process")

    except Exception:
        logger.exception("Feedback tracking job failed")


async def cs_automatic_learning_task() -> None:
    """客服反馈自动学习任务 (每小时) — 从反馈数据更新 few-shot 示例"""
    logger.info("Starting CS automatic learning task")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip CS automatic learning")
        return
    try:
        import asyncpg

        from src.agents.customer_service.learning import run_automatic_learning

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            await run_automatic_learning(pool)
            logger.info("CS automatic learning task completed")
        finally:
            await pool.close()
    except Exception:
        logger.exception("CS automatic learning task failed")


async def daily_selection_task() -> None:
    """每日选品任务 (6:00)"""
    logger.info("Starting daily selection task")
    try:
        import time

        from src.agents import Orchestrator
        from src.metrics import record_agent_execution, selection_run_total

        orch = Orchestrator()
        start = time.time()

        result = await orch.run_selection(
            trigger_type="scheduled",
            categories=["医疗器械"],
        )

        duration = time.time() - start
        record_agent_execution("selection", duration, success=True)
        selection_run_total.labels(trigger="scheduled", status="completed").inc()

        rec_count = len(result.get("recommendations", {}).get("recommendations", []))
        logger.info(f"Daily selection completed: {rec_count} recommendations in {duration:.1f}s")

    except Exception:
        logger.exception("Daily selection task failed")
        from src.metrics import selection_run_total

        selection_run_total.labels(trigger="scheduled", status="failed").inc()


async def alert_scan_task() -> None:
    """预警扫描任务 (每5分钟)"""
    logger.info("Starting alert scan task")
    try:
        import time

        from src.db import postgres as pg
        from src.metrics import (
            record_agent_execution,
            record_alert_triggered,
            update_active_alerts,
        )

        start = time.time()
        pool = pg.get_pool()
        anomalies: list[dict[str, str]] = []

        async with pool.acquire() as conn:
            # 库存告警：基于月销量比例判断
            # 高优先级: monthly_sales >= 100 且 stock < monthly_sales * 0.5
            # 中优先级: monthly_sales >= 30 且 stock < monthly_sales * 0.3
            low_stock_rows = await conn.fetch(
                """
                SELECT
                    product_id,
                    name,
                    COALESCE(stock, 0) AS stock,
                    COALESCE(monthly_sales, 0) AS monthly_sales,
                    CASE
                        WHEN COALESCE(monthly_sales, 0) >= 100
                             AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5
                            THEN 'critical'
                        WHEN COALESCE(monthly_sales, 0) >= 30
                             AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3
                            THEN 'warning'
                    END AS computed_severity
                FROM products
                WHERE status = 'active'
                  AND (
                      (COALESCE(monthly_sales, 0) >= 100 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.5)
                      OR
                      (COALESCE(monthly_sales, 0) >= 30 AND COALESCE(stock, 0) < COALESCE(monthly_sales, 0) * 0.3)
                  )
                ORDER BY monthly_sales DESC, stock ASC
                LIMIT $1
                """,
                ALERT_SCAN_MAX_ROWS,
            )

            low_stock_alert_ids: list[str] = []
            for row in low_stock_rows:
                stock = int(row["stock"])
                monthly_sales = int(row["monthly_sales"])
                severity = row["computed_severity"]
                alert_id = f"low_stock_{row['product_id']}"
                if severity == "critical":
                    threshold = int(monthly_sales * 0.5)
                else:
                    threshold = int(monthly_sales * 0.3)
                deficit = threshold - stock
                metrics_payload = {
                    "stock": stock,
                    "threshold": threshold,
                    "monthly_sales": monthly_sales,
                    "deficit": deficit,
                }
                description = (
                    f"库存 {stock} 件，月销 {monthly_sales} 件，低于安全库存 {threshold} 件"
                )
                await _upsert_scheduler_alert(
                    conn,
                    alert_id=alert_id,
                    product_id=row["product_id"],
                    alert_type="inventory_low_stock",
                    severity=severity,
                    title=f"{row['name']} 库存不足",
                    description=description,
                    metrics=metrics_payload,
                )
                low_stock_alert_ids.append(alert_id)
                record_alert_triggered("inventory_low_stock", severity)
                anomalies.append({"anomaly_type": "inventory_low_stock", "severity": severity})

            await _resolve_stale_alerts(conn, "low_stock_%", low_stock_alert_ids)

            pending_orders = await conn.fetch(
                """
                SELECT order_id,
                       COALESCE(status, 'unknown') AS status,
                       total_amount,
                       order_time,
                       EXTRACT(EPOCH FROM (NOW() - order_time)) / 60 AS age_minutes
                FROM orders
                WHERE order_time IS NOT NULL
                  AND COALESCE(status, '') NOT IN ('completed', 'cancelled', 'closed', 'refunded')
                  AND order_time < NOW() - ($1::int || ' minutes')::interval
                ORDER BY order_time ASC
                LIMIT $2
                """,
                ORDER_ALERT_DELAY_MINUTES,
                ALERT_SCAN_MAX_ROWS,
            )

            order_alert_ids: list[str] = []
            for row in pending_orders:
                age_minutes = float(row["age_minutes"] or 0)
                if age_minutes >= ORDER_ALERT_CRITICAL_MINUTES:
                    severity = "critical"
                else:
                    severity = "warning"
                alert_id = f"order_delay_{row['order_id']}"
                metrics_payload = {
                    "status": row["status"],
                    "total_amount": float(row["total_amount"] or 0),
                    "order_time": row["order_time"].isoformat() if row["order_time"] else None,
                    "age_minutes": age_minutes,
                }
                description = (
                    f"订单已等待 {age_minutes:.0f} 分钟 (状态: {row['status']})，请关注配送/履约"
                )
                await _upsert_scheduler_alert(
                    conn,
                    alert_id=alert_id,
                    product_id=None,
                    alert_type="order_delay",
                    severity=severity,
                    title=f"订单 {row['order_id']} 异常延迟",
                    description=description,
                    metrics=metrics_payload,
                )
                order_alert_ids.append(alert_id)
                record_alert_triggered("order_delay", severity)
                anomalies.append({"anomaly_type": "order_delay", "severity": severity})

            await _resolve_stale_alerts(conn, "order_delay_%", order_alert_ids)

        duration = time.time() - start
        record_agent_execution("alert", duration, success=True)

        # 更新活跃预警数量
        count_map: dict[str, int] = {}
        try:
            counts = await pool.fetch(
                """
                SELECT severity, COUNT(*) as cnt
                FROM alerts
                WHERE status = 'pending'
                GROUP BY severity
                """
            )
            count_map = {r["severity"]: r["cnt"] for r in counts}
        except Exception:
            # alerts 表可能尚未创建，静默跳过避免刷屏日志
            logger.debug("alerts table unavailable, skip active alert count update")
        finally:
            update_active_alerts(
                count_map.get("critical", 0),
                count_map.get("warning", 0),
                count_map.get("info", 0),
            )

        logger.info(
            "Alert scan completed: %d low-stock, %d pending-order anomalies in %.1fs",
            len(low_stock_alert_ids),
            len(order_alert_ids),
            duration,
        )

    except Exception:
        logger.exception("Alert scan task failed")


async def bundle_mining_task() -> None:
    """套餐挖掘任务 (23:00)"""
    logger.info("Starting bundle mining task")
    try:
        import time

        from src.agents import Orchestrator
        from src.metrics import bundle_generated_total, record_agent_execution

        orch = Orchestrator()
        start = time.time()

        result = await orch.run_bundle()

        duration = time.time() - start
        record_agent_execution("bundle", duration, success=True)

        # 统计生成的套餐
        pricing = result.get("bundle_pricing", [])
        for p in pricing:
            status = "approved" if p.get("approved", False) else "rejected"
            bundle_generated_total.labels(status=status).inc()

        logger.info(f"Bundle mining completed: {len(pricing)} bundles in {duration:.1f}s")

    except Exception:
        logger.exception("Bundle mining task failed")


async def prophet_retrain_task() -> None:
    """Prophet 模型重训练任务 (每周日3:00)"""
    logger.info("Starting Prophet retrain task")
    try:
        import pandas as pd

        from src.db import postgres as pg
        from src.skills.database import DatabaseSkill
        from src.skills.prophet_skill import ProphetSkill

        pool = pg.get_pool()
        db_skill = DatabaseSkill(pool)
        prophet_skill = ProphetSkill(pool)

        # 获取活跃商品列表
        products = await db_skill.list_products(status="active", limit=500)

        trained_count = 0
        for product in products:
            try:
                # 获取历史销量数据
                sales_data = await db_skill.get_daily_sales(product.product_id, days=90)
                if len(sales_data) < 14:
                    continue

                df = pd.DataFrame(sales_data)
                df["ds"] = pd.to_datetime(df["ds"])
                df["y"] = df["y"].astype(float)

                await prophet_skill.train_model(product.product_id, df)
                trained_count += 1

            except Exception as e:
                logger.warning(f"Failed to train Prophet for {product.product_id}: {e}")

        logger.info(f"Prophet retrain completed: {trained_count} models trained")

    except Exception:
        logger.exception("Prophet retrain task failed")


async def daily_report_task() -> None:
    """每日报告任务 (22:00) — 使用 DailyReportService 生成智能日报"""
    logger.info("Starting daily report task")
    try:
        from src.services.daily_report import DailyReportService

        svc = DailyReportService()
        report = await svc.generate_daily_report()
        await svc.push_report(report)

        logger.info("Daily report generated and pushed for %s", report.date)

    except Exception:
        logger.exception("Daily report task failed")


async def competitor_crawl_task() -> None:
    """竞品数据采集任务 — 已迁移至 Chrome 扩展，此处为空操作。"""
    logger.info("Competitor crawl now handled by Chrome extension — skipping")


def _resolve_database_url() -> str | None:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    cfg = get_settings().system.database.get("postgres", {})
    required = ("user", "password", "host", "port", "database")
    if not all(k in cfg for k in required):
        return None
    return (
        f"postgresql://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
    )


# ── 数据采集任务已移除 ──────────────────────────────────────────────────────
# 美团/牵牛花数据采集已迁移至 Chrome 扩展 + 手动上传模式。
# 以下函数保留空实现，避免调度器引用断裂。

async def meituan_product_sync_task() -> None:
    """已迁移至 Chrome 扩展。"""
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_full_sync_task(target: str | None = None, days_back: int = 7) -> None:
    """已迁移至 Chrome 扩展。"""
    logger.info("Data collection now handled by Chrome extension — skipping")


async def qnh_full_sync_task() -> None:
    """已迁移至 Chrome 扩展。"""
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_products_full_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_orders_incremental_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_reviews_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_metrics_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_refunds_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_daily_metrics_etl_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_sales_history_etl_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_review_analysis_etl_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def meituan_promotions_stub_sync_task() -> None:
    logger.info("Data collection now handled by Chrome extension — skipping")


async def sales_aggregation_etl_task() -> None:
    """销售历史 & 日指标聚合 ETL（每天凌晨 2:00 CST）。"""
    logger.info("Starting sales aggregation ETL")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip sales aggregation ETL")
        return
    try:
        import asyncpg

        from src.sync.etl_sales_aggregation import run_sales_aggregation_etl

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            result = await run_sales_aggregation_etl(pool, days_back=2)
            logger.info(
                "Sales aggregation ETL done: sales_history=%s(%d) daily_metrics=%s(%d)",
                result.get("sales_history_status"),
                result.get("sales_history_rows", 0),
                result.get("daily_metrics_status"),
                result.get("daily_metrics_rows", 0),
            )
        finally:
            await pool.close()
    except Exception:
        logger.exception("Sales aggregation ETL task failed")


async def delivery_timeout_etl_task() -> None:
    """配送超时检测 ETL。"""
    logger.info("Starting delivery timeout ETL")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip delivery timeout ETL")
        return
    try:
        import asyncpg

        from src.sync.etl_delivery_timeout import run_delivery_timeout_etl

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            await run_delivery_timeout_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Delivery timeout ETL task failed")


async def platform_penalties_etl_task() -> None:
    """平台处罚/扣分检测 ETL。"""
    logger.info("Starting platform penalties ETL")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip platform penalties ETL")
        return
    try:
        import asyncpg

        from src.sync.etl_platform_penalties import run_platform_penalties_etl

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            await run_platform_penalties_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Platform penalties ETL task failed")


async def policy_crawler_etl_task() -> None:
    """售后政策爬取 ETL。"""
    logger.info("Starting policy crawler ETL")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip policy crawler ETL")
        return
    try:
        import asyncpg

        from src.sync.etl_policy_crawler import run_policy_crawler_etl

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            await run_policy_crawler_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Policy crawler ETL task failed")


async def competitor_changes_etl_task() -> None:
    """竞品价格变动检测 ETL。"""
    logger.info("Starting competitor changes ETL")
    try:
        import asyncpg

        from src.sync.etl_competitor_changes import run_competitor_changes_etl
        dsn = _resolve_database_url()
        if not dsn:
            return
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            await run_competitor_changes_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Competitor changes ETL failed")


async def product_associations_etl_task() -> None:
    """关联购买矩阵 ETL。"""
    logger.info("Starting product associations ETL")
    try:
        import asyncpg

        from src.sync.etl_product_associations import run_product_associations_etl
        dsn = _resolve_database_url()
        if not dsn:
            return
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            await run_product_associations_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Product associations ETL failed")


async def seasonality_etl_task() -> None:
    """季节性趋势标签 ETL。"""
    logger.info("Starting seasonality ETL")
    try:
        import asyncpg

        from src.sync.etl_seasonality import run_seasonality_etl
        dsn = _resolve_database_url()
        if not dsn:
            return
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            await run_seasonality_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Seasonality ETL failed")


async def auto_faq_etl_task() -> None:
    """FAQ 自动生成 ETL。"""
    logger.info("Starting auto FAQ ETL")
    try:
        import asyncpg

        from src.sync.etl_auto_faq import run_auto_faq_etl
        dsn = _resolve_database_url()
        if not dsn:
            return
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            await run_auto_faq_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Auto FAQ ETL failed")


async def effect_evaluation_etl_task() -> None:
    """Agent 决策效果评估 ETL。"""
    logger.info("Starting effect evaluation ETL")
    try:
        import asyncpg

        from src.sync.etl_effect_evaluation import run_effect_evaluation_etl

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip effect evaluation ETL")
            return
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            await run_effect_evaluation_etl(pool)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Effect evaluation ETL failed")


async def category_mapping_etl_task() -> None:
    """类目映射 ETL — 从商品表/竞品表构建类目映射（仅本地数据）。"""
    logger.info("Starting category mapping ETL")
    try:
        import asyncpg

        from src.sync.etl_category_mapping import run_category_mapping_etl

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip category mapping ETL")
            return

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            results = await run_category_mapping_etl(pool, None)
            logger.info("Category mapping ETL done: %s", results)
        finally:
            await pool.close()
    except Exception:
        logger.exception("Category mapping ETL failed")


async def graph_builder_etl_task() -> None:
    """PG -> Neo4j 图谱构建 ETL。"""
    logger.info("Starting graph builder ETL")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip graph builder ETL")
        return
    try:
        import asyncpg

        from src.db import neo4j as neo4j_db
        from src.sync.etl_graph_builder import run_graph_builder_etl

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            try:
                neo4j_driver = neo4j_db.get_driver()
            except Exception:
                neo4j_driver = await neo4j_db.init_driver()

            etl_result = await run_graph_builder_etl(pool, neo4j_driver)
            logger.info(
                "Graph builder ETL done: nodes_created=%d relationships_created=%d errors=%d",
                etl_result.get("nodes_created", 0),
                etl_result.get("relationships_created", 0),
                len(etl_result.get("errors", [])),
            )
            if etl_result.get("errors"):
                logger.warning("Graph builder ETL errors: %s", etl_result["errors"])
        finally:
            await pool.close()
    except Exception:
        logger.exception("Graph builder ETL failed")


async def qnh_data_sync_task() -> None:
    """数据同步任务（已迁移到 Chrome 扩展 + nodriver 链路，此处保留为空操作）。"""
    logger.info("Data sync now handled by Chrome extension / nodriver — skipping legacy task")


async def etl_pipeline_task() -> None:
    """ETL 任务（已迁移到 Chrome 扩展实时同步，此处保留为空操作）。"""
    logger.info("ETL now handled by real-time Chrome extension sync — skipping legacy task")


async def cookie_health_check_task() -> None:
    """Cookie 健康检查 — 数据采集已迁移至 Chrome 扩展，此任务为空操作。"""
    logger.info("Cookie health check skipped — data collection handled by Chrome extension")


async def daily_insights_warmup_task() -> None:
    """调用 /api/insights/daily 预热日报缓存."""
    logger.info("Starting daily insights warmup task")
    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{base_url}/api/insights/daily")
            logger.info("Daily insights warmup completed (status=%s)", resp.status_code)
    except Exception:
        logger.exception("Daily insights warmup task failed")


# ── 调度器初始化 ────────────────────────────────────────────────────────────


def init_scheduler() -> AsyncIOScheduler:
    """初始化并启动调度器"""
    scheduler = get_scheduler()

    settings = get_settings()
    tasks = settings.system.scheduled_tasks
    sync_mode = os.environ.get("SYNC_MODE", "remote").strip().lower()

    _register_remote_safe_jobs(scheduler, tasks)
    if sync_mode == "local":
        _register_local_only_jobs(scheduler, tasks)
    else:
        logger.info("SYNC_MODE=remote, browser-dependent jobs are disabled by default")

    logger.info(
        "Scheduler initialized in %s mode with %d jobs",
        sync_mode,
        len(scheduler.get_jobs()),
    )
    return scheduler


def start_scheduler() -> None:
    """启动调度器"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    """关闭调度器"""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler shutdown")


async def _upsert_scheduler_alert(
    conn,
    *,
    alert_id: str,
    product_id: str | None,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    metrics: dict | None,
) -> None:
    metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics is not None else None
    await conn.execute(
        """
        INSERT INTO alerts (alert_id, product_id, alert_type, severity, detection_method,
                            metrics, title, description, status, created_at)
        VALUES ($1, $2, $3, $4, 'scheduler', $5::jsonb, $6, $7, 'pending', NOW())
        ON CONFLICT (alert_id) DO UPDATE SET
            severity = EXCLUDED.severity,
            metrics = EXCLUDED.metrics,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            detection_method = 'scheduler',
            status = 'pending',
            resolved_at = NULL,
            root_cause = NULL,
            suggestion = NULL
        """,
        alert_id,
        product_id,
        alert_type,
        severity,
        metrics_json,
        title,
        description,
    )


async def _resolve_stale_alerts(conn, prefix: str, active_ids: Iterable[str]) -> None:
    ids = list(active_ids)
    if ids:
        await conn.execute(
            """
            UPDATE alerts
            SET status = 'resolved', resolved_at = NOW()
            WHERE alert_id LIKE $1 AND status = 'pending' AND alert_id <> ALL($2::text[])
            """,
            prefix,
            ids,
        )
    else:
        await conn.execute(
            """
            UPDATE alerts
            SET status = 'resolved', resolved_at = NOW()
            WHERE alert_id LIKE $1 AND status = 'pending'
            """,
            prefix,
        )


def _register_remote_safe_jobs(scheduler: AsyncIOScheduler, tasks: dict) -> None:
    """Jobs that can safely run on remote (browser-less) environments."""

    # Cookie 健康检查 (每30分钟)
    scheduler.add_job(
        _make_heartbeat_task("cookie_health_check", cookie_health_check_task),
        CronTrigger.from_crontab(tasks.get("cookie_health_check", "*/30 * * * *")),
        id="cookie_health_check",
        replace_existing=True,
    )

    # 预警扫描 (每5分钟)
    scheduler.add_job(
        _make_heartbeat_task("alert_scan", alert_scan_task),
        CronTrigger.from_crontab(tasks.get("alert_scan", "*/5 * * * *")),
        id="alert_scan",
        replace_existing=True,
    )

    # 反馈闭环追踪 (凌晨 2:00 CST)
    scheduler.add_job(
        _make_heartbeat_task("feedback_tracking", feedback_tracking_job),
        CronTrigger.from_crontab(
            tasks.get("feedback_tracking", "0 2 * * *"),
            timezone=SH_TZ,
        ),
        id="feedback_tracking",
        replace_existing=True,
    )

    # 每日报告 (UTC 13:00 = CST 21:00)
    scheduler.add_job(
        _make_heartbeat_task("daily_report", daily_report_task),
        CronTrigger.from_crontab(tasks.get("daily_report", "0 13 * * *")),
        id="daily_report",
        replace_existing=True,
    )

    # ETL (凌晨2:30, CST)
    scheduler.add_job(
        _make_heartbeat_task("etl_pipeline", etl_pipeline_task),
        CronTrigger.from_crontab(
            tasks.get("etl_pipeline", "30 2 * * *"),
            timezone=SH_TZ,
        ),
        id="etl_pipeline",
        replace_existing=True,
    )

    # 销售历史 & 日指标聚合 ETL (凌晨 2:00 CST)
    scheduler.add_job(
        _make_heartbeat_task("sales_aggregation_etl", sales_aggregation_etl_task),
        CronTrigger.from_crontab(
            tasks.get("sales_aggregation_etl", "0 2 * * *"),
            timezone=SH_TZ,
        ),
        id="sales_aggregation_etl",
        replace_existing=True,
    )

    # 每日选品 (6:00) — 不依赖浏览器
    scheduler.add_job(
        _make_heartbeat_task("daily_selection", daily_selection_task),
        CronTrigger.from_crontab(tasks.get("daily_selection", "0 6 * * *")),
        id="daily_selection",
        replace_existing=True,
    )

    # 套餐挖掘 (23:00) — 不依赖浏览器
    scheduler.add_job(
        _make_heartbeat_task("bundle_mining", bundle_mining_task),
        CronTrigger.from_crontab(tasks.get("bundle_mining", "0 23 * * *")),
        id="bundle_mining",
        replace_existing=True,
    )

    # 客服反馈自动学习 (每小时) — 从反馈数据更新 few-shot 示例
    scheduler.add_job(
        _make_heartbeat_task("cs_automatic_learning", cs_automatic_learning_task),
        CronTrigger.from_crontab(
            tasks.get("cs_automatic_learning", "0 * * * *"),
            timezone=SH_TZ,
        ),
        id="cs_automatic_learning",
        replace_existing=True,
    )


def _register_local_only_jobs(scheduler: AsyncIOScheduler, tasks: dict) -> None:
    """Jobs enabled in local mode.

    Note: browser/nodriver crawlers were removed. We only keep
    model training and ETL jobs that run on uploaded/synced DB data.
    """

    # Prophet 重训练 (每周日3:00)
    scheduler.add_job(
        _make_heartbeat_task("prophet_retrain", prophet_retrain_task),
        CronTrigger.from_crontab(tasks.get("prophet_retrain", "0 3 * * 0")),
        id="prophet_retrain",
        replace_existing=True,
    )

    # 日报预热 (凌晨3:00, CST)
    scheduler.add_job(
        _make_heartbeat_task("daily_insights_warmup", daily_insights_warmup_task),
        CronTrigger.from_crontab(
            tasks.get("daily_insights_warmup", "0 3 * * *"),
            timezone=SH_TZ,
        ),
        id="daily_insights_warmup",
        replace_existing=True,
    )

    # ETL jobs based on existing DB data
    scheduler.add_job(
        _make_heartbeat_task("delivery_timeout_etl", delivery_timeout_etl_task),
        CronTrigger.from_crontab(tasks.get("delivery_timeout_etl", "0 5 * * *"), timezone=SH_TZ),
        id="delivery_timeout_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("platform_penalties_etl", platform_penalties_etl_task),
        CronTrigger.from_crontab(tasks.get("platform_penalties_etl", "0 */4 * * *"), timezone=SH_TZ),
        id="platform_penalties_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("policy_crawler_etl", policy_crawler_etl_task),
        CronTrigger.from_crontab(tasks.get("policy_crawler_etl", "0 6 * * 1"), timezone=SH_TZ),
        id="policy_crawler_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("competitor_changes_etl", competitor_changes_etl_task),
        CronTrigger.from_crontab(tasks.get("competitor_changes_etl", "30 9 * * *"), timezone=SH_TZ),
        id="competitor_changes_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("product_associations_etl", product_associations_etl_task),
        CronTrigger.from_crontab(tasks.get("product_associations_etl", "0 4 * * *"), timezone=SH_TZ),
        id="product_associations_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("seasonality_etl", seasonality_etl_task),
        CronTrigger.from_crontab(tasks.get("seasonality_etl", "0 5 * * 0"), timezone=SH_TZ),
        id="seasonality_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("auto_faq_etl", auto_faq_etl_task),
        CronTrigger.from_crontab(tasks.get("auto_faq_etl", "0 10 * * *"), timezone=SH_TZ),
        id="auto_faq_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("effect_evaluation_etl", effect_evaluation_etl_task),
        CronTrigger.from_crontab(tasks.get("effect_evaluation_etl", "0 21 * * *"), timezone=SH_TZ),
        id="effect_evaluation_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("category_mapping_etl", category_mapping_etl_task),
        CronTrigger.from_crontab(tasks.get("category_mapping_etl", "30 4 * * *"), timezone=SH_TZ),
        id="category_mapping_etl",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("graph_builder_etl", graph_builder_etl_task),
        CronTrigger.from_crontab(tasks.get("graph_builder_etl", "30 5 * * *"), timezone=SH_TZ),
        id="graph_builder_etl",
        replace_existing=True,
    )
