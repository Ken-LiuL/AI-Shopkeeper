"""牵牛花原始数据读取工具 — 从 *_raw 表读取最新的 JSONB 数据。

所有 raw 表结构相同: id, source, raw_data (JSONB), synced_at, created_at
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def fetch_latest_raw(pool, table: str, source: str | None = None) -> dict | list | None:
    """从指定 raw 表读取最新一条数据并解析 JSONB。

    Args:
        pool: asyncpg 连接池
        table: 表名，如 'qnh_store_metrics_raw'
        source: 可选的 source 过滤条件

    Returns:
        解析后的 Python 对象（dict 或 list），失败返回 None
    """
    if not pool:
        return None
    try:
        if source:
            row = await pool.fetchrow(
                f"SELECT raw_data FROM {table} WHERE source = $1 ORDER BY created_at DESC LIMIT 1",
                source,
            )
        else:
            row = await pool.fetchrow(
                f"SELECT raw_data FROM {table} ORDER BY created_at DESC LIMIT 1"
            )
        if row and row["raw_data"]:
            data = row["raw_data"]
            # asyncpg 自动解析 JSONB 为 Python 对象
            if isinstance(data, str):
                return json.loads(data)
            return data
    except Exception as e:
        logger.warning(f"读取 {table} 失败: {e}")
    return None


async def fetch_all_raw(
    pool, table: str, source: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """从指定 raw 表读取多条数据。

    Args:
        pool: asyncpg 连接池
        table: 表名
        source: 可选 source 过滤
        limit: 最大返回条数

    Returns:
        解析后的数据列表
    """
    if not pool:
        return []
    try:
        if source:
            rows = await pool.fetch(
                f"SELECT raw_data, synced_at, created_at FROM {table} "
                f"WHERE source = $1 ORDER BY created_at DESC LIMIT $2",
                source,
                limit,
            )
        else:
            rows = await pool.fetch(
                f"SELECT raw_data, synced_at, created_at FROM {table} "
                f"ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        results = []
        for row in rows:
            data = row["raw_data"]
            if isinstance(data, str):
                data = json.loads(data)
            results.append(data)
        return results
    except Exception as e:
        logger.warning(f"读取 {table} 多条数据失败: {e}")
    return []
