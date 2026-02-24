"""Async PostgreSQL connection pool powered by asyncpg."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from src.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create and return the global asyncpg connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    import os

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        cfg = get_settings().system.database["postgres"]
        dsn = (
            f"postgresql://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
        )
    cfg = get_settings().system.database.get("postgres", {})
    # Use SSL for external Render PG URLs, skip for internal
    ssl_param = None
    if dsn and ".render.com" in dsn:
        import ssl as _ssl

        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
        ssl_param = ssl_ctx
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=cfg.get("min_connections", 2),
        max_size=cfg.get("max_connections", 5),
        timeout=10,
        **({"ssl": ssl_param} if ssl_param else {}),
    )
    logger.info(
        "PostgreSQL pool initialised (min=%s, max=%s)",
        cfg.get("min_connections", 5),
        cfg.get("max_connections", 20),
    )
    return _pool


def get_pool() -> asyncpg.Pool:
    """Return the current pool or raise if not initialised."""
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialised. Call init_pool() first.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    """Execute a query and return all rows."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    """Execute a query and return a single row."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    """Execute a query and return a single value."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    """Execute a statement (INSERT / UPDATE / DELETE)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
