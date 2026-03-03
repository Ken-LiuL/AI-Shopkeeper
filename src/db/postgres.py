"""Async PostgreSQL connection pool powered by asyncpg."""

from __future__ import annotations

import contextlib
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
    # Retry pool creation — Fly PG can be slow on cold start
    import asyncio

    for attempt in range(5):
        try:
            _pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=3,
                timeout=30,
                command_timeout=30,
                max_inactive_connection_lifetime=300,
                **({"ssl": ssl_param} if ssl_param else {}),
            )
            logger.info("PostgreSQL pool initialised (min=1, max=10)")
            return _pool
        except Exception as e:
            logger.warning("PG pool init attempt %d/5 failed: %s", attempt + 1, e)
            if attempt < 4:
                await asyncio.sleep(2**attempt)
            else:
                raise


def get_pool() -> asyncpg.Pool:
    """Return the current pool or raise if not initialised.

    NOTE: If pool is None and we're in an async context, callers should
    use ``await get_pool_safe()`` instead, which will attempt init.
    """
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialised. Call init_pool() first.")
    return _pool


async def get_pool_safe() -> asyncpg.Pool | None:
    """Return pool, attempting init if needed. Returns None if PG unavailable."""
    global _pool
    if _pool is not None:
        return _pool
    try:
        return await init_pool()
    except Exception:
        return None


async def ensure_pool() -> asyncpg.Pool:
    """Get pool, re-initialising if needed (e.g. after PG restart)."""
    global _pool
    if _pool is None:
        return await init_pool()
    # Quick health check
    try:
        async with _pool.acquire(timeout=5) as conn:
            await conn.fetchval("SELECT 1")
        return _pool
    except Exception:
        logger.warning("PG pool unhealthy, re-initialising...")
        with contextlib.suppress(Exception):
            await _pool.close()
        _pool = None
        return await init_pool()


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
