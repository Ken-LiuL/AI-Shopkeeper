"""Tests for CustomerService Agent nodes — detailed unit tests for each node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.agents.customer_service.nodes import (
    faq_reply_node,
    get_route,
    graphrag_node,
    human_transfer_node,
    hybrid_search_node,
    intent_recognition_node,
    reply_generation_node,
    reranker_node,
    route_node,
)
from src.agents.customer_service.state import CustomerServiceState
from src.agents.prompts.customer_service import HUMAN_TRANSFER_KEYWORDS

# ---------------------------------------------------------------------------
# Intent Recognition Tests
# ---------------------------------------------------------------------------


class TestIntentRecognitionNode:
    """Tests for intent_recognition_node."""

    async def test_product_inquiry_intent(self, sample_intent_product_inquiry):
        """Recognizes product_inquiry intent."""
        state: CustomerServiceState = {
            "user_message": "有没有适合老人用的血压计？",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_product_inquiry,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "product_inquiry"
        assert result["intent"]["confidence"] > 0.9

    async def test_usage_question_intent(self):
        """Recognizes usage_question intent."""
        mock_intent = {
            "intent": "usage_question",
            "confidence": 0.88,
            "extracted_entities": {"product_mentioned": "血压计"},
            "sentiment": "neutral",
            "requires_human": False,
        }

        state: CustomerServiceState = {
            "user_message": "血压计怎么用？",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "usage_question"

    async def test_recommendation_intent(self):
        """Recognizes recommendation intent."""
        mock_intent = {
            "intent": "recommendation",
            "confidence": 0.92,
            "extracted_entities": {"target_population": "老人"},
            "sentiment": "neutral",
            "requires_human": False,
        }

        state: CustomerServiceState = {
            "user_message": "推荐一款适合老人的血压计",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "recommendation"

    async def test_logistics_intent(self):
        """Recognizes logistics intent."""
        mock_intent = {
            "intent": "logistics",
            "confidence": 0.95,
            "extracted_entities": {},
            "sentiment": "neutral",
            "requires_human": False,
        }

        state: CustomerServiceState = {
            "user_message": "多久能送到？",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "logistics"

    async def test_after_sales_intent(self):
        """Recognizes after_sales intent."""
        mock_intent = {
            "intent": "after_sales",
            "confidence": 0.85,
            "extracted_entities": {"product_mentioned": "体温计"},
            "sentiment": "negative",
            "requires_human": True,
            "human_reason": "售后问题需人工处理",
        }

        state: CustomerServiceState = {
            "user_message": "体温计坏了要退货",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "after_sales"
        assert result["intent"]["requires_human"] is True

    async def test_complaint_intent(self, sample_intent_complaint):
        """Recognizes complaint intent."""
        state: CustomerServiceState = {
            "user_message": "你们店太差了！骗子！",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_complaint,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "complaint"
        assert result["intent"]["requires_human"] is True

    async def test_greeting_intent(self, sample_intent_greeting):
        """Recognizes greeting intent."""
        state: CustomerServiceState = {
            "user_message": "你好",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_greeting,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["intent"] == "greeting"

    async def test_low_confidence_fallback(self):
        """Low confidence results in requires_human flag."""
        mock_intent = {
            "intent": "other",
            "confidence": 0.3,
            "extracted_entities": {},
            "sentiment": "neutral",
            "requires_human": True,
            "human_reason": "无法确定意图",
        }

        state: CustomerServiceState = {
            "user_message": "嗯嗯",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=mock_intent,
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["requires_human"] is True

    async def test_error_fallback(self):
        """API error results in safe fallback."""
        state: CustomerServiceState = {
            "user_message": "test",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            result = await intent_recognition_node(state)

        assert result["intent"]["requires_human"] is True
        assert result["intent"]["confidence"] == 0
        assert "errors" in result

    async def test_extracts_product_entity(self, sample_intent_product_inquiry):
        """Extracts product_mentioned entity."""
        state: CustomerServiceState = {
            "user_message": "血压计多少钱",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_product_inquiry,
        ):
            result = await intent_recognition_node(state)

        entities = result["intent"]["extracted_entities"]
        assert "product_mentioned" in entities

    async def test_extracts_target_population(self, sample_intent_product_inquiry):
        """Extracts target_population entity."""
        state: CustomerServiceState = {
            "user_message": "有没有适合老人用的血压计",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_product_inquiry,
        ):
            result = await intent_recognition_node(state)

        entities = result["intent"]["extracted_entities"]
        assert "target_population" in entities


# ---------------------------------------------------------------------------
# Route Node Tests
# ---------------------------------------------------------------------------


class TestRouteNode:
    """Tests for route_node."""

    async def test_greeting_routes_to_faq(self):
        """Greeting intent routes to FAQ."""
        state: CustomerServiceState = {
            "user_message": "你好",
            "intent": {"intent": "greeting", "confidence": 0.98, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "faq"

    async def test_logistics_routes_to_faq(self):
        """Logistics intent routes to FAQ."""
        state: CustomerServiceState = {
            "user_message": "多久能到？",
            "intent": {"intent": "logistics", "confidence": 0.95, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "faq"

    async def test_complaint_routes_to_human(self):
        """Complaint intent routes to human."""
        state: CustomerServiceState = {
            "user_message": "太差了",
            "intent": {"intent": "complaint", "confidence": 0.88, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "human"

    async def test_after_sales_routes_to_human(self):
        """After sales intent routes to human."""
        state: CustomerServiceState = {
            "user_message": "退货",
            "intent": {"intent": "after_sales", "confidence": 0.85, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "human"

    async def test_requires_human_flag_routes_to_human(self):
        """requires_human=True routes to human regardless of intent."""
        state: CustomerServiceState = {
            "user_message": "test",
            "intent": {"intent": "product_inquiry", "confidence": 0.5, "requires_human": True},
        }

        result = await route_node(state)
        assert result["route"] == "human"

    async def test_human_transfer_keyword_routes_to_human(self):
        """Human transfer keywords in message route to human."""
        for keyword in HUMAN_TRANSFER_KEYWORDS[:3]:  # Test first 3 keywords
            state: CustomerServiceState = {
                "user_message": f"我要{keyword}",
                "intent": {"intent": "product_inquiry", "confidence": 0.9, "requires_human": False},
            }

            result = await route_node(state)
            assert result["route"] == "human", f"Keyword '{keyword}' should route to human"

    async def test_product_inquiry_routes_to_search(self):
        """Product inquiry routes to search."""
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry", "confidence": 0.9, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "search"

    async def test_recommendation_routes_to_search(self):
        """Recommendation intent routes to search."""
        state: CustomerServiceState = {
            "user_message": "推荐一款",
            "intent": {"intent": "recommendation", "confidence": 0.9, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "search"

    async def test_default_routes_to_search(self):
        """Unknown intent defaults to search."""
        state: CustomerServiceState = {
            "user_message": "test",
            "intent": {"intent": "other", "confidence": 0.6, "requires_human": False},
        }

        result = await route_node(state)
        assert result["route"] == "search"


class TestGetRoute:
    """Tests for get_route condition function."""

    def test_returns_route_from_state(self):
        """Returns route value from state."""
        assert get_route({"route": "faq"}) == "faq"
        assert get_route({"route": "search"}) == "search"
        assert get_route({"route": "human"}) == "human"

    def test_defaults_to_search(self):
        """Defaults to search when route not in state."""
        assert get_route({}) == "search"
        assert get_route({"other_key": "value"}) == "search"


# ---------------------------------------------------------------------------
# FAQ Reply Tests
# ---------------------------------------------------------------------------


class TestFAQReplyNode:
    """Tests for faq_reply_node."""

    async def test_greeting_faq(self):
        """Returns greeting FAQ reply."""
        state: CustomerServiceState = {
            "user_message": "你好",
            "intent": {"intent": "greeting"},
        }

        result = await faq_reply_node(state)

        assert "faq_reply" in result
        assert "在的" in result["faq_reply"]

    async def test_greeting_variant(self):
        """Returns greeting for variant triggers."""
        state: CustomerServiceState = {
            "user_message": "在吗",
            "intent": {"intent": "greeting"},
        }

        result = await faq_reply_node(state)
        assert "faq_reply" in result

    async def test_logistics_delivery_time(self):
        """Returns logistics FAQ for delivery questions."""
        state: CustomerServiceState = {
            "user_message": "多久能到",
            "intent": {"intent": "logistics"},
        }

        result = await faq_reply_node(state)
        assert "faq_reply" in result

    async def test_logistics_shipping_status(self):
        """Returns logistics FAQ for shipping status."""
        state: CustomerServiceState = {
            "user_message": "发货了吗",
            "intent": {"intent": "logistics"},
        }

        result = await faq_reply_node(state)
        assert "faq_reply" in result

    async def test_logistics_delivery_range(self):
        """Returns logistics FAQ for delivery range."""
        state: CustomerServiceState = {
            "user_message": "能送到吗",
            "intent": {"intent": "logistics"},
        }

        result = await faq_reply_node(state)
        assert "faq_reply" in result

    async def test_default_faq_reply(self):
        """Returns default reply when no trigger matches."""
        state: CustomerServiceState = {
            "user_message": "随便问问",
            "intent": {"intent": "greeting"},
        }

        result = await faq_reply_node(state)
        assert "faq_reply" in result


# ---------------------------------------------------------------------------
# Human Transfer Tests
# ---------------------------------------------------------------------------


class TestHumanTransferNode:
    """Tests for human_transfer_node."""

    async def test_returns_transfer_message(self):
        """Returns human transfer message."""
        state: CustomerServiceState = {
            "intent": {"human_reason": "用户投诉"},
        }

        result = await human_transfer_node(state)

        assert "转接人工" in result["reply"]["reply_text"]

    async def test_sets_requires_human_review(self):
        """Sets requires_human_review flag."""
        state: CustomerServiceState = {
            "intent": {"human_reason": "用户投诉"},
        }

        result = await human_transfer_node(state)

        assert result["reply"]["requires_human_review"] is True

    async def test_includes_review_reason(self):
        """Includes review_reason from intent."""
        state: CustomerServiceState = {
            "intent": {"human_reason": "复杂售后问题"},
        }

        result = await human_transfer_node(state)

        assert result["reply"]["review_reason"] == "复杂售后问题"

    async def test_default_reason_when_missing(self):
        """Uses default reason when human_reason not provided."""
        state: CustomerServiceState = {
            "intent": {},
        }

        result = await human_transfer_node(state)

        assert result["reply"]["review_reason"] is not None

    async def test_high_confidence(self):
        """Transfer reply has high confidence."""
        state: CustomerServiceState = {
            "intent": {},
        }

        result = await human_transfer_node(state)

        assert result["reply"]["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Search Pipeline Tests
# ---------------------------------------------------------------------------


class TestHybridSearchNode:
    """Tests for hybrid_search_node."""

    async def test_passes_through_search_results(self):
        """Passes through existing search results."""
        state: CustomerServiceState = {
            "intent": {"extracted_entities": {"product_mentioned": "血压计"}},
            "search_results": [
                {"product_id": "P001", "name": "血压计", "score": 0.9},
            ],
        }

        result = await hybrid_search_node(state)

        assert len(result["search_results"]) == 1

    async def test_empty_search_results(self):
        """Handles empty search results."""
        state: CustomerServiceState = {
            "intent": {"extracted_entities": {}},
        }

        result = await hybrid_search_node(state)

        assert result["search_results"] == []


class TestRerankerNode:
    """Tests for reranker_node."""

    async def test_returns_top_5(self):
        """Returns top 5 reranked results."""
        state: CustomerServiceState = {
            "search_results": [{"id": str(i)} for i in range(10)],
        }

        result = await reranker_node(state)

        assert len(result["reranked_results"]) == 5

    async def test_handles_less_than_5(self):
        """Handles fewer than 5 results."""
        state: CustomerServiceState = {
            "search_results": [{"id": "1"}, {"id": "2"}],
        }

        result = await reranker_node(state)

        assert len(result["reranked_results"]) == 2

    async def test_empty_results(self):
        """Handles empty search results."""
        state: CustomerServiceState = {
            "search_results": [],
        }

        result = await reranker_node(state)

        assert result["reranked_results"] == []


class TestGraphRAGNode:
    """Tests for graphrag_node."""

    async def test_enriches_reranked_results(self):
        """Enriches reranked results with graph context."""
        state: CustomerServiceState = {
            "reranked_results": [
                {"product_id": "P001", "name": "血压计"},
            ],
        }

        result = await graphrag_node(state)

        assert len(result["enriched_results"]) == 1

    async def test_empty_results(self):
        """Handles empty reranked results."""
        state: CustomerServiceState = {
            "reranked_results": [],
        }

        result = await graphrag_node(state)

        assert result["enriched_results"] == []


# ---------------------------------------------------------------------------
# Reply Generation Tests
# ---------------------------------------------------------------------------


class TestReplyGenerationNode:
    """Tests for reply_generation_node."""

    async def test_returns_faq_reply_directly(self):
        """Returns FAQ reply without LLM call."""
        state: CustomerServiceState = {
            "user_message": "你好",
            "faq_reply": "亲，在的呢~",
        }

        result = await reply_generation_node(state)

        assert result["reply"]["reply_text"] == "亲，在的呢~"
        assert result["reply"]["confidence"] == 1.0

    async def test_calls_llm_for_search_reply(self, sample_reply):
        """Calls LLM for search-based reply."""
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [{"product_id": "P001", "name": "血压计"}],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_reply,
        ):
            result = await reply_generation_node(state)

        assert result["reply"]["confidence"] == 0.85

    async def test_includes_products_mentioned(self, sample_reply):
        """Reply includes products_mentioned."""
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_reply,
        ):
            result = await reply_generation_node(state)

        assert "products_mentioned" in result["reply"]

    async def test_includes_upsell_suggestions(self, sample_reply):
        """Reply includes upsell suggestions."""
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_reply,
        ):
            result = await reply_generation_node(state)

        assert "upsell_suggestions" in result["reply"]

    async def test_error_fallback(self):
        """Returns fallback reply on error."""
        state: CustomerServiceState = {
            "user_message": "test",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM error"),
        ):
            result = await reply_generation_node(state)

        assert result["reply"]["requires_human_review"] is True
        assert result["reply"]["confidence"] == 0

    async def test_reply_length_within_limit(self, sample_reply):
        """Reply text respects length limit."""
        state: CustomerServiceState = {
            "user_message": "test",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_reply,
        ):
            result = await reply_generation_node(state)

        # Reply tool schema has maxLength: 150
        assert len(result["reply"]["reply_text"]) <= 150


# ---------------------------------------------------------------------------
# End-to-End Flow Tests
# ---------------------------------------------------------------------------


class TestEndToEndFlows:
    """Tests for complete flow scenarios."""

    async def test_faq_flow_no_llm(self, sample_intent_greeting):
        """FAQ flow doesn't require LLM for reply."""
        state: CustomerServiceState = {
            "user_message": "你好",
            "conversation_history": [],
        }

        # Intent recognition
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_greeting,
        ):
            state.update(await intent_recognition_node(state))

        # Route
        state.update(await route_node(state))
        assert state["route"] == "faq"

        # FAQ
        state.update(await faq_reply_node(state))

        # Reply (uses FAQ)
        state.update(await reply_generation_node(state))

        # Should have reply without additional LLM call
        assert "在的" in state["reply"]["reply_text"]

    async def test_search_flow_with_llm(self, sample_intent_product_inquiry, sample_reply):
        """Search flow calls LLM for reply generation."""
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "conversation_history": [],
            "search_results": [{"product_id": "P001", "name": "血压计"}],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool", new_callable=AsyncMock
        ) as mock_call:
            # Intent
            mock_call.return_value = sample_intent_product_inquiry
            state.update(await intent_recognition_node(state))

            # Route
            state.update(await route_node(state))
            assert state["route"] == "search"

            # Search pipeline
            state.update(await hybrid_search_node(state))
            state.update(await reranker_node(state))
            state.update(await graphrag_node(state))

            # Reply
            mock_call.return_value = sample_reply
            state.update(await reply_generation_node(state))

        assert state["reply"]["confidence"] > 0

    async def test_human_flow(self, sample_intent_complaint):
        """Human transfer flow."""
        state: CustomerServiceState = {
            "user_message": "垃圾店铺，要投诉！",
            "conversation_history": [],
        }

        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_complaint,
        ):
            state.update(await intent_recognition_node(state))

        state.update(await route_node(state))
        assert state["route"] == "human"

        state.update(await human_transfer_node(state))
        assert "转接人工" in state["reply"]["reply_text"]
