"""
定时任务调度模块
使用 APScheduler 实现 SPEC 中定义的定时任务：
- 每日6点选品
- 每5分钟预警扫描
- 每日23点套餐挖掘
- 每周日3点 Prophet 重训练
"""

from __future__ import annotations

import asyncio
import logging
import os
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scripts.daily_sync_and_etl import (
    run_etl_pipeline,
    run_qnh_data_sync,
    run_store_stock_sync,
    trigger_daily_insights,
)
from src.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
SH_TZ = ZoneInfo("Asia/Shanghai")


def get_scheduler() -> AsyncIOScheduler:
    """获取调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


# ── 任务实现 ────────────────────────────────────────────────────────────────


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

        from src.agents import Orchestrator
        from src.db import postgres as pg
        from src.metrics import record_agent_execution, record_alert_triggered, update_active_alerts

        orch = Orchestrator()
        start = time.time()

        result = await orch.run_alert()

        duration = time.time() - start
        record_agent_execution("alert", duration, success=True)

        # 记录触发的预警
        anomalies = result.get("anomalies", {}).get("anomalies", [])
        for anomaly in anomalies:
            record_alert_triggered(
                anomaly.get("anomaly_type", "unknown"), anomaly.get("severity", "info")
            )

        # 更新活跃预警数量
        pool = pg.get_pool()
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

        logger.info(f"Alert scan completed: {len(anomalies)} anomalies in {duration:.1f}s")

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
                result = await syncer.full_sync()
                logger.info(
                    "Meituan product sync for %s: success=%s records=%s",
                    wm_poi_id, result.success, result.records_synced,
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


async def qnh_data_sync_task() -> None:
    """运行 QNH 数据同步 + 门店库存同步."""
    logger.info("Starting scheduled QNH data + store stock sync task")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip QNH data sync job")
        return
    try:
        dataset_result = await run_qnh_data_sync(dsn)
        logger.info(
            "QNH dataset sync completed (datasets=%d, errors=%d)",
            len(dataset_result["summary"]),
            len(dataset_result["errors"]),
        )
        stock_result = await run_store_stock_sync(dsn)
        logger.info(
            "Store stock sync completed (records=%s, success=%s)",
            stock_result.get("records_synced"),
            stock_result.get("success"),
        )
    except Exception:
        logger.exception("Scheduled QNH data sync task failed")


async def etl_pipeline_task() -> None:
    """运行 ETL，同步业务表."""
    logger.info("Starting scheduled ETL pipeline task")
    dsn = _resolve_database_url()
    if not dsn:
        logger.warning("DATABASE_URL unavailable — skip ETL job")
        return
    try:
        result = await run_etl_pipeline(dsn)
        logger.info(
            "ETL pipeline completed (products=%s, sales_history=%s)",
            result["products"].get("upserts"),
            result["sales_history"].get("upserts"),
        )
    except Exception:
        logger.exception("Scheduled ETL pipeline task failed")


async def daily_insights_warmup_task() -> None:
    """调用 /api/insights/daily 预热日报缓存."""
    logger.info("Starting daily insights warmup task")
    base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    try:
        result = await trigger_daily_insights(base_url)
        logger.info("Daily insights warmup completed (status=%s)", result["status_code"])
    except Exception:
        logger.exception("Daily insights warmup task failed")


# ── 调度器初始化 ────────────────────────────────────────────────────────────


def init_scheduler() -> AsyncIOScheduler:
    """初始化并启动调度器"""
    scheduler = get_scheduler()

    settings = get_settings()
    tasks = settings.system.scheduled_tasks

    # 每日选品 (6:00)
    scheduler.add_job(
        daily_selection_task,
        CronTrigger.from_crontab(tasks.get("daily_selection", "0 6 * * *")),
        id="daily_selection",
        replace_existing=True,
    )

    # 预警扫描 (每5分钟)
    scheduler.add_job(
        alert_scan_task,
        CronTrigger.from_crontab(tasks.get("alert_scan", "*/5 * * * *")),
        id="alert_scan",
        replace_existing=True,
    )

    # 套餐挖掘 (23:00)
    scheduler.add_job(
        bundle_mining_task,
        CronTrigger.from_crontab(tasks.get("bundle_mining", "0 23 * * *")),
        id="bundle_mining",
        replace_existing=True,
    )

    # Prophet 重训练 (每周日3:00)
    scheduler.add_job(
        prophet_retrain_task,
        CronTrigger.from_crontab(tasks.get("prophet_retrain", "0 3 * * 0")),
        id="prophet_retrain",
        replace_existing=True,
    )

    # 每日报告 (22:00)
    scheduler.add_job(
        daily_report_task,
        CronTrigger.from_crontab(tasks.get("daily_report", "0 22 * * *")),
        id="daily_report",
        replace_existing=True,
    )

    # 竞品采集 (8:00, 14:00)
    scheduler.add_job(
        competitor_crawl_task,
        CronTrigger.from_crontab(tasks.get("competitor_crawl_am", "0 8 * * *")),
        id="competitor_crawl_am",
        replace_existing=True,
    )
    scheduler.add_job(
        competitor_crawl_task,
        CronTrigger.from_crontab(tasks.get("competitor_crawl_pm", "0 14 * * *")),
        id="competitor_crawl_pm",
        replace_existing=True,
    )

    # 美团买药商品同步 (凌晨1:30, CST) — 主数据源
    scheduler.add_job(
        meituan_product_sync_task,
        CronTrigger.from_crontab(
            tasks.get("meituan_product_sync", "30 1 * * *"),
            timezone=SH_TZ,
        ),
        id="meituan_product_sync",
        replace_existing=True,
    )

    # QNH 数据同步 + 门店库存 (凌晨2:00, CST) — 补充数据源
    scheduler.add_job(
        qnh_data_sync_task,
        CronTrigger.from_crontab(
            tasks.get("qnh_data_sync", "0 2 * * *"),
            timezone=SH_TZ,
        ),
        id="qnh_data_sync",
        replace_existing=True,
    )

    # ETL (凌晨2:30, CST)
    scheduler.add_job(
        etl_pipeline_task,
        CronTrigger.from_crontab(
            tasks.get("etl_pipeline", "30 2 * * *"),
            timezone=SH_TZ,
        ),
        id="etl_pipeline",
        replace_existing=True,
    )

    # 日报预热 (凌晨3:00, CST)
    scheduler.add_job(
        daily_insights_warmup_task,
        CronTrigger.from_crontab(
            tasks.get("daily_insights_warmup", "0 3 * * *"),
            timezone=SH_TZ,
        ),
        id="daily_insights_warmup",
        replace_existing=True,
    )

    logger.info("Scheduler initialized with %d jobs", len(scheduler.get_jobs()))
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
