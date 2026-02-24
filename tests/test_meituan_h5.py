"""Tests for src/skills/meituan_h5.py — MeituanH5Scraper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.skills.meituan_h5 import MeituanH5Scraper


@pytest.fixture
def mock_cli():
    cli = AsyncMock()
    cli.browser_open = AsyncMock()
    cli.browser_close = AsyncMock()
    cli.browser_eval = AsyncMock(return_value="")  # default: return empty string
    cli.browser_text = AsyncMock(return_value="")
    cli.cleanup = AsyncMock()
    return cli


@pytest.fixture
def scraper(mock_cli):
    from unittest.mock import MagicMock

    fp_mgr = MagicMock()
    fp = MagicMock()
    fp.generate_inject_js = MagicMock(return_value="")
    fp_mgr.get_fingerprint = MagicMock(return_value=fp)
    behavior = MagicMock()
    behavior.estimate_page_stay = MagicMock(return_value=0)
    captcha = AsyncMock()
    captcha.detect_and_handle = AsyncMock(return_value=None)  # None = no captcha
    scheduler = AsyncMock()
    scheduler.wait_for_slot = AsyncMock(return_value=True)
    scheduler.can_run = MagicMock(return_value=True)
    scheduler.report_success = MagicMock()
    scheduler.report_failure = MagicMock()
    return MeituanH5Scraper(
        cli=mock_cli,
        fingerprint_mgr=fp_mgr,
        behavior_sim=behavior,
        captcha_handler=captcha,
        scheduler=scheduler,
    )


# Disable all delays in tests
@pytest.fixture(autouse=True)
def no_delay():
    with (
        patch("src.skills.meituan_h5._random_delay", new_callable=AsyncMock),
        patch("src.skills.meituan_h5.asyncio.sleep", new_callable=AsyncMock),
    ):
        yield


# ── search_products ──────────────────────────────────────────────────────────


def _make_eval_fn(captured_data=None, dom_data=None):
    """Create a browser_eval mock that returns data based on JS content."""

    async def eval_fn(js_code, *args, **kwargs):
        js = str(js_code)
        if "__mt_captured" in js and "JSON.stringify" in js:
            # _JS_GET_CAPTURED
            return json.dumps(captured_data or [])
        if "search-result" in js or "food-item" in js or "poi-item" in js:
            # _JS_EXTRACT_SEARCH_RESULTS / _JS_EXTRACT_STORE_PRODUCTS
            return json.dumps(dom_data or [])
        if "hot-word" in js or "HotWord" in js:
            return json.dumps([])
        return ""

    return eval_fn


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
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn(captured_data=xhr_data))

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
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn(dom_data=dom_data))

        products = await scraper.search_products("血压计")
        assert len(products) == 1
        assert products[0].name == "血压计A"
        assert products[0].price == 199.0

    @pytest.mark.asyncio
    async def test_text_fallback(self, scraper, mock_cli):
        """XHR + DOM empty → text fallback."""
        text = (
            "健康大药房 光谷店 距离1.2km\n月售120 ¥199\n"
            "另一家药店 关山大道店\n月售50 ¥89\n"
            "填充文本确保长度足够 padding text to exceed fifty characters\n"
        )
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn())
        mock_cli.browser_text = AsyncMock(return_value=text)

        products = await scraper.search_products("健康")
        assert len(products) >= 1
        assert products[0].monthly_sales == 120

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self, scraper, mock_cli):
        """All strategies fail → empty list, no exception."""
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn())
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
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn())
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
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn(dom_data=items))

        products = await scraper.get_store_products("12345")
        assert len(products) == 1
        assert products[0].name == "产品A"

    @pytest.mark.asyncio
    async def test_empty(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn())
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
                CompetitorProduct(
                    product_id="1", name="A", price=10, monthly_sales=100, store_name="S"
                ),
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
        hot_words = ["血压计", "口罩", "体温计"]

        async def eval_fn(js, *a, **kw):
            if "hot-word" in str(js) or "HotWord" in str(js):
                return json.dumps(hot_words)
            return ""

        mock_cli.browser_eval = AsyncMock(side_effect=eval_fn)
        keywords = await scraper.search_hot_keywords()
        assert keywords == hot_words

    @pytest.mark.asyncio
    async def test_empty(self, scraper, mock_cli):
        mock_cli.browser_eval = AsyncMock(side_effect=_make_eval_fn())
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
