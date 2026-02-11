"""Tests for Selection Agent nodes — detailed unit tests for each node."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.selection.nodes import (
    fetch_data,
    market_analysis_node,
    competitor_analysis_node,
    inventory_analysis_node,
    seasonal_analysis_node,
    gap_identification_node,
    supplier_evaluation_node,
    scorer_node,
)
from src.agents.selection.state import SelectionState


# ---------------------------------------------------------------------------
# fetch_data Node Tests
# ---------------------------------------------------------------------------

class TestFetchDataNode:
    """Tests for fetch_data node."""

    async def test_sets_current_date(self):
        """Fetch data sets current_date in YYYY-MM-DD format."""
        state: SelectionState = {}
        result = await fetch_data(state)
        
        assert "current_date" in result
        # Validate date format
        datetime.strptime(result["current_date"], "%Y-%m-%d")

    async def test_sets_current_season_spring(self):
        """Sets season to 春季 for March-May."""
        with patch("src.agents.selection.nodes.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 15)
            mock_dt.strftime = datetime.strftime
            state: SelectionState = {}
            result = await fetch_data(state)
            assert result["current_season"] == "春季"

    async def test_sets_current_season_summer(self):
        """Sets season to 夏季 for June-August."""
        with patch("src.agents.selection.nodes.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 15)
            mock_dt.strftime = datetime.strftime
            state: SelectionState = {}
            result = await fetch_data(state)
            assert result["current_season"] == "夏季"

    async def test_sets_current_season_autumn(self):
        """Sets season to 秋季 for September-November."""
        with patch("src.agents.selection.nodes.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 10, 15)
            mock_dt.strftime = datetime.strftime
            state: SelectionState = {}
            result = await fetch_data(state)
            assert result["current_season"] == "秋季"

    async def test_sets_current_season_winter(self):
        """Sets season to 冬季 for December-February."""
        with patch("src.agents.selection.nodes.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 15)
            mock_dt.strftime = datetime.strftime
            state: SelectionState = {}
            result = await fetch_data(state)
            assert result["current_season"] == "冬季"

    async def test_initializes_empty_errors(self):
        """Fetch data initializes errors as empty list."""
        state: SelectionState = {}
        result = await fetch_data(state)
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# market_analysis_node Tests
# ---------------------------------------------------------------------------

class TestMarketAnalysisNode:
    """Tests for market_analysis_node."""

    async def test_calls_call_tool_with_correct_args(self, sample_market_analysis):
        """Verifies call_tool is called with correct tool."""
        state: SelectionState = {
            "raw_keywords_data": "keywords",
            "raw_products_data": "products",
            "categories": ["医疗器械"],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = sample_market_analysis
            await market_analysis_node(state)
            
            # Verify tool name
            call_kwargs = mock_call.call_args
            assert call_kwargs[0][1]["name"] == "output_market_analysis"

    async def test_returns_market_analysis_in_result(self, sample_market_analysis):
        """Returns result with market_analysis key."""
        state: SelectionState = {
            "raw_keywords_data": "kw",
            "raw_products_data": "prod",
            "categories": ["医疗器械"],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_market_analysis):
            result = await market_analysis_node(state)
        
        assert "market_analysis" in result
        assert result["market_analysis"]["analysis_summary"] is not None

    async def test_handles_missing_categories(self, sample_market_analysis):
        """Handles missing categories with default."""
        state: SelectionState = {
            "raw_keywords_data": "kw",
            "raw_products_data": "prod",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_market_analysis):
            result = await market_analysis_node(state)
        
        assert "market_analysis" in result

    async def test_handles_missing_data_gracefully(self, sample_market_analysis):
        """Handles missing raw data with defaults."""
        state: SelectionState = {}
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_market_analysis):
            result = await market_analysis_node(state)
        
        assert "market_analysis" in result

    async def test_appends_error_on_exception(self):
        """Appends error to errors list on exception."""
        state: SelectionState = {"errors": ["prev"]}
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, side_effect=Exception("API fail")):
            result = await market_analysis_node(state)
        
        assert len(result["errors"]) == 2
        assert "market_analysis" in result["errors"][-1]


# ---------------------------------------------------------------------------
# competitor_analysis_node Tests
# ---------------------------------------------------------------------------

class TestCompetitorAnalysisNode:
    """Tests for competitor_analysis_node."""

    async def test_returns_competitor_analysis(self, sample_competitor_analysis):
        """Returns result with competitor_analysis key."""
        state: SelectionState = {
            "raw_competitor_stores": "stores",
            "raw_competitor_products": "products",
            "raw_stockouts": "stockouts",
            "raw_our_products": "our",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_competitor_analysis):
            result = await competitor_analysis_node(state)
        
        assert "competitor_analysis" in result
        assert "gap_products" in result["competitor_analysis"]

    async def test_identifies_high_threat_competitors(self, sample_competitor_analysis):
        """Correctly processes high threat competitor data."""
        state: SelectionState = {
            "raw_competitor_stores": "stores",
            "raw_competitor_products": "products",
            "raw_stockouts": "stockouts",
            "raw_our_products": "our",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_competitor_analysis):
            result = await competitor_analysis_node(state)
        
        summary = result["competitor_analysis"]["competitor_summary"]
        assert summary["high_threat_count"] == 2

    async def test_error_handling(self):
        """Handles errors and appends to errors list."""
        state: SelectionState = {"errors": []}
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            result = await competitor_analysis_node(state)
        
        assert len(result["errors"]) == 1
        assert "competitor_analysis" in result["errors"][0]


# ---------------------------------------------------------------------------
# inventory_analysis_node Tests
# ---------------------------------------------------------------------------

class TestInventoryAnalysisNode:
    """Tests for inventory_analysis_node."""

    async def test_returns_inventory_analysis(self, sample_inventory_analysis):
        """Returns result with inventory_analysis key."""
        state: SelectionState = {
            "raw_our_products": "products",
            "raw_sales_data": "sales",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_inventory_analysis):
            result = await inventory_analysis_node(state)
        
        assert "inventory_analysis" in result
        assert "inventory_summary" in result["inventory_analysis"]

    async def test_calculates_health_score(self, sample_inventory_analysis):
        """Verifies health_score is included in result."""
        state: SelectionState = {
            "raw_our_products": "products",
            "raw_sales_data": "sales",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_inventory_analysis):
            result = await inventory_analysis_node(state)
        
        assert "health_score" in result["inventory_analysis"]["inventory_summary"]

    async def test_identifies_problem_products(self, sample_inventory_analysis):
        """Includes problem products in analysis."""
        state: SelectionState = {
            "raw_our_products": "products",
            "raw_sales_data": "sales",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_inventory_analysis):
            result = await inventory_analysis_node(state)
        
        assert "problem_products" in result["inventory_analysis"]


# ---------------------------------------------------------------------------
# seasonal_analysis_node Tests
# ---------------------------------------------------------------------------

class TestSeasonalAnalysisNode:
    """Tests for seasonal_analysis_node."""

    async def test_returns_seasonal_factors(self, sample_seasonal_factors):
        """Returns result with seasonal_factors key."""
        state: SelectionState = {
            "current_date": "2026-02-11",
            "current_season": "冬季",
            "raw_upcoming_events": "春节",
            "raw_weather_forecast": "降温",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_seasonal_factors):
            result = await seasonal_analysis_node(state)
        
        assert "seasonal_factors" in result

    async def test_identifies_urgent_factors(self, sample_seasonal_factors):
        """Identifies factors marked as urgent."""
        state: SelectionState = {
            "current_date": "2026-02-11",
            "current_season": "冬季",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_seasonal_factors):
            result = await seasonal_analysis_node(state)
        
        factors = result["seasonal_factors"]["factors"]
        urgent_factors = [f for f in factors if f.get("urgency") == "urgent"]
        assert len(urgent_factors) >= 1

    async def test_includes_weather_impact(self, sample_seasonal_factors):
        """Includes weather impact analysis."""
        state: SelectionState = {
            "current_date": "2026-02-11",
            "current_season": "冬季",
            "raw_weather_forecast": "寒潮",
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_seasonal_factors):
            result = await seasonal_analysis_node(state)
        
        assert "weather_impact" in result["seasonal_factors"]


# ---------------------------------------------------------------------------
# gap_identification_node Tests
# ---------------------------------------------------------------------------

class TestGapIdentificationNode:
    """Tests for gap_identification_node."""

    async def test_identifies_gap_opportunities(self, sample_gap_opportunities, sample_market_analysis,
                                                 sample_competitor_analysis, sample_inventory_analysis,
                                                 sample_seasonal_factors):
        """Identifies gap opportunities from all data sources."""
        state: SelectionState = {
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
            "seasonal_factors": sample_seasonal_factors,
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_gap_opportunities):
            result = await gap_identification_node(state)
        
        assert "gap_opportunities" in result
        assert len(result["gap_opportunities"]["opportunities"]) > 0

    async def test_ranks_opportunities_by_priority(self, sample_gap_opportunities, sample_market_analysis,
                                                    sample_competitor_analysis, sample_inventory_analysis,
                                                    sample_seasonal_factors):
        """Opportunities are ranked by priority."""
        state: SelectionState = {
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
            "seasonal_factors": sample_seasonal_factors,
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_gap_opportunities):
            result = await gap_identification_node(state)
        
        opps = result["gap_opportunities"]["opportunities"]
        # First opportunity should have rank 1
        assert opps[0]["rank"] == 1

    async def test_includes_gap_summary(self, sample_gap_opportunities, sample_market_analysis,
                                        sample_competitor_analysis, sample_inventory_analysis,
                                        sample_seasonal_factors):
        """Includes summary with counts."""
        state: SelectionState = {
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
            "seasonal_factors": sample_seasonal_factors,
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_gap_opportunities):
            result = await gap_identification_node(state)
        
        summary = result["gap_opportunities"]["gap_summary"]
        assert "total_opportunities" in summary
        assert "high_priority" in summary


# ---------------------------------------------------------------------------
# supplier_evaluation_node Tests
# ---------------------------------------------------------------------------

class TestSupplierEvaluationNode:
    """Tests for supplier_evaluation_node — dual channel (1688 + PDD)."""

    async def test_evaluates_each_opportunity(self, sample_gap_opportunities, sample_supplier_evaluation):
        """Evaluates each gap opportunity."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "raw_alibaba_results": {"制氧机": "ali1", "雾化器": "ali2"},
            "raw_pdd_results": {"制氧机": "pdd1", "雾化器": "pdd2"},
            "errors": [],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_supplier_evaluation):
            result = await supplier_evaluation_node(state)
        
        # 2 opportunities → 2 evaluations
        assert len(result["supplier_evaluations"]) == 2

    async def test_skips_empty_keywords(self, sample_supplier_evaluation):
        """Skips opportunities with empty keyword."""
        state: SelectionState = {
            "gap_opportunities": {
                "opportunities": [
                    {"keyword": "", "market_heat_score": 50},
                    {"keyword": "血压计", "market_heat_score": 80},
                ],
            },
            "raw_alibaba_results": {},
            "raw_pdd_results": {},
            "errors": [],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_supplier_evaluation):
            result = await supplier_evaluation_node(state)
        
        # Only 1 evaluation (empty keyword skipped)
        assert len(result["supplier_evaluations"]) == 1

    async def test_handles_partial_failures(self, sample_supplier_evaluation):
        """Continues with remaining keywords when one fails."""
        call_count = 0
        
        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("First call failed")
            return sample_supplier_evaluation
        
        state: SelectionState = {
            "gap_opportunities": {
                "opportunities": [
                    {"keyword": "制氧机", "market_heat_score": 80},
                    {"keyword": "雾化器", "market_heat_score": 60},
                ],
            },
            "raw_alibaba_results": {},
            "raw_pdd_results": {},
            "errors": [],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, side_effect=mock_call):
            result = await supplier_evaluation_node(state)
        
        assert len(result["supplier_evaluations"]) == 1
        assert len(result["errors"]) == 1
        assert "制氧机" in result["errors"][0]

    async def test_includes_dual_channel_comparison(self, sample_supplier_evaluation):
        """Evaluation includes comparison between 1688 and PDD."""
        state: SelectionState = {
            "gap_opportunities": {
                "opportunities": [{"keyword": "血压计", "market_heat_score": 80}],
            },
            "raw_alibaba_results": {"血压计": "ali data"},
            "raw_pdd_results": {"血压计": "pdd data"},
            "errors": [],
        }
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_supplier_evaluation):
            result = await supplier_evaluation_node(state)
        
        eval_result = result["supplier_evaluations"][0]
        assert "cost_comparison" in eval_result
        assert "cheaper_channel" in eval_result["cost_comparison"]

    async def test_handles_empty_opportunities(self):
        """Handles empty opportunities list."""
        state: SelectionState = {
            "gap_opportunities": {"opportunities": []},
            "errors": [],
        }
        
        result = await supplier_evaluation_node(state)
        
        assert result["supplier_evaluations"] == []


# ---------------------------------------------------------------------------
# scorer_node Tests
# ---------------------------------------------------------------------------

class TestScorerNode:
    """Tests for scorer_node — 6-dimension scoring with self-reflection."""

    async def test_uses_call_tool_with_reflection(self, sample_recommendations, sample_gap_opportunities,
                                                   sample_supplier_evaluation, sample_seasonal_factors,
                                                   sample_market_analysis, sample_competitor_analysis,
                                                   sample_inventory_analysis):
        """Uses call_tool_with_reflection for self-correction."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock) as mock_reflect:
            mock_reflect.return_value = sample_recommendations
            await scorer_node(state)
            
            mock_reflect.assert_called_once()

    async def test_returns_recommendations(self, sample_recommendations, sample_gap_opportunities,
                                           sample_supplier_evaluation, sample_seasonal_factors,
                                           sample_market_analysis, sample_competitor_analysis,
                                           sample_inventory_analysis):
        """Returns result with recommendations key."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock, return_value=sample_recommendations):
            result = await scorer_node(state)
        
        assert "recommendations" in result

    async def test_includes_score_breakdown(self, sample_recommendations, sample_gap_opportunities,
                                            sample_supplier_evaluation, sample_seasonal_factors,
                                            sample_market_analysis, sample_competitor_analysis,
                                            sample_inventory_analysis):
        """Recommendations include 6-dimension score breakdown."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock, return_value=sample_recommendations):
            result = await scorer_node(state)
        
        rec = result["recommendations"]["recommendations"][0]
        breakdown = rec["score_breakdown"]
        expected_dims = ["market_heat", "competition_gap", "supply_chain",
                        "profit_margin", "category_synergy", "seasonal_fit"]
        for dim in expected_dims:
            assert dim in breakdown

    async def test_includes_reflection_notes(self, sample_recommendations, sample_gap_opportunities,
                                              sample_supplier_evaluation, sample_seasonal_factors,
                                              sample_market_analysis, sample_competitor_analysis,
                                              sample_inventory_analysis):
        """Recommendations include reflection_notes from self-reflection."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock, return_value=sample_recommendations):
            result = await scorer_node(state)
        
        assert "reflection_notes" in result["recommendations"]

    async def test_uses_opus_model(self, sample_recommendations, sample_gap_opportunities,
                                   sample_supplier_evaluation, sample_seasonal_factors,
                                   sample_market_analysis, sample_competitor_analysis,
                                   sample_inventory_analysis):
        """Scorer uses Opus model for high-quality reasoning."""
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock) as mock_reflect:
            mock_reflect.return_value = sample_recommendations
            await scorer_node(state)
            
            call_kwargs = mock_reflect.call_args.kwargs
            # Should use MODEL_OPUS (the highest-tier model)
            from src.agents.llm import MODEL_OPUS
            assert call_kwargs["model"] == MODEL_OPUS

    async def test_error_handling(self):
        """Appends error on exception."""
        state: SelectionState = {"errors": []}
        
        with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock, side_effect=RuntimeError("opus fail")):
            result = await scorer_node(state)
        
        assert len(result["errors"]) == 1
        assert "scorer" in result["errors"][0]
