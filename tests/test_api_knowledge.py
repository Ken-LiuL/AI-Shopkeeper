"""Tests for src/api/knowledge.py — knowledge search API."""

from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure neo4j stub has needed attributes
_neo4j_stub = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo4j_stub.AsyncDriver = MagicMock
_neo4j_stub.AsyncGraphDatabase = MagicMock()
sys.modules["neo4j"] = _neo4j_stub

# Stub asyncpg if needed
if "asyncpg" not in sys.modules:
    _asyncpg = types.ModuleType("asyncpg")
    _asyncpg.Pool = MagicMock
    _asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _asyncpg

# Stub redis
if "redis" not in sys.modules:
    _redis = types.ModuleType("redis")
    _redis.asyncio = MagicMock()
    sys.modules["redis"] = _redis
    sys.modules["redis.asyncio"] = _redis.asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Now safe to import
import src.api.knowledge as knowledge_mod
from src.api.knowledge import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as tc:
        yield tc


class TestKnowledgeSearch:
    def test_empty_results(self, client):
        with patch.object(knowledge_mod.neo4j_db, "query", new_callable=AsyncMock, return_value=[]):
            resp = client.get("/api/knowledge/search?q=血压计")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_faq_results(self, client):
        faq = [{"question": "血压计怎么用", "answer": "按开关", "category": "FAQ", "source": "faq"}]
        with patch.object(knowledge_mod.neo4j_db, "query", new_callable=AsyncMock, side_effect=[faq, [], []]):
            resp = client.get("/api/knowledge/search?q=血压计")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["source"] == "faq"

    def test_product_results(self, client):
        products = [{"name": "鱼跃血压计", "description": "电子", "category": "医疗", "source": "product"}]
        with patch.object(knowledge_mod.neo4j_db, "query", new_callable=AsyncMock, side_effect=[[], products, []]):
            resp = client.get("/api/knowledge/search?q=鱼跃")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_fallback_search(self, client):
        fallback = [{"labels": ["FAQ"], "props": {"q": "test"}, "source": "graph"}]
        with patch.object(knowledge_mod.neo4j_db, "query", new_callable=AsyncMock, side_effect=[[], [], fallback]):
            resp = client.get("/api/knowledge/search?q=test")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_query_required(self, client):
        resp = client.get("/api/knowledge/search")
        assert resp.status_code == 422

    def test_neo4j_exception_graceful(self, client):
        with patch.object(knowledge_mod.neo4j_db, "query", new_callable=AsyncMock, side_effect=Exception("down")):
            resp = client.get("/api/knowledge/search?q=test")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
