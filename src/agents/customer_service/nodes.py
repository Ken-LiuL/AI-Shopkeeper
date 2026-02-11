"""CustomerService Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import MODEL_HAIKU, MODEL_SONNET, call_tool
from ..prompts.customer_service import FAQ_TEMPLATES, HUMAN_TRANSFER_KEYWORDS, intent_prompt, reply_prompt
from ..tools import INTENT_TOOL, REPLY_TOOL
from .state import CustomerServiceState

logger = logging.getLogger(__name__)


async def intent_recognition_node(state: CustomerServiceState) -> dict:
    """Intent Sub-Agent: 意图识别（使用 Haiku，低成本快速）"""
    try:
        history_str = json.dumps(state.get("conversation_history", []), ensure_ascii=False)
        prompt = intent_prompt(
            user_message=state["user_message"],
            conversation_history=history_str,
        )
        result = await call_tool(prompt, INTENT_TOOL, model=MODEL_HAIKU)
        return {"intent": result}
    except Exception as e:
        logger.error(f"Intent recognition failed: {e}")
        return {
            "intent": {"intent": "other", "confidence": 0, "requires_human": True},
            "errors": [f"intent: {e}"],
        }


async def route_node(state: CustomerServiceState) -> dict:
    """路由节点：根据意图决定处理路径"""
    intent_data = state.get("intent", {})
    intent = intent_data.get("intent", "other")

    # 检查是否需要转人工
    if intent_data.get("requires_human", False):
        return {"route": "human"}

    # 检查消息中是否包含转人工触发词
    msg = state.get("user_message", "").lower()
    for kw in HUMAN_TRANSFER_KEYWORDS:
        if kw in msg:
            return {"route": "human"}

    # FAQ 路由
    if intent in ("greeting", "logistics"):
        return {"route": "faq"}

    # 需要转人工的意图
    if intent in ("complaint", "after_sales"):
        return {"route": "human"}

    # 默认走检索
    return {"route": "search"}


def get_route(state: CustomerServiceState) -> str:
    """条件边函数：返回路由方向"""
    return state.get("route", "search")


async def faq_reply_node(state: CustomerServiceState) -> dict:
    """FAQ 快捷回复"""
    intent = state.get("intent", {}).get("intent", "greeting")
    msg = state.get("user_message", "").lower()

    templates = FAQ_TEMPLATES.get(intent, FAQ_TEMPLATES.get("greeting", []))
    if isinstance(templates, dict):
        return {"faq_reply": templates.get("reply", "亲，在的呢~请问有什么可以帮您？😊")}

    for tpl in templates:
        triggers = tpl.get("trigger", [])
        if any(t in msg for t in triggers):
            return {"faq_reply": tpl["reply"]}

    # 默认
    if templates:
        return {"faq_reply": templates[0]["reply"]}
    return {"faq_reply": "亲，在的呢~请问有什么可以帮您？😊"}


async def hybrid_search_node(state: CustomerServiceState) -> dict:
    """Hybrid Search: 向量 + 关键词混合检索"""
    # NOTE: 实际实现调用 Neo4jSkill + EmbeddingSkill
    # 这里定义接口，具体数据层调用在 Skills 层
    intent_data = state.get("intent", {})
    entities = intent_data.get("extracted_entities", {})

    # placeholder - 实际由 skills 层注入
    logger.info(f"Hybrid search for entities: {entities}")
    return {"search_results": state.get("search_results", [])}


async def reranker_node(state: CustomerServiceState) -> dict:
    """Reranker: BGE 精排 Top 5"""
    # NOTE: 实际实现调用 RerankerSkill
    candidates = state.get("search_results", [])
    # placeholder - reranker 精排
    logger.info(f"Reranking {len(candidates)} candidates")
    return {"reranked_results": candidates[:5]}


async def graphrag_node(state: CustomerServiceState) -> dict:
    """GraphRAG: 获取 Top 5 商品的完整子图"""
    # NOTE: 实际实现调用 Neo4jSkill.get_product_graph
    reranked = state.get("reranked_results", [])
    # placeholder - 每个商品获取子图
    logger.info(f"Enriching {len(reranked)} products with graph context")
    return {"enriched_results": reranked}


async def reply_generation_node(state: CustomerServiceState) -> dict:
    """Reply Sub-Agent: 生成回复（使用 Sonnet）"""
    # 如果有 FAQ 回复，直接返回
    faq = state.get("faq_reply")
    if faq:
        return {
            "reply": {
                "reply_text": faq,
                "confidence": 1.0,
                "products_mentioned": [],
                "upsell_suggestions": [],
                "requires_human_review": False,
            }
        }

    try:
        enriched = state.get("enriched_results", [])
        prompt = reply_prompt(
            user_message=state["user_message"],
            intent=json.dumps(state.get("intent", {}), ensure_ascii=False),
            retrieved_products_with_graph=json.dumps(enriched, ensure_ascii=False),
        )
        result = await call_tool(prompt, REPLY_TOOL, model=MODEL_SONNET)
        return {"reply": result}
    except Exception as e:
        logger.error(f"Reply generation failed: {e}")
        return {
            "reply": {
                "reply_text": "亲，您的问题我已记录，稍后为您回复~",
                "confidence": 0,
                "requires_human_review": True,
                "review_reason": str(e),
            }
        }


async def human_transfer_node(state: CustomerServiceState) -> dict:
    """转人工处理"""
    reason = state.get("intent", {}).get("human_reason", "用户需求需要人工处理")
    return {
        "reply": {
            "reply_text": "亲，您的问题这边帮您转接人工客服处理，请稍等~",
            "confidence": 1.0,
            "requires_human_review": True,
            "review_reason": reason,
        }
    }
