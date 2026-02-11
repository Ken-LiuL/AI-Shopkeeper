"""Tests for src/sync/competitors.py — CompetitorSyncer."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from src.sync.competitors import (
    CompetitorSyncer,
    COMPETITOR_KEYWORDS,
    DEFAULT_LOCATION,
)
from src.sync.base import SyncMode


# ── Helpers ──────────────────────────────────────────────────────────────────

@dataclass
class FakeProduct:
    product_id: str = "P1"
    name: str = "血压计A"
    price: float = 199.0
    monthly_sales: int = 100
    store_name: str = "药店A"


@pytest.fixture
def db_pool():
    pool = AsyncMock()
    pool.execute = AsyncMock()
    return pool


@pytest.fixture
def syncer(db_pool):
    with patch.object(CompetitorSyncer.__bases__[0], '__init__', lambda self, *a, **kw: None):
        return CompetitorSyncer(db_pool=db_pool)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestCompetitorSyncerInit:
    def test_default_keywords(self, syncer):
        assert syncer._keywords == COMPETITOR_KEYWORDS
        assert len(syncer._keywords) == 15

    def test_custom_keywords(self, db_pool):
        with patch.object(CompetitorSyncer.__bases__[0], '__init__', lambda self, *a, **kw: None):
            s = CompetitorSyncer(db_pool=db_pool, keywords=["test"])
        assert s._keywords == ["test"]

    def test_default_location(self, syncer):
        assert syncer._location == DEFAULT_LOCATION

    def test_name(self, syncer):
        assert syncer.name == "competitors"


class TestFullSync:
    @pytest.mark.asyncio
    async def test_full_sync_success(self, syncer):
        products = [FakeProduct(), FakeProduct(product_id="P2", store_name="药店B")]
        mock_scraper = AsyncMock()
        mock_scraper.search_products = AsyncMock(return_value=products)
        mock_scraper.search_hot_keywords = AsyncMock(return_value=["血压计", "体温计"])
        mock_scraper.cleanup = AsyncMock()

        with patch("src.skills.meituan_h5.MeituanH5Scraper", return_value=mock_scraper):
            result = await syncer.full_sync()

        assert result.success
        assert result.mode == SyncMode.FULL
        assert result.details["products"] > 0
        assert result.details["keywords"] == 2

    @pytest.mark.asyncio
    async def test_full_sync_empty_results(self, syncer):
        mock_scraper = AsyncMock()
        mock_scraper.search_products = AsyncMock(return_value=[])
        mock_scraper.search_hot_keywords = AsyncMock(return_value=[])
        mock_scraper.cleanup = AsyncMock()

        with patch("src.skills.meituan_h5.MeituanH5Scraper", return_value=mock_scraper):
            result = await syncer.full_sync()

        # No products but also no errors → success
        assert result.success
        assert result.details["products"] == 0

    @pytest.mark.asyncio
    async def test_full_sync_scraper_error(self, syncer):
        mock_scraper = AsyncMock()
        mock_scraper.search_products = AsyncMock(side_effect=Exception("timeout"))
        mock_scraper.search_hot_keywords = AsyncMock(return_value=[])
        mock_scraper.cleanup = AsyncMock()

        with patch("src.skills.meituan_h5.MeituanH5Scraper", return_value=mock_scraper):
            result = await syncer.full_sync()

        assert result.records_failed > 0
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_full_sync_import_error(self, syncer):
        with patch("src.skills.meituan_h5.MeituanH5Scraper", side_effect=ImportError("no module")):
            # ImportError is caught inside full_sync via the try/except ImportError block
            # But we're patching at module level; let's patch the import inside
            pass

        # Simulate by patching at the point of import
        with patch.dict("sys.modules", {"src.skills.meituan_h5": None}):
            result = await syncer.full_sync()
        assert not result.success or "not available" in (result.error or "")


class TestIncrementalSync:
    @pytest.mark.asyncio
    async def test_incremental_delegates_to_full(self, syncer):
        mock_scraper = AsyncMock()
        mock_scraper.search_products = AsyncMock(return_value=[FakeProduct()])
        mock_scraper.search_hot_keywords = AsyncMock(return_value=[])
        mock_scraper.cleanup = AsyncMock()

        with patch("src.skills.meituan_h5.MeituanH5Scraper", return_value=mock_scraper):
            result = await syncer.incremental_sync()

        assert result.mode == SyncMode.FULL  # incremental = full for this syncer


class TestAggregateStores:
    def test_basic_aggregation(self):
        products = [
            FakeProduct(store_name="店A", monthly_sales=300),
            FakeProduct(product_id="P2", store_name="店A", monthly_sales=300),
            FakeProduct(product_id="P3", store_name="店B", monthly_sales=50),
        ]
        stores = CompetitorSyncer._aggregate_stores(products)
        assert len(stores) == 2

        store_a = next(s for s in stores if s["name"] == "店A")
        assert store_a["monthly_sales"] == 600
        assert store_a["product_count"] == 2
        assert store_a["threat_level"] == "high"

        store_b = next(s for s in stores if s["name"] == "店B")
        assert store_b["threat_level"] == "low"

    def test_empty_products(self):
        assert CompetitorSyncer._aggregate_stores([]) == []


class TestSaveProducts:
    @pytest.mark.asyncio
    async def test_save_calls_db(self, syncer, db_pool):
        products = [FakeProduct(), FakeProduct(product_id="P2")]
        await syncer._save_products(products, "血压计")
        assert db_pool.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_save_no_pool(self):
        with patch.object(CompetitorSyncer.__bases__[0], '__init__', lambda self, *a, **kw: None):
            s = CompetitorSyncer(db_pool=None)
        await s._save_products([FakeProduct()], "test")  # should not raise
