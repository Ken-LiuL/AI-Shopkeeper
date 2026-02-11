"""Tests for src/skills/meituan_h5.py — MeituanH5Scraper."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.skills.meituan_h5 import MeituanH5Scraper, DEFAULT_LOCATION


@pytest.fixture
def mock_cli():
    cli = AsyncMock()
    cli.browser_open = AsyncMock()
    cli.browser_close = AsyncMock()
    cli.browser_eval = AsyncMock(return_value=None)
    cli.browser_text = AsyncMock(return_value="")
    cli.cleanup = AsyncMock()
    return cli


@pytest.fixture
def scraper(mock_cli):
    return MeituanH5Scraper(cli=mock_cli)


# Disable all delays in tests
@pytest.fixture(autouse=True)
def no_delay():
    with patch("src.skills.meituan_h5._random_delay", new_callable=AsyncMock), \
         patch("src.skills.meituan_h5.asyncio.sleep", new_callable=AsyncMock):
        yield


# ── search_products ──────────────────────────────────────────────────────────

class TestSearchProducts:
    @pytest.mark.asyncio
    async def test_xhr_extraction(self, scraper, mock_cli):
        """XHR interception returns data → products extracted."""
        xhr_data = [
            {
                "url": "/api/search",
                "data": {
                    "data": {
                        "poiList": [
                            {
                                "name": "健康大药房",
                                "poiId": 12345,
                                "wmPoiScore": "4.8",
                                "monthSaleTip": "月售320",
                                "distance": "1.2km",
                                "foodSpuTags": [],
                            }
                        ]
                    }
                },
            }
        ]
        # First call: inject interceptor returns 'injected'
        # Second call: get captured returns xhr data
        mock_cli.browser_eval = AsyncMock(
            side_effect=["injected", json.dumps(xhr_data)]
        )

        products = await scraper.search_products("血压计")
        assert len(products) == 1
        assert products[0].store_name == "健康大药房"
        assert products[0].monthly_sales == 320

    @pytest.mark.asyncio
    async def test_dom_fallback(self, scraper, mock_cli):
        """XHR empty → falls back to DOM extraction."""
        dom_data = [
            {"name": "血压计A", "price": 199, "sales": 50, "storeName": "药店", "storeId": "1"}
        ]
        mock_cli.browser_eval = AsyncMock(
            side_effect=["injected", "[]", json.dumps(dom_data)]
        )

        products = await scraper.search_products("血压计")
        assert len(products) == 1
        assert products[0].name == "血压计A"
        assert products[0].price == 199.0

    @pytest.mark.asyncio
    async def test_text_fallback(self, scraper, mock_cli):
        """XHR + DOM empty → text fallback."""
        # Text must be > 50 chars for text parser to engage
        text = (
            "健康大药房 光谷店 距离1.2km\n月售120 ¥199\n"
            "另一家药店 关山大道店\n月售50 ¥89\n"
            "填充文本确保长度足够 padding text to exceed fifty characters\n"
        )
        mock_cli.browser_eval = AsyncMock(
            side_effect=["injected", "[]", "[]"]
        )
        mock_cli.browser_text = AsyncMock(return_value=text)

        products = await scraper.search_products("健康")
        # The text parser sets current_store on non-matching lines,
        # then creates product when it sees 月售. "健康大药房" matches keyword "健康"
        assert len(products) >= 1
        assert products[0].monthly_sales == 120

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self, scraper, mock_cli):
        """All strategies fail → empty list, no exception."""
        mock_cli.browser_eval = AsyncMock(return_value=None)
        mock_cli.browser_text = AsyncMock(return_value="")

        products = await scraper.search_products("血压计")
        assert products == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self, scraper, mock_cli):
        """Exception → empty list."""
        mock_cli.browser_open = AsyncMock(side_effect=Exception("timeout"))

        products = await scraper.search_products("血压计")
        assert products == []

    @pytest.mark.asyncio
    async def test_custom_location(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(return_value=None)
        mock_cli.browser_text = AsyncMock(return_value="")
        await scraper.search_products("test", location=(116.0, 39.0))
        url = mock_cli.browser_open.call_args[0][0]
        assert "lat=39.0" in url
        assert "lng=116.0" in url


# ── get_store_products ───────────────────────────────────────────────────────

class TestGetStoreProducts:
    @pytest.mark.asyncio
    async def test_success(self, scraper, mock_cli):
        items = [{"name": "产品A", "price": 99, "sales": 30}]
        mock_cli.browser_eval = AsyncMock(return_value=json.dumps(items))

        products = await scraper.get_store_products("12345")
        assert len(products) == 1
        assert products[0].name == "产品A"

    @pytest.mark.asyncio
    async def test_empty(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(return_value="[]")
        products = await scraper.get_store_products("12345")
        assert products == []

    @pytest.mark.asyncio
    async def test_error(self, scraper, mock_cli):
        mock_cli.browser_open = AsyncMock(side_effect=Exception("fail"))
        products = await scraper.get_store_products("12345")
        assert products == []


# ── get_category_ranking ─────────────────────────────────────────────────────

class TestGetCategoryRanking:
    @pytest.mark.asyncio
    async def test_delegates_to_search(self, scraper):
        with patch.object(scraper, "search_products", new_callable=AsyncMock) as mock_search:
            from src.skills.actionbook import CompetitorProduct
            mock_search.return_value = [
                CompetitorProduct(product_id="1", name="A", price=10, monthly_sales=100, store_name="S"),
            ]
            ranking = await scraper.get_category_ranking("医疗器械")
            assert len(ranking) == 1
            assert ranking[0]["rank"] == 1
            assert ranking[0]["name"] == "A"

    @pytest.mark.asyncio
    async def test_empty(self, scraper):
        with patch.object(scraper, "search_products", new_callable=AsyncMock, return_value=[]):
            ranking = await scraper.get_category_ranking("test")
            assert ranking == []


# ── search_hot_keywords ──────────────────────────────────────────────────────

class TestSearchHotKeywords:
    @pytest.mark.asyncio
    async def test_success(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(
            return_value=json.dumps(["血压计", "口罩", "体温计"])
        )
        keywords = await scraper.search_hot_keywords()
        assert keywords == ["血压计", "口罩", "体温计"]

    @pytest.mark.asyncio
    async def test_empty(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(return_value="[]")
        keywords = await scraper.search_hot_keywords()
        assert keywords == []

    @pytest.mark.asyncio
    async def test_error(self, scraper, mock_cli):
        mock_cli.browser_open = AsyncMock(side_effect=Exception("fail"))
        keywords = await scraper.search_hot_keywords()
        assert keywords == []


# ── Static helpers ───────────────────────────────────────────────────────────

class TestParseDistance:
    def test_km(self):
        assert MeituanH5Scraper._parse_distance("1.2km") == 1.2

    def test_meters(self):
        assert MeituanH5Scraper._parse_distance("500m") == 0.5

    def test_chinese(self):
        assert MeituanH5Scraper._parse_distance("800米") == 0.8

    def test_numeric(self):
        assert MeituanH5Scraper._parse_distance(2.5) == 2.5

    def test_empty(self):
        assert MeituanH5Scraper._parse_distance("") == 0.0


class TestParseMonthSales:
    def test_normal(self):
        assert MeituanH5Scraper._parse_monthly_sales("月售320") == 320

    def test_numeric(self):
        assert MeituanH5Scraper._parse_monthly_sales(100) == 100

    def test_empty(self):
        assert MeituanH5Scraper._parse_monthly_sales("") == 0
