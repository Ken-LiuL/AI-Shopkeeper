"""Async Redis connection powered by redis-py with hiredis."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from src.config import get_settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Create and ping the global Redis async connection."""
    global _redis
    if _redis is not None:
        return _redis

    cfg = get_settings().system.database["redis"]
    _redis = aioredis.from_url(
        cfg["url"],
        max_connections=cfg.get("max_connections", 10),
        decode_responses=True,
    )
    await _redis.ping()
    logger.info("Redis connected (%s)", cfg["url"])
    return _redis


def get_redis() -> aioredis.Redis:
    """Return the current Redis client or raise if not initialised."""
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _redis


async def close_redis() -> None:
    """Gracefully close the Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

async def get_json(key: str) -> Any | None:
    """Get a key and parse it as JSON."""
    r = get_redis()
    raw = await r.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    """Serialize value as JSON and set with optional TTL (seconds)."""
    r = get_redis()
    payload = json.dumps(value, ensure_ascii=False, default=str)
    if ttl:
        await r.setex(key, ttl, payload)
    else:
        await r.set(key, payload)


async def delete(key: str) -> None:
    """Delete a key."""
    r = get_redis()
    await r.delete(key)
