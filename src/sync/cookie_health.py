"""Cookie健康检查模块。

美团数据同步依赖浏览器 Cookie，Cookie 过期后全系统数据断流。
此模块提供以下功能：
- check_cookie_health: 检查最后一次成功同步时间，超过 2 小时标记为 STALE
- get_sync_status: 返回各数据源的同步状态和最后更新时间
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Cookie 过期判定阈值（小时）
STALE_THRESHOLD_HOURS = 2

# 各数据源对应的 sync_type 枚举值
SYNC_SOURCES = [
    "meituan_orders",
    "meituan_products",
    "qnh_products",
    "qnh_orders",
    "store_stock",
]


async def check_cookie_health(pool: Any) -> dict:
    """检查 Cookie 健康状态。

    查询 sync_logs 中最近一次成功同步的时间；
    若距现在超过 STALE_THRESHOLD_HOURS 小时，则标记为 STALE。

    Returns:
        {
            "status": "OK" | "STALE" | "UNKNOWN",
            "last_success_at": ISO 时间字符串 | None,
            "hours_since_last_sync": float | None,
            "stale_threshold_hours": int,
            "message": str,
        }
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT finished_at
                FROM sync_logs
                WHERE status = 'success'
                  AND sync_type LIKE 'meituan%'
                ORDER BY finished_at DESC NULLS LAST
                LIMIT 1
                """
            )
    except Exception as e:
        logger.warning("Failed to query sync_logs for cookie health: %s", e)
        return {
            "status": "UNKNOWN",
            "last_success_at": None,
            "hours_since_last_sync": None,
            "stale_threshold_hours": STALE_THRESHOLD_HOURS,
            "message": f"无法查询同步日志: {e}",
        }

    now = datetime.now(UTC)

    if row is None or row["finished_at"] is None:
        return {
            "status": "UNKNOWN",
            "last_success_at": None,
            "hours_since_last_sync": None,
            "stale_threshold_hours": STALE_THRESHOLD_HOURS,
            "message": "未找到任何美团同步成功记录，Cookie 状态未知",
        }

    last_success: datetime = row["finished_at"]
    # 确保时区一致
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=UTC)

    hours_elapsed = (now - last_success).total_seconds() / 3600

    if hours_elapsed > STALE_THRESHOLD_HOURS:
        status = "STALE"
        message = (
            f"距最后一次成功同步已过去 {hours_elapsed:.1f} 小时（阈值 {STALE_THRESHOLD_HOURS}h），"
            "Cookie 可能已过期，数据同步中断"
        )
    else:
        status = "OK"
        message = f"同步正常，距最后一次成功同步 {hours_elapsed:.1f} 小时"

    return {
        "status": status,
        "last_success_at": last_success.isoformat(),
        "hours_since_last_sync": round(hours_elapsed, 2),
        "stale_threshold_hours": STALE_THRESHOLD_HOURS,
        "message": message,
    }


async def get_sync_status(pool: Any) -> dict:
    """返回各数据源的同步状态和最后更新时间。

    Returns:
        {
            "sources": {
                "<sync_type>": {
                    "last_success_at": ISO 时间字符串 | None,
                    "last_status": str | None,
                    "last_error": str | None,
                    "records_count": int | None,
                    "hours_since_last_sync": float | None,
                    "is_stale": bool,
                },
                ...
            },
            "overall_status": "OK" | "STALE" | "UNKNOWN",
            "checked_at": ISO 时间字符串,
        }
    """
    now = datetime.now(UTC)
    sources: dict[str, dict] = {}

    try:
        async with pool.acquire() as conn:
            # 每种 sync_type 取最近一条记录（不限 status）
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (sync_type)
                    sync_type,
                    status,
                    finished_at,
                    records_count,
                    error_msg
                FROM sync_logs
                ORDER BY sync_type, finished_at DESC NULLS LAST
                """
            )
    except Exception as e:
        logger.warning("Failed to query sync_logs for sync status: %s", e)
        return {
            "sources": {},
            "overall_status": "UNKNOWN",
            "checked_at": now.isoformat(),
            "error": str(e),
        }

    # 把查询结果整理成字典
    row_map: dict[str, Any] = {r["sync_type"]: r for r in rows}

    # 补全预定义数据源（即使从未同步过也出现在结果中）
    all_types = set(SYNC_SOURCES) | {r["sync_type"] for r in rows}

    any_stale = False
    any_ok = False

    for sync_type in sorted(all_types):
        row = row_map.get(sync_type)
        if row is None:
            sources[sync_type] = {
                "last_success_at": None,
                "last_status": None,
                "last_error": None,
                "records_count": None,
                "hours_since_last_sync": None,
                "is_stale": True,
            }
            any_stale = True
            continue

        finished_at = row["finished_at"]
        if finished_at is not None:
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=UTC)
            hours_elapsed = (now - finished_at).total_seconds() / 3600
            is_stale = row["status"] != "success" or hours_elapsed > STALE_THRESHOLD_HOURS
        else:
            hours_elapsed = None
            is_stale = True

        if is_stale:
            any_stale = True
        else:
            any_ok = True

        # 只在成功同步时记录 last_success_at
        last_success_at = (
            finished_at.isoformat()
            if (finished_at is not None and row["status"] == "success")
            else None
        )

        sources[sync_type] = {
            "last_success_at": last_success_at,
            "last_status": row["status"],
            "last_error": row["error_msg"],
            "records_count": row["records_count"],
            "hours_since_last_sync": round(hours_elapsed, 2) if hours_elapsed is not None else None,
            "is_stale": is_stale,
        }

    if any_stale:
        overall_status = "STALE"
    elif any_ok:
        overall_status = "OK"
    else:
        overall_status = "UNKNOWN"

    return {
        "sources": sources,
        "overall_status": overall_status,
        "checked_at": now.isoformat(),
    }
