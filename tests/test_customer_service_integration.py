"""CustomerService Agent 集成测试"""

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

# ---------------------------------------------------------------------------
# Intent Recognition
# ---------------------------------------------------------------------------


class TestIntentRecognition:
    async def test_product_inquiry(self, sample_intent_product_inquiry):
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

    async def test_greeting_intent(self, sample_intent_greeting):
        state: CustomerServiceState = {"user_message": "你好", "conversation_history": []}
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_greeting,
        ):
            result = await intent_recognition_node(state)
        assert result["intent"]["intent"] == "greeting"

    async def test_complaint_intent(self, sample_intent_complaint):
        state: CustomerServiceState = {
            "user_message": "体温计坏了！太差了！",
            "conversation_history": [],
        }
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_complaint,
        ):
            result = await intent_recognition_node(state)
        assert result["intent"]["requires_human"] is True

    async def test_intent_error_fallback(self):
        state: CustomerServiceState = {"user_message": "test", "conversation_history": []}
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("api err"),
        ):
            result = await intent_recognition_node(state)
        assert result["intent"]["requires_human"] is True
        assert result["intent"]["confidence"] == 0


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class TestRouting:
    async def test_greeting_routes_to_faq(self):
        state: CustomerServiceState = {
            "user_message": "你好",
            "intent": {"intent": "greeting", "confidence": 0.98, "requires_human": False},
        }
        result = await route_node(state)
        assert result["route"] == "faq"

    async def test_logistics_routes_to_faq(self):
        state: CustomerServiceState = {
            "user_message": "多久能到？",
            "intent": {"intent": "logistics", "confidence": 0.9, "requires_human": False},
        }
        result = await route_node(state)
        assert result["route"] == "faq"

    async def test_complaint_routes_to_human(self):
        state: CustomerServiceState = {
            "user_message": "不满意",
            "intent": {"intent": "complaint", "confidence": 0.88, "requires_human": False},
        }
        result = await route_node(state)
        assert result["route"] == "human"

    async def test_requires_human_flag(self):
        state: CustomerServiceState = {
            "user_message": "test",
            "intent": {"intent": "product_inquiry", "confidence": 0.5, "requires_human": True},
        }
        result = await route_node(state)
        assert result["route"] == "human"

    async def test_human_transfer_keyword(self):
        state: CustomerServiceState = {
            "user_message": "我要投诉",
            "intent": {"intent": "product_inquiry", "confidence": 0.9, "requires_human": False},
        }
        result = await route_node(state)
        assert result["route"] == "human"

    async def test_product_inquiry_routes_to_search(self):
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry", "confidence": 0.9, "requires_human": False},
        }
        result = await route_node(state)
        assert result["route"] == "search"

    async def test_get_route_returns_state_route(self):
        assert get_route({"route": "faq"}) == "faq"
        assert get_route({"route": "search"}) == "search"
        assert get_route({}) == "search"  # default


# ---------------------------------------------------------------------------
# FAQ Reply
# ---------------------------------------------------------------------------


class TestFAQReply:
    async def test_greeting_faq(self):
        state: CustomerServiceState = {
            "user_message": "你好",
            "intent": {"intent": "greeting"},
        }
        result = await faq_reply_node(state)
        assert "在的" in result["faq_reply"]

    async def test_logistics_faq_delivery(self):
        state: CustomerServiceState = {
            "user_message": "多久能到",
            "intent": {"intent": "logistics"},
        }
        result = await faq_reply_node(state)
        assert "faq_reply" in result


# ---------------------------------------------------------------------------
# Human Transfer
# ---------------------------------------------------------------------------


class TestHumanTransfer:
    async def test_transfer_reply(self):
        state: CustomerServiceState = {
            "intent": {"human_reason": "用户投诉"},
        }
        result = await human_transfer_node(state)
        assert "转接人工" in result["reply"]["reply_text"]
        assert result["reply"]["requires_human_review"] is True


# ---------------------------------------------------------------------------
# Search → Reranker → GraphRAG → Reply
# ---------------------------------------------------------------------------


class TestSearchPipeline:
    async def test_hybrid_search(self):
        state: CustomerServiceState = {
            "intent": {"extracted_entities": {"product_mentioned": "血压计"}},
            "search_results": [
                {"product_id": "P100", "name": "鱼跃血压计", "score": 0.9},
                {"product_id": "P101", "name": "欧姆龙血压计", "score": 0.85},
            ],
        }
        result = await hybrid_search_node(state)
        assert len(result["search_results"]) == 2

    async def test_reranker_top5(self):
        state: CustomerServiceState = {
            "search_results": [{"id": str(i)} for i in range(10)],
        }
        result = await reranker_node(state)
        assert len(result["reranked_results"]) == 5

    async def test_graphrag_enriches(self):
        state: CustomerServiceState = {
            "reranked_results": [{"product_id": "P100", "name": "血压计"}],
        }
        result = await graphrag_node(state)
        assert len(result["enriched_results"]) == 1

    async def test_reply_generation_with_search(self, sample_reply):
        state: CustomerServiceState = {
            "user_message": "有血压计吗",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [{"product_id": "P100", "name": "鱼跃血压计"}],
        }
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_reply,
        ):
            result = await reply_generation_node(state)
        assert result["reply"]["confidence"] == 0.85
        assert len(result["reply"]["products_mentioned"]) > 0

    async def test_reply_generation_with_faq(self):
        """有 faq_reply 时直接返回，不调 LLM"""
        state: CustomerServiceState = {
            "user_message": "你好",
            "faq_reply": "亲，在的呢~请问有什么可以帮您？😊",
        }
        result = await reply_generation_node(state)
        assert result["reply"]["reply_text"] == state["faq_reply"]
        assert result["reply"]["confidence"] == 1.0

    async def test_reply_generation_error_fallback(self):
        state: CustomerServiceState = {
            "user_message": "查一下",
            "intent": {"intent": "product_inquiry"},
            "enriched_results": [],
        }
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            side_effect=RuntimeError("llm err"),
        ):
            result = await reply_generation_node(state)
        assert result["reply"]["requires_human_review"] is True
        assert result["reply"]["confidence"] == 0


# ---------------------------------------------------------------------------
# 端到端流程
# ---------------------------------------------------------------------------


class TestEndToEnd:
    async def test_faq_flow(self, sample_intent_greeting):
        """greeting → faq → reply (无 LLM 调用)"""
        state: CustomerServiceState = {
            "user_message": "你好",
            "conversation_history": [],
        }
        with patch(
            "src.agents.customer_service.nodes.call_tool",
            new_callable=AsyncMock,
            return_value=sample_intent_greeting,
        ):
            state.update(await intent_recognition_node(state))

        state.update(await route_node(state))
        assert state["route"] == "faq"

        state.update(await faq_reply_node(state))
        state.update(await reply_generation_node(state))
        assert "在的" in state["reply"]["reply_text"]

    async def test_search_flow(self, sample_intent_product_inquiry, sample_reply):
        """product_inquiry → search → reranker → graphrag → reply"""
        state: CustomerServiceState = {
            "user_message": "有适合老人的血压计吗",
            "conversation_history": [],
            "search_results": [{"product_id": "P100", "name": "鱼跃血压计", "score": 0.9}],
        }
        with patch(
            "src.agents.customer_service.nodes.call_tool", new_callable=AsyncMock
        ) as mock_ct:
            mock_ct.return_value = sample_intent_product_inquiry
            state.update(await intent_recognition_node(state))

            state.update(await route_node(state))
            assert state["route"] == "search"

            state.update(await hybrid_search_node(state))
            state.update(await reranker_node(state))
            state.update(await graphrag_node(state))

            mock_ct.return_value = sample_reply
            state.update(await reply_generation_node(state))

        assert state["reply"]["confidence"] > 0
        assert len(state["reply"]["products_mentioned"]) > 0

    async def test_human_flow(self, sample_intent_complaint):
        """complaint → human transfer"""
        state: CustomerServiceState = {
            "user_message": "体温计坏了要退货",
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
