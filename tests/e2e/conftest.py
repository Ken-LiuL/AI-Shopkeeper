"""E2E test shared fixtures — mock Redis, LLM, DB."""

from __future__ import annotations

import sys
import types as _types

# Stub heavy deps not installed in test env
from unittest.mock import MagicMock as _MK

# Stub redis package before anything imports it
if "redis" not in sys.modules:
    _redis_pkg = _types.ModuleType("redis")
    _redis_asyncio = _types.ModuleType("redis.asyncio")
    _redis_asyncio.Redis = _MK
    _redis_asyncio.from_url = _MK(return_value=_MK())
    _redis_pkg.asyncio = _redis_asyncio
    sys.modules["redis"] = _redis_pkg
    sys.modules["redis.asyncio"] = _redis_asyncio

for _mod in ("neo4j", "sentence_transformers", "asyncpg", "langfuse", "langfuse.decorators",
             "prometheus_client", "apscheduler", "apscheduler.schedulers",
             "apscheduler.schedulers.asyncio", "apscheduler.triggers", "apscheduler.triggers.cron",
             "hiredis"):
    if _mod not in sys.modules:
        sys.modules[_mod] = _types.ModuleType(_mod)

# Ensure neo4j stub has required attrs
_neo4j = sys.modules["neo4j"]
if not hasattr(_neo4j, "AsyncDriver") or isinstance(_neo4j.AsyncDriver, _types.ModuleType):
    _neo4j.AsyncDriver = _MK
    _neo4j.AsyncGraphDatabase = _MK

if "aiohttp" not in sys.modules:
    from unittest.mock import MagicMock as _MagicMock
    _aiohttp = _types.ModuleType("aiohttp")
    _aiohttp.ClientSession = _MagicMock
    _aiohttp.ClientTimeout = _MagicMock
    _aiohttp.ClientError = Exception
    sys.modules["aiohttp"] = _aiohttp

import asyncio
import json
from collections import defaultdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── FakeRedis (dict-backed) ──────────────────────────────────

class FakeRedis:
    """Minimal async Redis mock backed by dicts for E2E testing."""

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._lists: dict[str, list[str]] = defaultdict(list)
        self._hashes: dict[str, dict[str, str]] = defaultdict(dict)
        self._zsets: dict[str, dict[str, float]] = defaultdict(dict)
        self._ttls: dict[str, int] = {}
        self._locks: dict[str, bool] = {}

    async def ping(self) -> bool:
        return True

    # String ops
    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self._data:
            return None
        self._data[key] = value
        if ex:
            self._ttls[key] = ex
        return True

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self._data[key] = value
        self._ttls[key] = ttl
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            for store in (self._data, self._lists, self._hashes, self._zsets, self._ttls):
                if key in store:
                    del store[key]
                    count += 1
        return count

    async def exists(self, key: str) -> int:
        return 1 if key in self._data or key in self._hashes or key in self._lists else 0

    async def expire(self, key: str, ttl: int) -> bool:
        self._ttls[key] = ttl
        return True

    # List ops
    async def rpush(self, key: str, *values: str) -> int:
        for v in values:
            self._lists[key].append(v)
        return len(self._lists[key])

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        if end == -1:
            end = len(lst)
        else:
            end = end + 1
        return lst[start:end]

    async def lindex(self, key: str, idx: int) -> str | None:
        lst = self._lists.get(key, [])
        try:
            return lst[idx]
        except IndexError:
            return None

    # Hash ops
    async def hset(self, key: str, mapping: dict[str, str] | None = None, **kwargs: str) -> int:
        m = mapping or {}
        m.update(kwargs)
        self._hashes[key].update(m)
        return len(m)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        cur = int(self._hashes.get(key, {}).get(field, "0"))
        cur += amount
        self._hashes.setdefault(key, {})[field] = str(cur)
        return cur

    # Sorted set ops
    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self._zsets[key].update(mapping)
        return len(mapping)

    async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        items = sorted(self._zsets.get(key, {}).items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in items[start:end + 1]]

    async def zrem(self, key: str, *members: str) -> int:
        zs = self._zsets.get(key, {})
        count = 0
        for m in members:
            if m in zs:
                del zs[m]
                count += 1
        return count

    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list[Any] = []

    def delete(self, key: str):
        self._ops.append(("delete", key))
        return self

    def zrem(self, key: str, *members: str):
        self._ops.append(("zrem", key, members))
        return self

    async def execute(self) -> list[Any]:
        results = []
        for op in self._ops:
            if op[0] == "delete":
                r = await self._redis.delete(op[1])
                results.append(r)
            elif op[0] == "zrem":
                r = await self._redis.zrem(op[1], *op[2])
                results.append(r)
        return results


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator that returns canned LLM responses."""
    orch = AsyncMock()
    orch.run_customer_service = AsyncMock(return_value={
        "reply": {"reply_text": "亲，在的呢~请问有什么可以帮您？😊", "confidence": 1.0},
        "intent": {"intent": "greeting", "confidence": 0.98},
    })
    orch.run_selection = AsyncMock(return_value={
        "recommendations": [{"rank": 1, "keyword": "血压计", "final_score": 85}],
        "scoring_summary": {"total_evaluated": 1, "recommended_count": 1},
    })
    orch.run_alert = AsyncMock(return_value={
        "anomalies": {"detection_summary": {"anomalies_found": 1, "critical_count": 1}},
        "actions": {"recommended_actions": [{"action_type": "price_adjust"}]},
    })
    orch.run_listing = AsyncMock(return_value={
        "meituan_listing": {"title": "测试商品", "description": "描述"},
        "quality_report": {"overall_score": 90},
    })
    orch.run_bundle = AsyncMock(return_value={
        "bundles": [{"name": "健康套餐", "products": [], "bundle_price": 99.9}],
    })
    return orch


@pytest.fixture
def app_client(fake_redis, mock_orchestrator):
    """Create a FastAPI TestClient with mocked dependencies."""
    # Pre-import modules so patch targets exist
    import src.db.redis
    import src.api.deps
    import src.api.customer_service

    with patch.object(src.db.redis, "get_redis", return_value=fake_redis), \
         patch.object(src.db.redis, "_redis", fake_redis), \
         patch.object(src.api.deps, "get_orchestrator", return_value=mock_orchestrator):
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(src.api.customer_service.router)

        from src.api.errors import register_error_handlers
        register_error_handlers(app)

        client = TestClient(app)
        yield client
