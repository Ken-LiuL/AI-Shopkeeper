"""牵牛花原始数据读取工具 — 从 *_raw 表读取最新的 JSONB 数据。

所有 raw 表结构相同: id, source, raw_data (JSONB), synced_at, created_at
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

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
    params: tuple[Any, ...] = (source,) if source else ()
    where_clause = "WHERE source = $1" if source else ""
    order_columns = ("created_at", "synced_at", "id")
    for column in order_columns:
        try:
            row = await pool.fetchrow(
                f"SELECT raw_data FROM {table} {where_clause} ORDER BY {column} DESC LIMIT 1",
                *params,
            )
            if row and row["raw_data"]:
                data = row["raw_data"]
                if isinstance(data, str):
                    return json.loads(data)
                return data
        except asyncpg.UndefinedColumnError:
            logger.debug("%s 缺少列 %s，改用下一个排序列", table, column)
            continue
        except asyncpg.UndefinedTableError as e:
            logger.warning("表 %s 不存在: %s", table, e)
            return None
        except Exception as e:  # pragma: no cover - logging fallback
            logger.warning(f"读取 {table} 失败: {e}")
            return None
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
    params: tuple[Any, ...] = (source, limit) if source else (limit,)
    where_clause = "WHERE source = $1" if source else ""
    limit_placeholder = "$2" if source else "$1"
    default_query = (
        f"SELECT raw_data, synced_at, created_at FROM {table} "
        f"{where_clause} ORDER BY created_at DESC LIMIT {limit_placeholder}"
    )
    fallback_query = (
        f"SELECT raw_data, synced_at FROM {table} {where_clause} "
        f"ORDER BY synced_at DESC, id DESC LIMIT {limit_placeholder}"
    )

    for query in (default_query, fallback_query):
        try:
            rows = await pool.fetch(query, *params)
            results = []
            for row in rows:
                data = row["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                results.append(data)
            return results
        except asyncpg.UndefinedColumnError:
            logger.debug("%s 缺少 created_at 列，使用 synced_at/id 排序", table)
            continue
        except Exception as e:
            logger.warning(f"读取 {table} 多条数据失败: {e}")
            break
    return []
