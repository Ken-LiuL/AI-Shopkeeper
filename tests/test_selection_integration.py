"""Selection Agent 集成测试 — 完整流程（mock LLM）"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.selection.nodes import (
    competitor_analysis_node,
    fetch_data,
    gap_identification_node,
    inventory_analysis_node,
    market_analysis_node,
    scorer_node,
    seasonal_analysis_node,
    supplier_evaluation_node,
)
from src.agents.selection.state import SelectionState


# ---------------------------------------------------------------------------
# Phase 1: fetch_data
# ---------------------------------------------------------------------------

class TestFetchData:
    async def test_sets_date_and_season(self):
        state: SelectionState = {"store_id": "S001", "categories": ["医疗器械"]}
        result = await fetch_data(state)
        assert "current_date" in result
        assert "current_season" in result
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# Phase 1: 4 节点并行（Market / Competitor / Inventory / Seasonal）
# ---------------------------------------------------------------------------

class TestParallelAnalysisNodes:
    """测试四个分析节点各自正确调用 call_tool 并返回结果"""

    async def test_market_analysis(self, tool_response_factory, sample_market_analysis):
        resp = tool_response_factory("output_market_analysis", sample_market_analysis)
        state: SelectionState = {
            "raw_keywords_data": "kw data",
            "raw_products_data": "prod data",
            "categories": ["医疗器械"],
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_market_analysis):
            result = await market_analysis_node(state)
        assert "market_analysis" in result
        assert result["market_analysis"]["keywords"][0]["keyword"] == "电子血压计"

    async def test_competitor_analysis(self, sample_competitor_analysis):
        state: SelectionState = {
            "raw_competitor_stores": "stores",
            "raw_competitor_products": "products",
            "raw_stockouts": "stockouts",
            "raw_our_products": "our",
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_competitor_analysis):
            result = await competitor_analysis_node(state)
        assert result["competitor_analysis"]["gap_products"][0]["product_name"] == "制氧机"

    async def test_inventory_analysis(self, sample_inventory_analysis):
        state: SelectionState = {"raw_our_products": "our", "raw_sales_data": "sales"}
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_inventory_analysis):
            result = await inventory_analysis_node(state)
        assert result["inventory_analysis"]["inventory_summary"]["total_sku"] == 120

    async def test_seasonal_analysis(self, sample_seasonal_factors):
        state: SelectionState = {
            "current_date": "2026-02-11",
            "current_season": "冬季",
            "raw_upcoming_events": "events",
            "raw_weather_forecast": "weather",
            "raw_trending_events": "无",
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_seasonal_factors):
            result = await seasonal_analysis_node(state)
        assert result["seasonal_factors"]["factors"][0]["event_name"] == "冬季流感"

    async def test_node_error_appends_to_errors(self):
        """节点异常时，errors 列表正确追加"""
        state: SelectionState = {"categories": ["医疗器械"], "errors": ["prev_error"]}
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, side_effect=RuntimeError("API down")):
            result = await market_analysis_node(state)
        assert len(result["errors"]) == 2
        assert "market_analysis" in result["errors"][-1]


# ---------------------------------------------------------------------------
# Phase 2: Gap Identification
# ---------------------------------------------------------------------------

class TestGapIdentification:
    async def test_identifies_gaps(self, sample_gap_opportunities, sample_market_analysis,
                                    sample_competitor_analysis, sample_inventory_analysis,
                                    sample_seasonal_factors):
        state: SelectionState = {
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
            "seasonal_factors": sample_seasonal_factors,
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_gap_opportunities):
            result = await gap_identification_node(state)
        gaps = result["gap_opportunities"]
        assert gaps["gap_summary"]["total_opportunities"] == 3
        assert gaps["opportunities"][0]["keyword"] == "制氧机"


# ---------------------------------------------------------------------------
# Phase 3: Supplier Evaluation（双渠道）
# ---------------------------------------------------------------------------

class TestSupplierEvaluation:
    async def test_evaluates_each_opportunity(self, sample_gap_opportunities, sample_supplier_evaluation):
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "raw_alibaba_results": {"制氧机": "ali data", "雾化器": "ali data2"},
            "raw_pdd_results": {"制氧机": "pdd data", "雾化器": "pdd data2"},
            "errors": [],
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_supplier_evaluation):
            result = await supplier_evaluation_node(state)
        # 2 opportunities → 2 evaluations
        assert len(result["supplier_evaluations"]) == 2

    async def test_skips_empty_keyword(self, sample_supplier_evaluation):
        state: SelectionState = {
            "gap_opportunities": {
                "opportunities": [{"keyword": "", "market_heat_score": 10}],
            },
            "errors": [],
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=sample_supplier_evaluation):
            result = await supplier_evaluation_node(state)
        assert len(result["supplier_evaluations"]) == 0

    async def test_partial_failure(self, sample_gap_opportunities, sample_supplier_evaluation):
        """一个关键词评估失败，其他照常"""
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("timeout")
            return sample_supplier_evaluation

        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "raw_alibaba_results": {}, "raw_pdd_results": {},
            "errors": [],
        }
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, side_effect=_side_effect):
            result = await supplier_evaluation_node(state)
        assert len(result["supplier_evaluations"]) == 1
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# Phase 4: Scorer（含 Self-Reflection）
# ---------------------------------------------------------------------------

class TestScorer:
    async def test_scorer_with_reflection(self, sample_recommendations, sample_gap_opportunities,
                                           sample_supplier_evaluation, sample_seasonal_factors,
                                           sample_market_analysis, sample_competitor_analysis,
                                           sample_inventory_analysis):
        state: SelectionState = {
            "gap_opportunities": sample_gap_opportunities,
            "supplier_evaluations": [sample_supplier_evaluation],
            "seasonal_factors": sample_seasonal_factors,
            "market_analysis": sample_market_analysis,
            "competitor_analysis": sample_competitor_analysis,
            "inventory_analysis": sample_inventory_analysis,
        }
        with patch("src.agents.selection.nodes.call_tool_with_reflection",
                    new_callable=AsyncMock, return_value=sample_recommendations):
            result = await scorer_node(state)
        recs = result["recommendations"]
        assert recs["scoring_summary"]["recommended_count"] == 2
        assert "reflection_notes" in recs
        assert recs["recommendations"][0]["final_score"] == 87.5

    async def test_scorer_error(self):
        state: SelectionState = {"errors": []}
        with patch("src.agents.selection.nodes.call_tool_with_reflection",
                    new_callable=AsyncMock, side_effect=RuntimeError("opus error")):
            result = await scorer_node(state)
        assert any("scorer" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# 端到端状态传递
# ---------------------------------------------------------------------------

class TestStateFlow:
    """验证各阶段输出可正确被下游节点读取"""

    async def test_full_pipeline_state_keys(
        self,
        sample_market_analysis,
        sample_competitor_analysis,
        sample_inventory_analysis,
        sample_seasonal_factors,
        sample_gap_opportunities,
        sample_supplier_evaluation,
        sample_recommendations,
    ):
        """模拟完整流水线，验证最终 state 包含所有 key"""
        state: SelectionState = {
            "store_id": "S001",
            "categories": ["医疗器械"],
            "trigger_type": "manual",
        }

        # Phase 1: fetch
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock) as mock_ct:
            fetch_result = await fetch_data(state)
            state.update(fetch_result)

            # Phase 1: parallel
            mock_ct.return_value = sample_market_analysis
            state.update(await market_analysis_node(state))
            mock_ct.return_value = sample_competitor_analysis
            state.update(await competitor_analysis_node(state))
            mock_ct.return_value = sample_inventory_analysis
            state.update(await inventory_analysis_node(state))
            mock_ct.return_value = sample_seasonal_factors
            state.update(await seasonal_analysis_node(state))

            # Phase 2
            mock_ct.return_value = sample_gap_opportunities
            state.update(await gap_identification_node(state))

            # Phase 3
            mock_ct.return_value = sample_supplier_evaluation
            state.update(await supplier_evaluation_node(state))

        # Phase 4
        with patch("src.agents.selection.nodes.call_tool_with_reflection",
                    new_callable=AsyncMock, return_value=sample_recommendations):
            state.update(await scorer_node(state))

        # 验证所有关键 state key 存在
        for key in [
            "current_date", "current_season",
            "market_analysis", "competitor_analysis", "inventory_analysis", "seasonal_factors",
            "gap_opportunities", "supplier_evaluations", "recommendations",
        ]:
            assert key in state, f"Missing state key: {key}"
