"""System configuration and admin API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/system", tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/config", response_model=APIResponse[dict])
async def get_config() -> APIResponse[dict]:
    pool = pg.get_pool()
    rows = await pool.fetch("SELECT key, value, updated_at FROM system_config ORDER BY key")
    data = {r["key"]: r["value"] for r in rows}
    return APIResponse(data=data)


@router.patch("/config", response_model=APIResponse[dict])
async def update_config(body: dict) -> APIResponse[dict]:
    pool = pg.get_pool()
    for key, value in body.items():
        await pool.execute(
            """INSERT INTO system_config (key, value, updated_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
            key,
            str(value),
        )
    return APIResponse(data=body, message="Config updated")


@router.get("/tasks", response_model=APIResponse[list[dict]])
async def list_tasks() -> APIResponse[list[dict]]:
    """List scheduled tasks and their status."""
    try:
        from src.scheduler import get_scheduler

        scheduler = get_scheduler()
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "task_name": job.name,
                    "job_id": job.id,
                    "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return APIResponse(data=jobs)
    except Exception:
        return APIResponse(data=[], message="Scheduler not available")


@router.post("/tasks/{task_name}/trigger", response_model=APIResponse[dict])
async def trigger_task(task_name: str) -> APIResponse[dict]:
    """Manually trigger a scheduled task by name."""
    from src.api.errors import NotFoundError

    task_map = {
        "daily_selection": "src.scheduler:daily_selection_task",
        "alert_scan": "src.scheduler:alert_scan_task",
        "bundle_mining": "src.scheduler:bundle_mining_task",
    }
    if task_name not in task_map:
        raise NotFoundError("Task", task_name)

    try:
        from src.scheduler import get_scheduler

        scheduler = get_scheduler()
        scheduler.add_job(
            task_map[task_name],
            id=f"manual_{task_name}",
            replace_existing=True,
        )
        return APIResponse(data={"task_name": task_name, "status": "triggered"})
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.get("/logs", response_model=APIResponse[list[dict]])
async def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: str | None = Query(None, pattern="^(INFO|WARNING|ERROR|DEBUG)$"),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    conditions = []
    params: list = []
    idx = 1
    if level:
        conditions.append(f"level = ${idx}")
        params.append(level)
        idx += 1
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"SELECT * FROM system_logs{where} ORDER BY created_at DESC LIMIT ${idx}",
        *params,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.post("/debug/fix-competitor-keywords", response_model=APIResponse[dict])
async def fix_competitor_keywords() -> APIResponse[dict]:
    """TEMPORARY: Fix the missing competitor_keywords table."""
    pool = pg.get_pool()
    try:
        # Create the missing table
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS competitor_keywords (
                keyword      TEXT PRIMARY KEY,
                search_volume INTEGER DEFAULT 0,
                result_count INTEGER DEFAULT 0,
                avg_price    REAL DEFAULT 0,
                last_synced  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_competitor_keywords_volume ON competitor_keywords(search_volume DESC);
            CREATE INDEX IF NOT EXISTS idx_competitor_keywords_synced ON competitor_keywords(last_synced);
        """)

        # Add sample data
        await pool.execute("""
            INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price)
            VALUES
                ('感冒药', 1200, 45, 25.5),
                ('维生素', 800, 32, 15.8),
                ('创可贴', 600, 28, 8.9)
            ON CONFLICT (keyword) DO NOTHING;
        """)

        count = await pool.fetchval("SELECT COUNT(*) FROM competitor_keywords")
        return APIResponse(
            data={"table_created": True, "rows": count}, message="competitor_keywords table fixed"
        )

    except Exception as e:
        return APIResponse(success=False, data={"error": str(e)}, message="Failed to fix table")
