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
    """竞品数据采集任务 (8:00, 14:00)"""
    logger.info("Starting competitor crawl task")
    try:
        from src.skills.actionbook import ActionBookSkill

        skill = ActionBookSkill()

        # 获取竞品店铺
        stores = await skill.competitor_stores("default_store", radius_km=3.0)
        logger.info(f"Found {len(stores)} competitor stores")

        # 获取竞品商品
        for store in stores:
            products = await skill.competitor_products("default_store", store.store_id, limit=50)
            logger.info(f"Crawled {len(products)} products from {store.name}")
            await asyncio.sleep(1)  # 限速

        logger.info("Competitor crawl completed")

    except Exception:
        logger.exception("Competitor crawl task failed")


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


async def meituan_product_sync_task() -> None:
    """美团买药商品同步 (主数据源)."""
    logger.info("Starting Meituan product sync task")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip Meituan sync")
        return
    try:
        import asyncpg

        from src.sync.meituan_client import MeituanBrowserClient
        from src.sync.meituan_products import MeituanProductSyncer

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            # 从 store_configs 获取活跃门店
            async with pool.acquire() as conn:
                stores = await conn.fetch(
                    "SELECT wm_poi_id, cookie_json FROM store_configs WHERE sync_status = 'active' AND platform = 'meituan_yiyao'"
                )

            for store in stores:
                wm_poi_id = store["wm_poi_id"]
                logger.info("Syncing Meituan store %s", wm_poi_id)
                client = MeituanBrowserClient(wm_poi_id=wm_poi_id)
                syncer = MeituanProductSyncer(client, pool, wm_poi_id)
                result = await syncer.sync()
                logger.info(
                    "Meituan product sync for %s: success=%s records=%s",
                    wm_poi_id,
                    result.success,
                    result.records_synced,
                )
                # 更新 sync 状态
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE store_configs SET last_sync_at = NOW(), last_sync_error = $1 WHERE wm_poi_id = $2",
                        result.error if not result.success else None,
                        wm_poi_id,
                    )
                await client.close()
        finally:
            await pool.close()
    except Exception:
        logger.exception("Meituan product sync task failed")


async def meituan_full_sync_task(target: str | None = None, days_back: int = 7) -> None:
    """定时数据同步（使用 nodriver + YiyaoFullSyncer）。"""
    logger.info("Starting Meituan full sync via nodriver (target=%s)", target or "all")
    try:
        from src.sync.meituan_client import MeituanBrowserClient
        from src.sync.yiyao_syncer import YiyaoFullSyncer
        import asyncpg

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip sync")
            return

        wm_poi_id = os.environ.get("WM_POI_ID", "")
        if not wm_poi_id:
            logger.warning("WM_POI_ID not set — skip sync")
            return

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)

        # 尝试从 DB 读取最新 Cookie
        cookie_json = None
        try:
            row = await pool.fetchrow(
                "SELECT cookie_json FROM merchant_sync_cookies "
                "WHERE is_active = true ORDER BY updated_at DESC LIMIT 1"
            )
            if row and row["cookie_json"]:
                import json as _json
                cookie_json = _json.loads(row["cookie_json"]) if isinstance(row["cookie_json"], str) else row["cookie_json"]
                logger.info("从 DB 加载 Cookie（%d 个键）", len(cookie_json))
        except Exception:
            logger.debug("DB Cookie 表不存在或查询失败，将使用文件/环境变量")

        client = MeituanBrowserClient(wm_poi_id=wm_poi_id, cookie_json=cookie_json)
        try:
            syncer = YiyaoFullSyncer(client=client, pool=pool, wm_poi_id=wm_poi_id, days_back=days_back)
            if target == "products":
                results = [await syncer.sync_products()]
            elif target == "orders":
                results = [await syncer.sync_orders()]
            elif target == "reviews":
                results = [await syncer.sync_reviews()]
            elif target == "metrics":
                results = [await syncer.sync_stats()]
            elif target == "refunds":
                results = [await syncer.sync_refunds()]
            elif target == "promotions":
                results = [await syncer.sync_promotions()]
            elif target == "review_analysis":
                results = [await syncer.sync_review_analysis()]
            else:
                results = await syncer.sync_all()

            for r in results:
                if r.success:
                    logger.info("✅ %s: %d 条, %d 页", r.syncer, r.records, r.pages)
                else:
                    logger.error("❌ %s: %s", r.syncer, r.error)
        finally:
            await client.close()
            await pool.close()
    except Exception:
        logger.exception("Meituan full sync failed")


async def qnh_full_sync_task() -> None:
    """牵牛花全量同步任务（QNH goldengateway + IM）。"""
    logger.info("Starting QNH full sync")
    try:
        import asyncpg
        import time

        from src.sync.channels import ChannelSyncer
        from src.sync.competitors import CompetitorSyncer
        from src.sync.customers import CustomerSyncer
        from src.sync.finance import FinanceSyncer
        from src.sync.im_history import IMHistorySyncer
        from src.sync.inventory import InventorySyncer
        from src.sync.products import ProductSyncer
        from src.sync.promotions import PromotionSyncer
        from src.sync.qnh_auth import QNHAuth
        from src.sync.qnh_client import QNHClient
        from src.sync.traffic import TrafficSyncer

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip QNH sync")
            return

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            cookie_json = None
            try:
                row = await pool.fetchrow(
                    "SELECT cookie_json FROM merchant_sync_cookies "
                    "WHERE is_active = true ORDER BY updated_at DESC LIMIT 1"
                )
                if row and row["cookie_json"]:
                    raw_cookie = row["cookie_json"]
                    cookie_json = (
                        json.loads(raw_cookie) if isinstance(raw_cookie, str) else raw_cookie
                    )
                    logger.info("QNH 从 DB 加载 Cookie（%d 个键）", len(cookie_json))
            except Exception:
                logger.debug("QNH Cookie 查询失败，将使用文件/环境变量")

            auth = QNHAuth()
            if cookie_json:
                auth._cookies = {str(k): str(v) for k, v in cookie_json.items()}
                auth._session_expires = time.time() + 7200

            client = QNHClient(auth=auth)
            try:
                syncers = [
                    ProductSyncer(client, pool),
                    PromotionSyncer(client, pool),
                    TrafficSyncer(client, pool),
                    InventorySyncer(client, pool),
                    CustomerSyncer(client, pool),
                    ChannelSyncer(client, pool),
                    CompetitorSyncer(pool),
                    FinanceSyncer(client, pool),
                    IMHistorySyncer(client, pool),
                ]
                results = []
                for syncer in syncers:
                    result = await syncer.sync()
                    results.append(result)
                    if result.success:
                        logger.info(
                            "✅ QNH %s: %d records",
                            result.syncer_name,
                            result.records_synced,
                        )
                    else:
                        logger.error("❌ QNH %s: %s", result.syncer_name, result.error)

                ok = sum(1 for item in results if item.success)
                failed = len(results) - ok
                total_records = sum(item.records_synced for item in results)
                logger.info(
                    "QNH full sync finished: success=%d failed=%d total_records=%d",
                    ok,
                    failed,
                    total_records,
                )
            finally:
                await client.close()
        finally:
            await pool.close()
    except Exception:
        logger.exception("QNH full sync failed")


async def meituan_products_full_sync_task() -> None:
    await meituan_full_sync_task(target="products", days_back=7)


async def meituan_orders_incremental_sync_task() -> None:
    await meituan_full_sync_task(target="orders", days_back=7)


async def meituan_reviews_sync_task() -> None:
    await meituan_full_sync_task(target="reviews", days_back=7)


async def meituan_metrics_sync_task() -> None:
    await meituan_full_sync_task(target="metrics", days_back=7)


async def meituan_refunds_sync_task() -> None:
    await meituan_full_sync_task(target="refunds", days_back=30)


async def _run_meituan_db_only_etl(target: str) -> None:
    logger.info("Starting Meituan DB-only ETL (target=%s)", target)
    try:
        import asyncpg
        from src.sync.yiyao_syncer import YiyaoFullSyncer

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip DB-only ETL")
            return

        wm_poi_id = os.environ.get("WM_POI_ID", "")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            syncer = YiyaoFullSyncer(client=None, pool=pool, wm_poi_id=wm_poi_id or "db_etl", days_back=7)
            if target == "daily_metrics":
                result = await syncer.sync_daily_metrics()
            elif target == "sales_history":
                result = await syncer.sync_sales_history()
            elif target == "review_analysis":
                result = await syncer.sync_review_analysis()
            elif target == "promotions":
                result = await syncer.sync_promotions()
            else:
                raise ValueError(f"Unsupported Meituan DB-only ETL target: {target}")
            logger.info(
                "Meituan DB-only ETL done: target=%s success=%s records=%d pages=%d",
                target,
                result.success,
                result.records,
                result.pages,
            )
        finally:
            await pool.close()
    except Exception:
        logger.exception("Meituan DB-only ETL failed (target=%s)", target)


async def meituan_daily_metrics_etl_task() -> None:
    await _run_meituan_db_only_etl("daily_metrics")


async def meituan_sales_history_etl_task() -> None:
    await _run_meituan_db_only_etl("sales_history")


async def meituan_review_analysis_etl_task() -> None:
    await _run_meituan_db_only_etl("review_analysis")


async def meituan_promotions_stub_sync_task() -> None:
    await _run_meituan_db_only_etl("promotions")


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
    """类目映射 ETL — 从商品表/竞品表/QNH API 构建类目映射。"""
    logger.info("Starting category mapping ETL")
    try:
        import asyncpg
        import time

        from src.sync.etl_category_mapping import run_category_mapping_etl
        from src.sync.qnh_auth import QNHAuth
        from src.sync.qnh_client import QNHClient

        dsn = _resolve_database_url()
        if not dsn:
            logger.warning("DATABASE_URL unavailable — skip category mapping ETL")
            return

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        try:
            # 尝试创建 QNH client（用于 storeCategory API）
            qnh_client = None
            try:
                row = await pool.fetchrow(
                    "SELECT cookie_json FROM merchant_sync_cookies "
                    "WHERE is_active = true ORDER BY updated_at DESC LIMIT 1"
                )
                if row and row["cookie_json"]:
                    raw = row["cookie_json"]
                    cookie_json = json.loads(raw) if isinstance(raw, str) else raw
                    auth = QNHAuth()
                    auth._cookies = {str(k): str(v) for k, v in cookie_json.items()}
                    auth._session_expires = time.time() + 7200
                    qnh_client = QNHClient(auth=auth)
            except Exception:
                logger.debug("无法创建 QNH client，仅使用本地数据")

            results = await run_category_mapping_etl(pool, qnh_client)
            logger.info("Category mapping ETL done: %s", results)

            if qnh_client:
                await qnh_client.close()
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
    """Cookie 健康检查任务（每 30 分钟）。

    若美团同步超过 2 小时未成功，写入一条 SYNC_FAILURE 告警。
    """
    logger.info("Starting cookie health check task")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip cookie health check")
        return
    try:
        import asyncpg
        from src.sync.cookie_health import check_cookie_health

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            result = await check_cookie_health(pool)
            logger.info(
                "Cookie health: status=%s hours_since_last_sync=%s",
                result["status"],
                result.get("hours_since_last_sync"),
            )

            if result["status"] == "STALE":
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO alerts (
                            alert_id, product_id, alert_type, severity,
                            detection_method, metrics, title, description,
                            status, created_at
                        ) VALUES (
                            'sync_cookie_stale', NULL, 'SYNC_FAILURE', 'critical',
                            'scheduler',
                            $1::jsonb,
                            '美团数据同步中断 — Cookie 可能已过期',
                            $2,
                            'pending', NOW()
                        )
                        ON CONFLICT (alert_id) DO UPDATE SET
                            severity     = 'critical',
                            metrics      = EXCLUDED.metrics,
                            description  = EXCLUDED.description,
                            status       = 'pending',
                            resolved_at  = NULL
                        """,
                        __import__("json").dumps({
                            "hours_since_last_sync": result.get("hours_since_last_sync"),
                            "stale_threshold_hours": result["stale_threshold_hours"],
                            "last_success_at": result.get("last_success_at"),
                        }),
                        result["message"],
                    )
                logger.warning("SYNC_FAILURE alert written: %s", result["message"])
            else:
                # 若已恢复，自动 resolve 告警
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE alerts
                        SET status = 'resolved', resolved_at = NOW()
                        WHERE alert_id = 'sync_cookie_stale'
                          AND status = 'pending'
                        """
                    )
        finally:
            await pool.close()

    except Exception:
        logger.exception("Cookie health check task failed")


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

    # 每日报告 (22:00)
    scheduler.add_job(
        _make_heartbeat_task("daily_report", daily_report_task),
        CronTrigger.from_crontab(tasks.get("daily_report", "0 22 * * *")),
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


def _register_local_only_jobs(scheduler: AsyncIOScheduler, tasks: dict) -> None:
    """Jobs that require local resources (browser/nodriver/agent warmups)."""

    # Prophet 重训练 (每周日3:00)
    scheduler.add_job(
        _make_heartbeat_task("prophet_retrain", prophet_retrain_task),
        CronTrigger.from_crontab(tasks.get("prophet_retrain", "0 3 * * 0")),
        id="prophet_retrain",
        replace_existing=True,
    )

    # 竞品采集 (8:00, 14:00)
    scheduler.add_job(
        _make_heartbeat_task("competitor_crawl_am", competitor_crawl_task),
        CronTrigger.from_crontab(tasks.get("competitor_crawl_am", "0 8 * * *")),
        id="competitor_crawl_am",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("competitor_crawl_pm", competitor_crawl_task),
        CronTrigger.from_crontab(tasks.get("competitor_crawl_pm", "0 14 * * *")),
        id="competitor_crawl_pm",
        replace_existing=True,
    )

    # 美团买药商品同步 (凌晨1:30, CST) — 主数据源
    scheduler.add_job(
        _make_heartbeat_task("meituan_product_sync", meituan_product_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_product_sync", "30 1 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_product_sync",
        replace_existing=True,
    )

    # ── 美团 YiyaoFullSyncer 定时采集 ──────────────────────────────────
    scheduler.add_job(
        _make_heartbeat_task("meituan_full_sync_products", meituan_products_full_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_full_sync_products", "0 2 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_full_sync_products",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("qnh_full_sync", qnh_full_sync_task),
        CronTrigger.from_crontab(
            tasks.get("qnh_full_sync", "0 3 * * *"),
            timezone=SH_TZ,
        ),
        id="qnh_full_sync",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("meituan_sync_orders_hourly", meituan_orders_incremental_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_sync_orders_hourly", "0 * * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_sync_orders_hourly",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("meituan_sync_reviews_6h", meituan_reviews_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_sync_reviews_6h", "0 */6 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_sync_reviews_6h",
        replace_existing=True,
    )
    scheduler.add_job(
        _make_heartbeat_task("meituan_sync_metrics_daily", meituan_metrics_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_sync_metrics_daily", "0 6 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_sync_metrics_daily",
        replace_existing=True,
    )

    # 退款同步：每 6 小时
    scheduler.add_job(
        _make_heartbeat_task("meituan_sync_refunds", meituan_refunds_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_sync_refunds", "0 */6 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_sync_refunds",
        replace_existing=True,
    )

    # 日报指标 ETL：每天 7:00（在统计数据同步后）
    scheduler.add_job(
        _make_heartbeat_task("meituan_daily_metrics_etl", meituan_daily_metrics_etl_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_daily_metrics_etl", "0 7 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_daily_metrics_etl",
        replace_existing=True,
    )

    # 销售历史聚合：每天 8:00
    scheduler.add_job(
        _make_heartbeat_task("meituan_sales_history_etl", meituan_sales_history_etl_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_sales_history_etl", "0 8 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_sales_history_etl",
        replace_existing=True,
    )

    # 评价分析 ETL：每天 8:30
    scheduler.add_job(
        _make_heartbeat_task("meituan_review_analysis_etl", meituan_review_analysis_etl_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_review_analysis_etl", "30 8 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_review_analysis_etl",
        replace_existing=True,
    )

    # 促销表 stub 保活：每天 9:00
    scheduler.add_job(
        _make_heartbeat_task("meituan_promotions_stub_sync", meituan_promotions_stub_sync_task),
        CronTrigger.from_crontab(
            tasks.get("meituan_promotions_stub_sync", "0 9 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_promotions_stub_sync",
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

    # 配送超时检测：每天 05:00 CST
    scheduler.add_job(
        _make_heartbeat_task("delivery_timeout_etl", delivery_timeout_etl_task),
        CronTrigger.from_crontab(
            tasks.get("delivery_timeout_etl", "0 5 * * *"),
            timezone=SH_TZ,
        ),
        id="delivery_timeout_etl",
        replace_existing=True,
    )

    # 平台处罚检测：每 4 小时
    scheduler.add_job(
        _make_heartbeat_task("platform_penalties_etl", platform_penalties_etl_task),
        CronTrigger.from_crontab(
            tasks.get("platform_penalties_etl", "0 */4 * * *"),
            timezone=SH_TZ,
        ),
        id="platform_penalties_etl",
        replace_existing=True,
    )

    # 政策爬取：每周一 06:00 CST
    scheduler.add_job(
        _make_heartbeat_task("policy_crawler_etl", policy_crawler_etl_task),
        CronTrigger.from_crontab(
            tasks.get("policy_crawler_etl", "0 6 * * 1"),
            timezone=SH_TZ,
        ),
        id="policy_crawler_etl",
        replace_existing=True,
    )

    # 竞品价格变动：每天 09:30 CST（竞品采集 08:00 之后）
    scheduler.add_job(
        _make_heartbeat_task("competitor_changes_etl", competitor_changes_etl_task),
        CronTrigger.from_crontab(
            tasks.get("competitor_changes_etl", "30 9 * * *"),
            timezone=SH_TZ,
        ),
        id="competitor_changes_etl",
        replace_existing=True,
    )

    # 关联购买矩阵：每天 04:00 CST（订单同步后）
    scheduler.add_job(
        _make_heartbeat_task("product_associations_etl", product_associations_etl_task),
        CronTrigger.from_crontab(
            tasks.get("product_associations_etl", "0 4 * * *"),
            timezone=SH_TZ,
        ),
        id="product_associations_etl",
        replace_existing=True,
    )

    # 季节性趋势：每周日 05:00 CST
    scheduler.add_job(
        _make_heartbeat_task("seasonality_etl", seasonality_etl_task),
        CronTrigger.from_crontab(
            tasks.get("seasonality_etl", "0 5 * * 0"),
            timezone=SH_TZ,
        ),
        id="seasonality_etl",
        replace_existing=True,
    )

    # FAQ 自动生成：每天 10:00 CST
    scheduler.add_job(
        _make_heartbeat_task("auto_faq_etl", auto_faq_etl_task),
        CronTrigger.from_crontab(
            tasks.get("auto_faq_etl", "0 10 * * *"),
            timezone=SH_TZ,
        ),
        id="auto_faq_etl",
        replace_existing=True,
    )

    # 决策效果评估：每天 21:00 CST
    scheduler.add_job(
        _make_heartbeat_task("effect_evaluation_etl", effect_evaluation_etl_task),
        CronTrigger.from_crontab(
            tasks.get("effect_evaluation_etl", "0 21 * * *"),
            timezone=SH_TZ,
        ),
        id="effect_evaluation_etl",
        replace_existing=True,
    )

    # 类目映射 ETL：每天 04:30 CST（商品同步后）
    scheduler.add_job(
        _make_heartbeat_task("category_mapping_etl", category_mapping_etl_task),
        CronTrigger.from_crontab(
            tasks.get("category_mapping_etl", "30 4 * * *"),
            timezone=SH_TZ,
        ),
        id="category_mapping_etl",
        replace_existing=True,
    )

    # PG -> Neo4j 图谱构建：每天 05:30 CST（在商品同步和 ETL 之后）
    scheduler.add_job(
        _make_heartbeat_task("graph_builder_etl", graph_builder_etl_task),
        CronTrigger.from_crontab(
            tasks.get("graph_builder_etl", "30 5 * * *"),
            timezone=SH_TZ,
        ),
        id="graph_builder_etl",
        replace_existing=True,
    )
