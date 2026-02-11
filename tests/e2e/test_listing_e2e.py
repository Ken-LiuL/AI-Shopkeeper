"""E2E tests for Listing Agent flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    orch.run_listing = AsyncMock(return_value={
        "meituan_listing": {
            "title": "鱼跃电子血压计 YE680A",
            "description": "全自动上臂式血压测量仪",
            "seo_keywords": ["血压计", "电子血压计"],
        },
        "quality_report": {"overall_score": 92},
    })
    return orch


@pytest.fixture
def listing_client(mock_pool, mock_orch):
    import src.db.postgres
    import src.api.deps
    import src.api.listing

    with patch.object(src.db.postgres, "get_pool", return_value=mock_pool), \
         patch.object(src.api.deps, "get_orchestrator", return_value=mock_orch):
        from src.api.errors import register_error_handlers
        app = FastAPI()
        app.include_router(src.api.listing.router)
        register_error_handlers(app)
        yield TestClient(app)


class TestListingE2E:

    def test_create_listing(self, listing_client, mock_pool):
        """Submit 1688 URL and start listing generation."""
        res = listing_client.post("/api/listing/create", json={
            "source_url": "https://detail.1688.com/offer/123456.html",
            "platform": "alibaba",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"].startswith("lst_")

    def test_create_listing_pdd(self, listing_client):
        """Submit PDD URL."""
        res = listing_client.post("/api/listing/create", json={
            "source_url": "https://mobile.yangkeduo.com/goods.html?id=123",
            "platform": "pdd",
        })
        assert res.status_code == 200

    def test_get_listing_not_found(self, listing_client):
        """Get non-existent listing returns 404."""
        res = listing_client.get("/api/listing/nonexistent")
        assert res.status_code == 404

    def test_get_listing_detail(self, listing_client, mock_pool):
        """Get a completed listing."""
        mock_pool.fetchrow = AsyncMock(return_value={
            "listing_id": "lst_001", "status": "completed",
            "product_data": json.dumps({"title": "测试商品"}),
            "created_at": "2026-01-01T00:00:00",
        })
        res = listing_client.get("/api/listing/lst_001")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["listing_id"] == "lst_001"
        assert data["status"] == "completed"

    def test_create_listing_with_overrides(self, listing_client):
        """Submit with raw_product_data override."""
        res = listing_client.post("/api/listing/create", json={
            "source_url": "https://detail.1688.com/offer/789.html",
            "platform": "alibaba",
            "raw_product_data": "手动输入的商品数据",
            "overrides": {"price": 199},
        })
        assert res.status_code == 200

    def test_parse_url_alibaba(self, listing_client):
        """Parse an alibaba URL (mock skill)."""
        import sys, types as _t
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(return_value={"title": "test", "price": 100})
        mock_skill_instance = MagicMock()
        mock_skill_instance.alibaba_detail = AsyncMock(return_value=mock_result)
        mock_skill_cls = MagicMock(return_value=mock_skill_instance)

        # Stub the skills module
        mod = _t.ModuleType("src.skills.actionbook")
        mod.ActionBookSkill = mock_skill_cls
        sys.modules["src.skills.actionbook"] = mod

        try:
            res = listing_client.post("/api/listing/parse", json={
                "url": "https://detail.1688.com/offer/123.html",
                "platform": "alibaba",
            })
            assert res.status_code == 200
            assert res.json()["data"]["title"] == "test"
        finally:
            sys.modules.pop("src.skills.actionbook", None)
