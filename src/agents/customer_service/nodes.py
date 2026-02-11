"""CustomerService Agent 各节点实现"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import MODEL_FLASH, MODEL_SONNET, call_tool
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
        result = await call_tool(prompt, INTENT_TOOL, model=MODEL_FLASH)
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
    """FAQ 快捷回复 — 优先从 Neo4j FAQ 节点语义匹配，fallback 到模板。"""
    from .skills_registry import get_embedding, get_neo4j

    neo4j = get_neo4j()
    embedding_skill = get_embedding()
    query = state.get("user_message", "")

    # 尝试 Neo4j FAQ 语义检索
    if neo4j and embedding_skill and query:
        try:
            query_vec = embedding_skill.embed(query)
            faq_results = await neo4j.vector_search(
                query_embedding=query_vec,
                index_name="faq_embedding_index",
                limit=1,
            )
            if faq_results and faq_results[0].score > 0.85:
                # 高置信度 FAQ 命中，直接返回
                faq_hit = faq_results[0]
                logger.info(f"FAQ hit: {faq_hit.name} (score={faq_hit.score:.3f})")
                return {"faq_reply": faq_hit.description}
        except Exception as e:
            logger.warning(f"FAQ vector search failed, falling back to templates: {e}")

    # Fallback: 模板匹配
    intent = state.get("intent", {}).get("intent", "greeting")
    msg = query.lower()

    templates = FAQ_TEMPLATES.get(intent, FAQ_TEMPLATES.get("greeting", []))
    if isinstance(templates, dict):
        return {"faq_reply": templates.get("reply", "亲，在的呢~请问有什么可以帮您？😊")}

    for tpl in templates:
        triggers = tpl.get("trigger", [])
        if any(t in msg for t in triggers):
            return {"faq_reply": tpl["reply"]}

    if templates:
        return {"faq_reply": templates[0]["reply"]}
    return {"faq_reply": "亲，在的呢~请问有什么可以帮您？😊"}


async def hybrid_search_node(state: CustomerServiceState) -> dict:
    """Hybrid Search: 向量 + 关键词混合检索（EmbeddingSkill + Neo4jSkill）。"""
    from .skills_registry import get_embedding, get_neo4j

    neo4j = get_neo4j()
    embedding_skill = get_embedding()
    intent_data = state.get("intent", {})
    entities = intent_data.get("extracted_entities", {})
    query = state.get("user_message", "")

    # Graceful fallback: skills 未注入时走 placeholder
    if not neo4j or not embedding_skill:
        logger.warning("Skills not registered, returning empty search_results")
        return {"search_results": state.get("search_results", [])}

    try:
        # 提取关键词
        keywords: list[str] = []
        if isinstance(entities, dict):
            for v in entities.values():
                if isinstance(v, list):
                    keywords.extend(str(i) for i in v)
                elif v:
                    keywords.append(str(v))
        if not keywords:
            keywords = [w for w in query.split() if len(w) > 1]

        # 向量编码
        query_vec = embedding_skill.embed(query)

        # 混合检索（内部已做 RRF 合并）
        results = await neo4j.hybrid_search(
            query=query,
            query_embedding=query_vec,
            keywords=keywords,
            limit=20,
        )

        search_results = [r.model_dump() for r in results]
        logger.info(f"Hybrid search returned {len(search_results)} results for: {query[:50]}")
        return {"search_results": search_results}

    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        return {"search_results": [], "errors": [f"hybrid_search: {e}"]}


async def reranker_node(state: CustomerServiceState) -> dict:
    """Reranker: BGE 精排 Top 5。"""
    from .skills_registry import get_reranker

    reranker = get_reranker()
    candidates = state.get("search_results", [])
    query = state.get("user_message", "")

    if not reranker or not candidates:
        logger.info(f"Reranker skip: reranker={'yes' if reranker else 'no'}, candidates={len(candidates)}")
        return {"reranked_results": candidates[:5]}

    try:
        reranked = reranker.rerank(query=query, documents=candidates, text_field="description", top_k=5)
        logger.info(f"Reranked {len(candidates)} → {len(reranked)} results")
        return {"reranked_results": reranked}
    except Exception as e:
        logger.error(f"Reranker failed, using truncated results: {e}")
        return {"reranked_results": candidates[:5], "errors": [f"reranker: {e}"]}


async def graphrag_node(state: CustomerServiceState) -> dict:
    """GraphRAG: 获取 Top 5 商品的完整关联子图。"""
    import asyncio

    from .skills_registry import get_neo4j

    neo4j = get_neo4j()
    reranked = state.get("reranked_results", [])

    if not neo4j or not reranked:
        logger.info(f"GraphRAG skip: neo4j={'yes' if neo4j else 'no'}, reranked={len(reranked)}")
        return {"enriched_results": reranked}

    try:
        # 并发获取每个商品的子图
        tasks = [neo4j.get_product_graph(item.get("id", "")) for item in reranked]
        graphs = await asyncio.gather(*tasks, return_exceptions=True)

        enriched = []
        for item, graph in zip(reranked, graphs):
            enriched_item = dict(item)
            if isinstance(graph, Exception):
                logger.warning(f"Graph fetch failed for {item.get('id')}: {graph}")
            elif graph is not None:
                enriched_item.update({
                    "suitable_for": graph.suitable_for,
                    "contraindicated_for": [c for c in graph.contraindicated_for if c.get("name")],
                    "scenarios": graph.scenarios,
                    "related_products": graph.related_products,
                    "faqs": graph.faqs,
                    "price": graph.price,
                })
            enriched.append(enriched_item)

        logger.info(f"GraphRAG enriched {len(enriched)} products")
        return {"enriched_results": enriched}

    except Exception as e:
        logger.error(f"GraphRAG failed, using raw reranked results: {e}")
        return {"enriched_results": reranked, "errors": [f"graphrag: {e}"]}


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
