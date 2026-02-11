"""E2E tests for Bundle Agent flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def mock_orch():
    orch = AsyncMock()
    orch.run_bundle = AsyncMock(return_value={
        "bundles": [
            {"name": "健康监测套餐", "products": [
                {"product_id": "P1", "name": "血压计"},
                {"product_id": "P2", "name": "血糖仪"},
            ], "bundle_price": 399.0, "original_price": 499.0},
        ],
    })
    return orch


@pytest.fixture
def bundle_client(mock_pool, mock_orch):
    import src.db.postgres
    import src.api.deps
    import src.api.bundles

    with patch.object(src.db.postgres, "get_pool", return_value=mock_pool), \
         patch.object(src.api.deps, "get_orchestrator", return_value=mock_orch):
        from src.api.errors import register_error_handlers
        app = FastAPI()
        app.include_router(src.api.bundles.router)
        register_error_handlers(app)
        yield TestClient(app)


class TestBundleE2E:

    def test_generate_bundles(self, bundle_client, mock_pool):
        """Trigger bundle generation."""
        res = bundle_client.post("/api/bundles/generate", json={
            "min_support": 0.05,
            "min_confidence": 0.3,
            "max_bundles": 5,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"].startswith("bnd_")

    def test_generate_bundles_default_params(self, bundle_client):
        """Generate with default parameters."""
        res = bundle_client.post("/api/bundles/generate", json={})
        assert res.status_code == 200

    def test_list_bundles_empty(self, bundle_client):
        """List bundles when none exist."""
        res = bundle_client.get("/api/bundles")
        assert res.status_code == 200
        assert res.json()["data"] == []

    def test_list_bundles_with_data(self, bundle_client, mock_pool):
        """List bundles returns stored bundles."""
        mock_pool.fetch = AsyncMock(return_value=[
            {"bundle_id": "B001", "name": "健康套餐", "status": "active",
             "bundle_price": 399, "created_at": "2026-01-01"},
        ])
        res = bundle_client.get("/api/bundles")
        assert res.status_code == 200
        assert len(res.json()["data"]) == 1

    def test_update_bundle(self, bundle_client, mock_pool):
        """Update bundle name and price."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "bundle_id": "B001", "name": "超值健康套餐",
            "bundle_price": 359, "status": "active",
        })
        res = bundle_client.patch("/api/bundles/B001", json={
            "name": "超值健康套餐",
            "bundle_price": 359,
        })
        assert res.status_code == 200
        assert res.json()["data"]["name"] == "超值健康套餐"

    def test_update_bundle_not_found(self, bundle_client, mock_pool):
        """Update non-existent bundle returns 404."""
        mock_pool.fetchrow = AsyncMock(return_value=None)
        res = bundle_client.patch("/api/bundles/nonexist", json={"status": "active"})
        assert res.status_code == 404

    def test_delete_bundle(self, bundle_client, mock_pool):
        """Delete (soft) a bundle."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "bundle_id": "B001", "status": "deleted",
        })
        res = bundle_client.delete("/api/bundles/B001")
        assert res.status_code == 200

    def test_delete_bundle_not_found(self, bundle_client, mock_pool):
        """Delete non-existent bundle returns 404."""
        mock_pool.fetchrow = AsyncMock(return_value=None)
        res = bundle_client.delete("/api/bundles/nonexist")
        assert res.status_code == 404
