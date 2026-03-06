"""System configuration and admin API routes."""

from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/system", tags=["system"])
# 根级别路由（不带前缀）
health_router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


# 根级别健康检查（满足前端期望的 /api/health 路径）
@health_router.get("/api/health", response_model=APIResponse[dict])
async def root_health() -> APIResponse[dict]:
    """Root level health check for /api/health"""
    try:
        pool = pg.get_pool()

        # Test database connection
        db_ok = False
        try:
            await pool.fetchval("SELECT 1")
            db_ok = True
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            db_ok = False

        # 快速健康检查（减少响应时间）
        health_data = {
            "status": "healthy" if db_ok else "degraded",
            "database": "ok" if db_ok else "error",
            "timestamp": datetime.now().isoformat(),
            "service": "AI店长",
        }

        return APIResponse(data=health_data)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return APIResponse(
            success=False,
            message=f"健康检查失败: {str(e)}",
            data={"status": "unhealthy", "error": str(e)},
        )


@router.get("/health", response_model=APIResponse[dict])
async def health() -> APIResponse[dict]:
    """System health check."""
    try:
        pool = pg.get_pool()

        # Test database connection
        db_ok = False
        try:
            await pool.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False

        # Test Redis connection
        redis_ok = False
        try:
            from src.db import redis as redis_db

            redis_client = redis_db.get_redis()
            if redis_client:
                await redis_client.ping()
                redis_ok = True
        except Exception:
            redis_ok = False

        # Check disk space (basic check)
        import shutil

        disk_usage = shutil.disk_usage("/")
        disk_free_gb = disk_usage.free / (1024**3)
        disk_ok = disk_free_gb > 1.0  # At least 1GB free

        # Overall health status
        overall_healthy = db_ok and disk_ok  # Redis is optional

        return APIResponse(
            data={
                "status": "healthy" if overall_healthy else "unhealthy",
                "database": "ok" if db_ok else "error",
                "redis": "ok" if redis_ok else "error",
                "disk_free_gb": round(disk_free_gb, 2),
                "disk_status": "ok" if disk_ok else "low",
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return APIResponse(
            success=False, data={"status": "error", "error": str(e)}, message="Health check failed"
        )


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


@router.get("/scheduler-status", response_model=APIResponse[list[dict]])
async def get_scheduler_status() -> APIResponse[list[dict]]:
    """获取每个定时任务的心跳状态：上次运行时间、状态、下次预计运行。

    数据来源：
    - scheduler_heartbeat 表（持久化运行记录）
    - APScheduler 内存中的 job 列表（实时 next_run_time）
    """
    # 从调度器获取当前 job 信息（实时 next_run_time）
    scheduler_jobs: dict[str, dict] = {}
    try:
        from src.scheduler import get_scheduler

        scheduler = get_scheduler()
        for job in scheduler.get_jobs():
            scheduler_jobs[job.id] = {
                "job_id": job.id,
                "trigger": str(job.trigger),
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "scheduler_running": scheduler.running,
            }
    except Exception as exc:
        logger.warning("Scheduler not available: %s", exc)

    # 从数据库读取持久化心跳记录
    db_records: dict[str, dict] = {}
    try:
        pool = pg.get_pool()
        rows = await pool.fetch(
            """
            SELECT task_name, last_run, next_run, status, error_msg, run_count, updated_at
            FROM scheduler_heartbeat
            ORDER BY task_name
            """
        )
        for row in rows:
            db_records[row["task_name"]] = {
                "task_name": row["task_name"],
                "last_run": row["last_run"].isoformat() if row["last_run"] else None,
                "next_run": row["next_run"].isoformat() if row["next_run"] else None,
                "status": row["status"],
                "error_msg": row["error_msg"],
                "run_count": row["run_count"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
    except Exception as exc:
        logger.warning("Failed to read scheduler_heartbeat: %s", exc)

    # 合并两个数据源
    all_task_ids = set(scheduler_jobs) | set(db_records)
    result = []
    for task_id in sorted(all_task_ids):
        sched = scheduler_jobs.get(task_id, {})
        db = db_records.get(task_id, {})
        # 优先使用调度器的 next_run_time（实时）
        next_run = sched.get("next_run_time") or db.get("next_run")
        result.append(
            {
                "task_name": task_id,
                "trigger": sched.get("trigger"),
                "scheduler_running": sched.get("scheduler_running", False),
                "last_run": db.get("last_run"),
                "next_run": next_run,
                "status": db.get("status", "unknown"),
                "error_msg": db.get("error_msg"),
                "run_count": db.get("run_count", 0),
                "updated_at": db.get("updated_at"),
            }
        )

    return APIResponse(data=result)


@router.get("/memory-usage", response_model=APIResponse[dict])
async def get_memory_usage() -> APIResponse[dict]:
    """返回当前进程的内存占用详情（MB），用于 512MB 环境下的内存监控。"""
    import gc

    result: dict = {
        "timestamp": datetime.now().isoformat(),
        "process": {},
        "system": {},
    }

    # ── 进程内存（psutil）──────────────────────────────
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        mem_full = proc.memory_full_info()
        result["process"] = {
            "rss_mb": round(mem_info.rss / 1024**2, 2),
            "vms_mb": round(mem_info.vms / 1024**2, 2),
            "uss_mb": round(mem_full.uss / 1024**2, 2),  # unique set size (most accurate)
            "pid": os.getpid(),
        }
        # 系统整体内存
        sys_mem = psutil.virtual_memory()
        result["system"] = {
            "total_mb": round(sys_mem.total / 1024**2, 2),
            "available_mb": round(sys_mem.available / 1024**2, 2),
            "used_mb": round(sys_mem.used / 1024**2, 2),
            "percent": sys_mem.percent,
        }
    except ImportError:
        # psutil 未安装，退回 /proc/self/status
        try:
            with open("/proc/self/status") as f:
                status = {
                    line.split(":")[0]: line.split(":")[1].strip()
                    for line in f
                    if ":" in line
                }
            vm_rss = int(status.get("VmRSS", "0 kB").split()[0])
            vm_vms = int(status.get("VmSize", "0 kB").split()[0])
            result["process"] = {
                "rss_mb": round(vm_rss / 1024, 2),
                "vms_mb": round(vm_vms / 1024, 2),
                "note": "psutil not installed, read from /proc/self/status",
            }
        except Exception as e:
            result["process"] = {"error": str(e)}
    except Exception as e:
        result["process"] = {"error": str(e)}

    # ── Python GC 对象数量（调试参考）──────────────────
    gc.collect()
    result["gc"] = {
        "objects": len(gc.get_objects()),
        "collections": list(gc.get_count()),
    }

    # ── 快速判断是否超出 512MB 阈值 ────────────────────
    rss = result.get("process", {}).get("rss_mb", 0)
    result["warning"] = rss > 400  # > 400MB 时告警

    return APIResponse(data=result)
