"""Tests for src/api/metrics_api.py — LLM metrics API."""

from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure stubs for db imports
_neo4j_stub = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo4j_stub.AsyncDriver = MagicMock
_neo4j_stub.AsyncGraphDatabase = MagicMock()
sys.modules["neo4j"] = _neo4j_stub

if "asyncpg" not in sys.modules:
    _asyncpg = types.ModuleType("asyncpg")
    _asyncpg.Pool = MagicMock
    _asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _asyncpg

if "redis" not in sys.modules:
    _redis = types.ModuleType("redis")
    _redis.asyncio = MagicMock()
    sys.modules["redis"] = _redis
    sys.modules["redis.asyncio"] = _redis.asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.metrics_api as metrics_mod
from src.api.metrics_api import router


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value={
        "total_input_tokens": 10000,
        "total_output_tokens": 5000,
        "total_cost_usd": 1.23,
        "total_requests": 42,
    })
    pool.fetch = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def client(mock_pool):
    app = FastAPI()
    app.include_router(router)
    with patch.object(metrics_mod.pg, "get_pool", return_value=mock_pool):
        with TestClient(app) as tc:
            yield tc, mock_pool


class TestLLMMetrics:
    def test_default_7_days(self, client):
        tc, _ = client
        resp = tc.get("/api/metrics/llm")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["period_days"] == 7
        assert data["total_input_tokens"] == 10000
        assert data["total_cost_usd"] == 1.23

    def test_custom_days(self, client):
        tc, mock_pool = client
        resp = tc.get("/api/metrics/llm?days=30")
        assert resp.status_code == 200
        assert resp.json()["data"]["period_days"] == 30
        args = mock_pool.fetchrow.call_args[0]
        assert args[1] == 30

    def test_with_model_breakdown(self, client):
        tc, mock_pool = client
        model_rows = [
            {"model": "gpt-4", "input_tokens": 8000, "output_tokens": 4000, "cost_usd": 1.0, "requests": 30},
        ]
        mock_pool.fetch = AsyncMock(side_effect=[model_rows, [], []])
        resp = tc.get("/api/metrics/llm")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["by_model"]) == 1

    def test_days_validation(self, client):
        tc, _ = client
        assert tc.get("/api/metrics/llm?days=0").status_code == 422
        assert tc.get("/api/metrics/llm?days=100").status_code == 422
