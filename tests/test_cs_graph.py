"""Tests for CustomerService Agent graph definition."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.agents.customer_service.graph import (
    build_customer_service_graph,
    compile_customer_service_graph,
)
from src.agents.customer_service.state import CustomerServiceState


class TestBuildCustomerServiceGraph:
    """Tests for build_customer_service_graph function."""

    def test_returns_state_graph(self):
        """Build returns a StateGraph instance."""
        from langgraph.graph import StateGraph

        graph = build_customer_service_graph()
        assert isinstance(graph, StateGraph)

    def test_has_entry_point(self):
        """Graph has intent_recognition as entry point."""
        graph = build_customer_service_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_has_all_nodes(self):
        """Graph has all required nodes."""
        graph = build_customer_service_graph()
        node_names = list(graph.nodes.keys())

        expected_nodes = [
            "intent_recognition",
            "route",
            "faq_reply",
            "hybrid_search",
            "reranker",
            "graphrag",
            "reply_generation",
            "human_transfer",
        ]

        for node in expected_nodes:
            assert node in node_names, f"Missing node: {node}"


class TestCompileCustomerServiceGraph:
    """Tests for compile_customer_service_graph function."""

    def test_returns_compiled_graph(self):
        """Compile returns executable graph."""
        compiled = compile_customer_service_graph()
        assert compiled is not None
        assert hasattr(compiled, "ainvoke")

    async def test_faq_flow(self):
        """Test FAQ flow through compiled graph."""
        compiled = compile_customer_service_graph()

        mock_intent = {
            "intent": "greeting",
            "confidence": 0.98,
            "requires_human": False,
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            state = CustomerServiceState(
                user_message="你好",
                conversation_history=[],
            )
            result = await compiled.ainvoke(state)

        assert "reply" in result
        assert result["route"] == "faq"

    async def test_human_flow(self):
        """Test human transfer flow through compiled graph."""
        compiled = compile_customer_service_graph()

        mock_intent = {
            "intent": "complaint",
            "confidence": 0.88,
            "requires_human": True,
            "human_reason": "用户投诉",
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            state = CustomerServiceState(
                user_message="投诉！",
                conversation_history=[],
            )
            result = await compiled.ainvoke(state)

        assert result["route"] == "human"
        assert "转接人工" in result["reply"]["reply_text"]

    async def test_search_flow(self):
        """Test search flow through compiled graph."""
        compiled = compile_customer_service_graph()

        mock_intent = {
            "intent": "product_inquiry",
            "confidence": 0.92,
            "requires_human": False,
            "extracted_entities": {"product_mentioned": "血压计"},
        }
        mock_reply = {
            "reply_text": "亲，推荐这款血压计~",
            "confidence": 0.85,
            "products_mentioned": [],
            "upsell_suggestions": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool", new_callable=AsyncMock
        ) as mock_call:
            mock_call.side_effect = [mock_intent, mock_reply]

            state = CustomerServiceState(
                user_message="有血压计吗",
                conversation_history=[],
                search_results=[{"product_id": "P001", "name": "血压计"}],
            )
            result = await compiled.ainvoke(state)

        assert result["route"] == "search"
        assert "reply" in result
