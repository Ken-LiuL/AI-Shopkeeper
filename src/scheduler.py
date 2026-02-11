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
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


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
        from src.agents import Orchestrator
        from src.metrics import record_agent_execution, selection_run_total
        import time

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
        
    except Exception as e:
        logger.exception("Daily selection task failed")
        from src.metrics import selection_run_total
        selection_run_total.labels(trigger="scheduled", status="failed").inc()


async def alert_scan_task() -> None:
    """预警扫描任务 (每5分钟)"""
    logger.info("Starting alert scan task")
    try:
        from src.agents import Orchestrator
        from src.metrics import record_agent_execution, record_alert_triggered, update_active_alerts
        from src.db import postgres as pg
        import time

        orch = Orchestrator()
        start = time.time()
        
        result = await orch.run_alert()
        
        duration = time.time() - start
        record_agent_execution("alert", duration, success=True)
        
        # 记录触发的预警
        anomalies = result.get("anomalies", {}).get("anomalies", [])
        for anomaly in anomalies:
            record_alert_triggered(anomaly.get("anomaly_type", "unknown"), anomaly.get("severity", "info"))
        
        # 更新活跃预警数量
        pool = pg.get_pool()
        counts = await pool.fetch(
            "SELECT severity, COUNT(*) as cnt FROM alerts WHERE status = 'pending' GROUP BY severity"
        )
        count_map = {r["severity"]: r["cnt"] for r in counts}
        update_active_alerts(
            count_map.get("critical", 0),
            count_map.get("warning", 0),
            count_map.get("info", 0),
        )
        
        logger.info(f"Alert scan completed: {len(anomalies)} anomalies in {duration:.1f}s")
        
    except Exception as e:
        logger.exception("Alert scan task failed")


async def bundle_mining_task() -> None:
    """套餐挖掘任务 (23:00)"""
    logger.info("Starting bundle mining task")
    try:
        from src.agents import Orchestrator
        from src.metrics import record_agent_execution, bundle_generated_total
        import time

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
        
    except Exception as e:
        logger.exception("Bundle mining task failed")


async def prophet_retrain_task() -> None:
    """Prophet 模型重训练任务 (每周日3:00)"""
    logger.info("Starting Prophet retrain task")
    try:
        from src.skills.prophet_skill import ProphetSkill
        from src.skills.database import DatabaseSkill
        from src.db import postgres as pg
        import pandas as pd

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
        
    except Exception as e:
        logger.exception("Prophet retrain task failed")


async def daily_report_task() -> None:
    """每日报告任务 (22:00)"""
    logger.info("Starting daily report task")
    try:
        from src.skills.notifier import NotifierSkill, DailyReportPayload
        from src.skills.database import DatabaseSkill
        from src.db import postgres as pg
        from datetime import date

        pool = pg.get_pool()
        db_skill = DatabaseSkill(pool)
        
        # 获取今日统计
        today = date.today()
        stats = await db_skill.get_sales_stats(start_date=today, end_date=today)
        
        total_revenue = sum(s.total_revenue for s in stats)
        total_orders = sum(s.order_count for s in stats)
        avg_margin = sum(s.gross_margin for s in stats) / len(stats) if stats else 0
        
        # 获取预警数量
        alerts = await db_skill.get_alerts(status="open", limit=100)
        
        # 获取最新选品推荐
        runs = await db_skill.get_latest_selection_runs(limit=1)
        recommendations = []
        if runs and runs[0].results:
            recommendations = runs[0].results.get("recommendations", [])[:5]
        
        # 发送报告
        notifier = NotifierSkill(webhook_url=os.environ.get("WECHAT_WEBHOOK_URL", ""))
        await notifier.send_daily_report(DailyReportPayload(
            date=str(today),
            metrics={
                "total_revenue": total_revenue,
                "total_orders": total_orders,
                "avg_margin": avg_margin,
                "alert_count": len(alerts),
            },
            top_recommendations=recommendations,
        ))
        
        logger.info("Daily report sent")
        
    except Exception as e:
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
        
    except Exception as e:
        logger.exception("Competitor crawl task failed")


# ── 调度器初始化 ────────────────────────────────────────────────────────────

import os

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
