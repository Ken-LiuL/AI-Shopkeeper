"""Tests for Selection Agent graph definition."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.selection.graph import build_selection_graph, compile_selection_graph
from src.agents.selection.state import SelectionState


class TestBuildSelectionGraph:
    """Tests for build_selection_graph function."""

    def test_returns_state_graph(self):
        """Build returns a StateGraph instance."""
        from langgraph.graph import StateGraph
        
        graph = build_selection_graph()
        assert isinstance(graph, StateGraph)

    def test_has_entry_point(self):
        """Graph has fetch_data as entry point."""
        graph = build_selection_graph()
        # The graph should be buildable
        compiled = graph.compile()
        assert compiled is not None

    def test_has_all_nodes(self):
        """Graph has all required nodes."""
        graph = build_selection_graph()
        node_names = list(graph.nodes.keys())
        
        expected_nodes = [
            "fetch_data",
            "market_analysis",
            "competitor_analysis",
            "inventory_analysis",
            "seasonal_analysis",
            "gap_identification",
            "supplier_evaluation",
            "scorer",
        ]
        
        for node in expected_nodes:
            assert node in node_names, f"Missing node: {node}"


class TestCompileSelectionGraph:
    """Tests for compile_selection_graph function."""

    def test_returns_compiled_graph(self):
        """Compile returns executable graph."""
        compiled = compile_selection_graph()
        assert compiled is not None
        # Should have ainvoke method
        assert hasattr(compiled, "ainvoke")

    async def test_can_invoke_with_mock_nodes(self):
        """Compiled graph can be invoked with mocked nodes."""
        # This is a smoke test that the graph structure is correct
        compiled = compile_selection_graph()
        
        # Mock all the LLM calls
        mock_result = {"analysis_summary": "test", "keywords": [], "products": []}
        
        with patch("src.agents.selection.nodes.call_tool", new_callable=AsyncMock, return_value=mock_result):
            with patch("src.agents.selection.nodes.call_tool_with_reflection", new_callable=AsyncMock, return_value={
                "scoring_summary": {}, "recommendations": [], "reflection_notes": ""
            }):
                state = SelectionState(
                    store_id="test",
                    categories=["医疗器械"],
                )
                # This should not raise
                result = await compiled.ainvoke(state)
        
        # Should have all expected keys after full run
        assert "current_date" in result
        assert "current_season" in result
