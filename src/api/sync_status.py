"""同步状态 API。

提供 GET /api/sync/health 端点，返回同步状态信息。
数据采集已迁移至 Chrome 扩展 + 手动上传模式。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)


async def get_syncer_status_list(pool) -> list[dict[str, Any]]:
    """Query sync_state and return normalized syncer run status list."""
    try:
        rows = await pool.fetch(
            """
            SELECT
                syncer_name,
                COALESCE(last_sync_status, 'unknown') AS last_sync_status,
                COALESCE(last_incremental_sync, last_full_sync, updated_at) AS last_sync_time,
                COALESCE(records_synced, 0) AS records_synced,
                COALESCE(last_sync_duration_ms, 0) AS duration_ms
            FROM sync_state
            ORDER BY updated_at DESC NULLS LAST
            """
        )
    except Exception:
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        sync_time = row["last_sync_time"]
        result.append(
            {
                "syncer_name": row["syncer_name"] or "unknown",
                "last_sync_status": row["last_sync_status"] or "unknown",
                "last_sync_time": sync_time.isoformat() if sync_time else None,
                "records_synced": int(row["records_synced"] or 0),
                "duration_ms": int(row["duration_ms"] or 0),
            }
        )
    return result


@router.get("/health", response_model=APIResponse[dict])
async def sync_health() -> APIResponse[dict]:
    """返回数据同步健康状态。

    数据采集已迁移至 Chrome 扩展 + 手动上传模式。
    此端点返回最近的同步记录摘要。
    """
    try:
        pool = pg.get_pool()
        syncer_list = await get_syncer_status_list(pool)

        data = {
            "mode": "chrome_extension",
            "message": "数据采集已迁移至 Chrome 扩展 + 手动上传",
            "syncer_count": len(syncer_list),
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

        return APIResponse(
            success=True,
            data=data,
            message="数据通过 Chrome 扩展或手动上传同步",
        )

    except Exception as e:
        logger.error("sync_health endpoint failed: %s", e, exc_info=True)
        return APIResponse(
            success=False,
            data={"error": str(e)},
            message=f"同步健康检查失败: {e}",
        )


@router.get("/status/list", response_model=APIResponse[list[dict[str, Any]]])
async def sync_status_list() -> APIResponse[list[dict[str, Any]]]:
    """Return latest sync status for each syncer. Empty list when sync_state is missing."""
    try:
        pool = pg.get_pool()
        data = await get_syncer_status_list(pool)
        return APIResponse(data=data)
    except Exception as e:
        logger.error("sync_status_list endpoint failed: %s", e, exc_info=True)
        return APIResponse(success=False, message=f"获取同步状态失败: {e}", data=[])
