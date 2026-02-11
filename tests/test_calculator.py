"""Tests for Calculator Skill."""

from __future__ import annotations

import pytest

from src.skills.calculator import CalculatorSkill


@pytest.fixture
def calc() -> CalculatorSkill:
    return CalculatorSkill()


# ── heat_score ───────────────────────────────────────────────────────────────

class TestHeatScore:
    def test_low_volume(self, calc: CalculatorSkill):
        r = calc.heat_score("血压计", search_volume=500, growth_rate=0.0, conversion_rate=0.1)
        assert r.heat_score == 20.0  # 0.2 * 1.0 * 1.0 * 100
        assert r.trend == "stable"

    def test_high_volume_rising(self, calc: CalculatorSkill):
        r = calc.heat_score("口罩", search_volume=60000, growth_rate=0.3, conversion_rate=0.1)
        # 1.0 * 1.3 * 1.0 * 100 = 130 → capped at 100
        assert r.heat_score == 100.0
        assert r.trend == "rising"

    def test_declining_trend(self, calc: CalculatorSkill):
        r = calc.heat_score("体温计", search_volume=3000, growth_rate=-0.1, conversion_rate=0.1)
        assert r.trend == "declining"

    def test_zero_conversion(self, calc: CalculatorSkill):
        r = calc.heat_score("测试", search_volume=10000, growth_rate=0.0, conversion_rate=0.0)
        assert r.heat_score == 0.0  # conv_factor = 0

    def test_growth_capped(self, calc: CalculatorSkill):
        r1 = calc.heat_score("a", search_volume=5000, growth_rate=0.5, conversion_rate=0.1)
        r2 = calc.heat_score("b", search_volume=5000, growth_rate=1.0, conversion_rate=0.1)
        assert r1.heat_score == r2.heat_score  # both capped at 0.5

    def test_volume_thresholds(self, calc: CalculatorSkill):
        """Verify each volume bracket."""
        vols = [500, 2000, 8000, 30000, 60000]
        expected_norm = [0.2, 0.4, 0.6, 0.8, 1.0]
        for vol, exp in zip(vols, expected_norm):
            r = calc.heat_score("k", search_volume=vol, growth_rate=0.0, conversion_rate=0.1)
            assert r.heat_score == pytest.approx(exp * 100, abs=0.1)


# ── alibaba_supplier_score ───────────────────────────────────────────────────

class TestAlibabaSupplierScore:
    def test_perfect_supplier(self, calc: CalculatorSkill):
        r = calc.alibaba_supplier_score(
            is_power_seller=True, years=6, shop_score=4.9,
            trade_level="gold", return_rate=0.35,
            product_match="exact", price_rank="lowest",
        )
        assert r.total_score == 100.0
        assert r.source == "alibaba"

    def test_weak_supplier(self, calc: CalculatorSkill):
        r = calc.alibaba_supplier_score(
            is_power_seller=False, years=0, shop_score=4.0,
            trade_level="", return_rate=0.05,
            product_match="marginal", price_rank="average",
        )
        assert r.total_score < 30

    def test_mid_range(self, calc: CalculatorSkill):
        r = calc.alibaba_supplier_score(
            is_power_seller=False, years=3, shop_score=4.6,
            trade_level="silver", return_rate=0.22,
            product_match="similar", price_rank="second",
        )
        assert 45 < r.total_score < 75
        assert "years" in r.breakdown


# ── pdd_product_score ────────────────────────────────────────────────────────

class TestPddProductScore:
    def test_top_product(self, calc: CalculatorSkill):
        r = calc.pdd_product_score(
            shop_score=4.9, sales_count=2000,
            price_rank="lowest", review_count=800,
        )
        assert r.total_score == 100.0
        assert r.source == "pdd"

    def test_low_product(self, calc: CalculatorSkill):
        r = calc.pdd_product_score(
            shop_score=4.0, sales_count=50,
            price_rank="average", review_count=20,
        )
        assert r.total_score < 50

    def test_breakdown_keys(self, calc: CalculatorSkill):
        r = calc.pdd_product_score(shop_score=4.5, sales_count=500, price_rank="second", review_count=200)
        assert set(r.breakdown.keys()) == {"shop_score", "sales", "price", "reviews"}


# ── calculate_margin ─────────────────────────────────────────────────────────

class TestMargin:
    def test_alibaba_basic(self, calc: CalculatorSkill):
        r = calc.calculate_margin(cost=100, market_price=0, source="alibaba", weight_kg=1)
        # total_cost = (100 + 1.5) * 1.02 = 103.53
        assert r.cost == pytest.approx(103.53, abs=0.01)
        # suggested = 103.53 * 2.5 = 258.825
        assert r.suggested_price == pytest.approx(258.83, abs=0.01)
        assert r.gross_margin > 0.5
        assert r.margin_grade == "excellent"

    def test_pdd_no_shipping(self, calc: CalculatorSkill):
        r = calc.calculate_margin(cost=50, source="pdd")
        assert r.cost == 50.0

    def test_market_price_floor(self, calc: CalculatorSkill):
        """When market_price * 0.95 > cost * 2.5, use market_price floor."""
        r = calc.calculate_margin(cost=10, market_price=100, source="pdd")
        assert r.suggested_price >= 95.0  # max(25, 95) = 95

    def test_margin_grades(self, calc: CalculatorSkill):
        r = calc.calculate_margin(cost=80, market_price=100, source="pdd")
        # suggested = max(200, 95) = 200, margin = (200-80)/200 = 0.6
        assert r.margin_grade == "excellent"


# ── comprehensive_score ──────────────────────────────────────────────────────

class TestComprehensiveScore:
    def test_strong_recommend(self, calc: CalculatorSkill):
        scores = {d: 90.0 for d in [
            "market_heat", "competition_gap", "supply_chain",
            "profit_margin", "category_synergy", "seasonal_fit",
        ]}
        r = calc.comprehensive_score("血压计", scores)
        assert r.final_score == 90.0
        assert r.recommendation == "strong_recommend"

    def test_not_recommend(self, calc: CalculatorSkill):
        scores = {d: 30.0 for d in [
            "market_heat", "competition_gap", "supply_chain",
            "profit_margin", "category_synergy", "seasonal_fit",
        ]}
        r = calc.comprehensive_score("冷门品", scores)
        assert r.final_score == 30.0
        assert r.recommendation == "not_recommend"

    def test_recommend_threshold(self, calc: CalculatorSkill):
        # weights sum to 1.0, all scores = 75 → final = 75
        scores = {d: 75.0 for d in [
            "market_heat", "competition_gap", "supply_chain",
            "profit_margin", "category_synergy", "seasonal_fit",
        ]}
        r = calc.comprehensive_score("中等品", scores)
        assert r.recommendation == "recommend"

    def test_optional_threshold(self, calc: CalculatorSkill):
        scores = {d: 65.0 for d in [
            "market_heat", "competition_gap", "supply_chain",
            "profit_margin", "category_synergy", "seasonal_fit",
        ]}
        r = calc.comprehensive_score("可选品", scores)
        assert r.recommendation == "optional"

    def test_missing_dimension_defaults_zero(self, calc: CalculatorSkill):
        r = calc.comprehensive_score("缺维度", {"market_heat": 100.0})
        assert r.final_score == 25.0  # only market_heat * 0.25

    def test_custom_weights(self):
        custom = {"market_heat": 1.0}
        calc = CalculatorSkill(weights=custom)
        r = calc.comprehensive_score("自定义", {"market_heat": 80.0})
        assert r.final_score == 80.0

    def test_breakdown_present(self, calc: CalculatorSkill):
        scores = {"market_heat": 50.0, "competition_gap": 60.0, "supply_chain": 70.0,
                  "profit_margin": 80.0, "category_synergy": 40.0, "seasonal_fit": 30.0}
        r = calc.comprehensive_score("测试", scores)
        assert len(r.breakdown) == 6
        assert r.final_score == pytest.approx(sum(r.breakdown.values()), abs=0.1)


# ── RRF merge ────────────────────────────────────────────────────────────────

class TestRRFMerge:
    def test_single_list(self):
        items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        results = CalculatorSkill.rrf_merge(items, k=60)
        assert [r.id for r in results] == ["a", "b", "c"]
        assert results[0].score > results[1].score > results[2].score

    def test_two_lists_boost(self):
        list1 = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        list2 = [{"id": "b"}, {"id": "a"}, {"id": "d"}]
        results = CalculatorSkill.rrf_merge(list1, list2, k=60)
        # a: 1/61 + 1/62, b: 1/62 + 1/61 → tied scores
        ids = [r.id for r in results]
        # Both a and b appear in both lists (boosted), c and d in one each
        assert set(ids[:2]) == {"a", "b"}
        assert results[0].score == pytest.approx(results[1].score)
        assert results[0].score > results[2].score

    def test_empty_list(self):
        results = CalculatorSkill.rrf_merge([], [])
        assert results == []

    def test_custom_id_field(self):
        items = [{"product_id": "x"}, {"product_id": "y"}]
        results = CalculatorSkill.rrf_merge(items, id_field="product_id")
        assert results[0].id == "x"

    def test_data_preserved(self):
        items = [{"id": "a", "name": "Alpha", "score": 0.9}]
        results = CalculatorSkill.rrf_merge(items)
        assert results[0].data["name"] == "Alpha"
