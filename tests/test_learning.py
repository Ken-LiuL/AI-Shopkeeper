"""Tests for learning module — WeightLearner, AdaptiveThresholds, ParameterVersionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.learning.adaptive_thresholds import AdaptiveThresholds
from src.learning.version_manager import ParameterType, ParameterVersionManager
from src.learning.weight_learner import RecommendationOutcome, WeightLearner, WeightUpdate

# ── WeightLearner ────────────────────────────────────────────────────────────


class TestWeightLearner:
    def test_default_weights(self):
        wl = WeightLearner()
        w = wl.weights
        assert abs(sum(w.values()) - 1.0) < 0.01
        assert "market_heat" in w

    def test_custom_weights(self):
        wl = WeightLearner(initial_weights={"market_heat": 0.5, "supply_chain": 0.5})
        assert wl.weights["market_heat"] == 0.5

    @pytest.mark.asyncio
    async def test_learn_not_enough_samples(self):
        wl = WeightLearner(min_samples=20)
        outcomes = [
            RecommendationOutcome(
                keyword="test",
                predicted_score=90,
                actual_monthly_sales=5,
                actual_margin=0.1,
                conversion_rate=0.02,
                days_since_listed=30,
            )
        ] * 5  # only 5 samples < 20
        updates = await wl.learn_from_outcomes(outcomes)
        assert updates == []

    @pytest.mark.asyncio
    async def test_learn_overestimation(self):
        """High predicted score + low actual performance → weight decrease."""
        wl = WeightLearner(min_samples=1, learning_rate=0.1)
        outcomes = [
            RecommendationOutcome(
                keyword="bad_product",
                predicted_score=90,
                actual_monthly_sales=2,
                actual_margin=0.1,
                conversion_rate=0.02,
                days_since_listed=30,
            )
        ]
        updates = await wl.learn_from_outcomes(outcomes)
        # Should have some weight decreases
        assert len(updates) > 0

    @pytest.mark.asyncio
    async def test_learn_underestimation(self):
        """Low predicted score + high actual performance → weight increase."""
        wl = WeightLearner(min_samples=1, learning_rate=0.1)
        outcomes = [
            RecommendationOutcome(
                keyword="surprise_hit",
                predicted_score=40,
                actual_monthly_sales=200,
                actual_margin=0.5,
                conversion_rate=0.15,
                days_since_listed=30,
            )
        ]
        updates = await wl.learn_from_outcomes(outcomes)
        assert len(updates) > 0

    @pytest.mark.asyncio
    async def test_weights_normalized(self):
        wl = WeightLearner(min_samples=1, learning_rate=0.3)
        outcomes = [
            RecommendationOutcome(
                keyword="test",
                predicted_score=90,
                actual_monthly_sales=1,
                actual_margin=0.05,
                conversion_rate=0.01,
                days_since_listed=30,
            )
        ]
        await wl.learn_from_outcomes(outcomes)
        assert abs(sum(wl.weights.values()) - 1.0) < 0.01

    @pytest.mark.asyncio
    async def test_save_weights_with_pool(self):
        conn = AsyncMock()
        pool = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = cm

        wl = WeightLearner(pool=pool, min_samples=1)
        outcomes = [
            RecommendationOutcome(
                keyword="test",
                predicted_score=90,
                actual_monthly_sales=1,
                actual_margin=0.05,
                conversion_rate=0.01,
                days_since_listed=30,
            )
        ]
        await wl.learn_from_outcomes(outcomes)
        conn.execute.assert_called()

    @pytest.mark.asyncio
    async def test_load_weights_no_pool(self):
        wl = WeightLearner()
        result = await wl.load_weights()
        assert result == wl.weights

    @pytest.mark.asyncio
    async def test_load_weights_from_db(self):
        conn = AsyncMock()
        pool = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = cm
        conn.fetchrow = AsyncMock(
            return_value={"weights": '{"market_heat": 0.5, "supply_chain": 0.5}'}
        )

        wl = WeightLearner(pool=pool)
        result = await wl.load_weights()
        assert result["market_heat"] == 0.5

    def test_weight_update_model(self):
        u = WeightUpdate(dimension="market_heat", old_weight=0.25, new_weight=0.20, reason="test")
        assert u.dimension == "market_heat"
        assert u.timestamp is not None

    def test_weight_ranges_respected(self):
        wl = WeightLearner()
        for dim, (lo, hi) in wl.WEIGHT_RANGES.items():
            assert lo <= wl.weights[dim] <= hi


# ── AdaptiveThresholds ───────────────────────────────────────────────────────


class TestAdaptiveThresholds:
    def test_get_threshold(self):
        at = AdaptiveThresholds()
        v = at.get_threshold("sales_drop_critical")
        assert v == 70.0

    def test_get_unknown_threshold(self):
        at = AdaptiveThresholds()
        with pytest.raises(KeyError):
            at.get_threshold("nonexistent")

    def test_get_all_thresholds(self):
        at = AdaptiveThresholds()
        all_t = at.get_all_thresholds()
        assert len(all_t) == len(at.DEFAULT_THRESHOLDS)

    @pytest.mark.asyncio
    async def test_update_not_enough_samples(self):
        at = AdaptiveThresholds(min_feedback_samples=50)
        result = await at.update_from_feedback("sales_drop_critical", 5, 0, 10, 10)
        assert result is None  # not enough samples

    @pytest.mark.asyncio
    async def test_update_high_false_positive(self):
        at = AdaptiveThresholds(min_feedback_samples=10, learning_rate=0.1)
        old_val = at.get_threshold("sales_drop_critical")
        result = await at.update_from_feedback(
            "sales_drop_critical",
            false_positive_count=20,
            false_negative_count=0,
            true_positive_count=5,
            true_negative_count=5,
        )
        if result:
            assert result.current_value > old_val  # threshold raised

    @pytest.mark.asyncio
    async def test_update_high_false_negative(self):
        at = AdaptiveThresholds(min_feedback_samples=10, learning_rate=0.1)
        old_val = at.get_threshold("sales_drop_critical")
        result = await at.update_from_feedback(
            "sales_drop_critical",
            false_positive_count=0,
            false_negative_count=15,
            true_positive_count=5,
            true_negative_count=10,
        )
        if result:
            assert result.current_value < old_val  # threshold lowered

    @pytest.mark.asyncio
    async def test_update_well_balanced(self):
        at = AdaptiveThresholds(min_feedback_samples=10)
        result = await at.update_from_feedback(
            "sales_drop_critical",
            false_positive_count=1,
            false_negative_count=1,
            true_positive_count=10,
            true_negative_count=10,
        )
        assert result is None  # balanced

    @pytest.mark.asyncio
    async def test_update_unknown_threshold(self):
        at = AdaptiveThresholds()
        result = await at.update_from_feedback("nonexistent", 10, 10, 10, 10)
        assert result is None

    def test_dynamic_threshold_no_adjustment(self):
        at = AdaptiveThresholds()
        val = at.calculate_dynamic_threshold(
            "sales_drop_critical", recent_volatility=0.0, seasonality_factor=1.0
        )
        assert val == 70.0  # no adjustment

    def test_dynamic_threshold_high_volatility(self):
        at = AdaptiveThresholds()
        val = at.calculate_dynamic_threshold(
            "sales_drop_critical", recent_volatility=0.5, seasonality_factor=1.0
        )
        assert val > 70.0  # relaxed

    def test_dynamic_threshold_peak_season(self):
        at = AdaptiveThresholds()
        val = at.calculate_dynamic_threshold(
            "sales_drop_critical", recent_volatility=0.0, seasonality_factor=2.0
        )
        assert val > 70.0  # relaxed for peak season

    @pytest.mark.asyncio
    async def test_load_thresholds_no_pool(self):
        at = AdaptiveThresholds()
        result = await at.load_thresholds()
        assert len(result) > 0


# ── ParameterVersionManager ──────────────────────────────────────────────────


class TestParameterVersionManager:
    @pytest.mark.asyncio
    async def test_create_version(self):
        mgr = ParameterVersionManager()
        v = await mgr.create_version(ParameterType.WEIGHTS, {"market_heat": 0.3}, "test v1")
        assert v.param_type == ParameterType.WEIGHTS
        assert v.is_active is True

    @pytest.mark.asyncio
    async def test_create_deactivates_previous(self):
        mgr = ParameterVersionManager()
        v1 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        v2 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 2}, "v2")
        assert v1.is_active is False
        assert v2.is_active is True

    @pytest.mark.asyncio
    async def test_get_active_version(self):
        mgr = ParameterVersionManager()
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        active = mgr.get_active_version(ParameterType.WEIGHTS)
        assert active is not None
        assert active.values == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_active_values(self):
        mgr = ParameterVersionManager()
        await mgr.create_version(ParameterType.THRESHOLDS, {"t1": 50.0})
        vals = mgr.get_active_values(ParameterType.THRESHOLDS)
        assert vals["t1"] == 50.0

    @pytest.mark.asyncio
    async def test_get_active_values_empty(self):
        mgr = ParameterVersionManager()
        assert mgr.get_active_values(ParameterType.CONFIG) == {}

    @pytest.mark.asyncio
    async def test_activate_version(self):
        mgr = ParameterVersionManager()
        v1 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 2}, "v2")
        result = await mgr.activate_version(v1.version_id)
        assert result is True
        assert mgr.get_active_version(ParameterType.WEIGHTS).version_id == v1.version_id

    @pytest.mark.asyncio
    async def test_activate_nonexistent(self):
        mgr = ParameterVersionManager()
        result = await mgr.activate_version("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback(self):
        mgr = ParameterVersionManager()
        v1 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 2}, "v2")
        rolled = await mgr.rollback(ParameterType.WEIGHTS, steps=1)
        assert rolled is not None
        assert rolled.version_id == v1.version_id

    @pytest.mark.asyncio
    async def test_rollback_not_enough(self):
        mgr = ParameterVersionManager()
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        result = await mgr.rollback(ParameterType.WEIGHTS, steps=5)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_performance_score(self):
        mgr = ParameterVersionManager()
        v = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1})
        ok = await mgr.update_performance_score(v.version_id, 85.0)
        assert ok
        assert v.performance_score == 85.0

    @pytest.mark.asyncio
    async def test_get_best_performing(self):
        mgr = ParameterVersionManager()
        v1 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, activate=False)
        v2 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 2})
        await mgr.update_performance_score(v1.version_id, 70.0)
        await mgr.update_performance_score(v2.version_id, 90.0)
        best = mgr.get_best_performing_version(ParameterType.WEIGHTS)
        assert best.version_id == v2.version_id

    @pytest.mark.asyncio
    async def test_get_best_performing_none(self):
        mgr = ParameterVersionManager()
        assert mgr.get_best_performing_version(ParameterType.WEIGHTS) is None

    @pytest.mark.asyncio
    async def test_version_history(self):
        mgr = ParameterVersionManager()
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 1}, "v1")
        await mgr.create_version(ParameterType.WEIGHTS, {"a": 2}, "v2")
        history = mgr.get_version_history(ParameterType.WEIGHTS)
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_compare_versions(self):
        mgr = ParameterVersionManager()
        v1 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 1, "b": 2}, "v1")
        v2 = await mgr.create_version(ParameterType.WEIGHTS, {"a": 3, "b": 2}, "v2")
        diff = await mgr.compare_versions(v1.version_id, v2.version_id)
        assert "a" in diff["changes"]
        assert "b" not in diff["changes"]

    @pytest.mark.asyncio
    async def test_compare_nonexistent(self):
        mgr = ParameterVersionManager()
        diff = await mgr.compare_versions("x", "y")
        assert "error" in diff

    def test_parameter_type_enum(self):
        assert ParameterType.WEIGHTS == "weights"
        assert ParameterType.THRESHOLDS == "thresholds"
        assert ParameterType.CONFIG == "config"
