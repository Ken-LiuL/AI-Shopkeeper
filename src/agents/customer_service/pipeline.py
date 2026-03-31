"""CS Agent LangGraph 5步管线：Intent → Search → Rerank → GraphRAG → Reply

管线架构：
  intent_node   — 快速意图识别 (intent.quick_intent_guess)
  search_node   — Hybrid Search: 向量+关键词 → RRF 融合 (召回候选)
  rerank_node   — Reranker 精排 (src.skills.reranker.RerankerSkill)
  graphrag_node — Neo4j 商品关联图谱上下文
  reply_node    — LLM 生成客服回复

此模块不导入 nodes.py，避免循环依赖。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# 意图初始置信度映射（规则匹配的先验置信度，会被 reply_node LLM 返回的真实值更新）
INTENT_CONFIDENCE_MAP = {
    "greeting": 0.95,       # 问候，规则完全确定
    "after_sales": 0.85,    # 售后，关键词明确
    "logistics": 0.85,
    "complaint": 0.80,
    "usage_question": 0.75,
    "product_inquiry": 0.75,
    "recommendation": 0.70,
    "medical_advice": 0.70,
    "comparison": 0.65,
    "other": 0.45,          # 未匹配到，低置信
}

# ── LangGraph 导入（graceful：未安装时给出清晰报错） ──────────────────────────

try:
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore[assignment,misc]
    END = "__end__"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 管线状态定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CSPipelineState(TypedDict, total=False):
    """LangGraph 5步管线共享状态。

    所有字段都是 Optional（total=False），由各 Node 增量填充。
    """

    # ── 输入字段（由 _chat_via_pipeline 初始化） ──────────────────────
    user_message: str
    session_id: str
    pool: Any
    conversation_history: list[dict]
    images: list[str]
    customer_info: dict
    order_context: dict
    stream: bool
    token_callback: Any
    ai_reply_id: str

    # ── Step 1: intent_node 输出 ──────────────────────────────────────
    intent: str | None
    intent_confidence: float

    # ── Step 2: search_node 输出 ─────────────────────────────────────
    search_results: list[dict]

    # ── Step 3: rerank_node 输出 ─────────────────────────────────────
    reranked_results: list[dict]

    # ── Step 4: graphrag_node 输出 ───────────────────────────────────
    graph_context: str | None

    # ── Step 5: reply_node 输出 ──────────────────────────────────────
    reply: str
    suggestions: list[str]
    needs_human: bool
    suggested_action: dict
    product_cards: list[dict]
    reply_confidence: float  # LLM 对回复内容的把握度（区别于 intent_confidence）


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Node 函数（每步逻辑自包含，graceful fallback）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def intent_node(state: CSPipelineState) -> dict:
    """Step 1 — 快速意图识别。

    调用 intent.py 中的 quick_intent_guess() + should_run_product_pipeline()。
    当规则无法匹配（other）且置信度低时，用 LLM 做二次意图兜底分类。
    """
    from src.agents.customer_service.intent import llm_intent_classify, quick_intent_guess

    message = state.get("user_message", "")
    history: list[dict] = state.get("conversation_history") or []

    intent = quick_intent_guess(message, history)
    confidence = INTENT_CONFIDENCE_MAP.get(intent, 0.60)

    # 规则无法识别时，尝试 LLM 二次分类（使用轻量 FLASH 模型）
    if intent == "other":
        llm_intent, llm_conf = await llm_intent_classify(message)
        if llm_intent != "other" or llm_conf > confidence:
            intent = llm_intent
            confidence = llm_conf
            logger.info(
                "[Pipeline:intent] LLM fallback used: intent=%s conf=%.2f",
                intent,
                confidence,
            )

    logger.info(
        "[Pipeline:intent] session=%s intent=%s conf=%.2f",
        state.get("session_id", "")[:12],
        intent,
        confidence,
    )
    return {"intent": intent, "intent_confidence": confidence}


async def search_node(state: CSPipelineState) -> dict:
    """Step 2 — Hybrid Search（向量 + 关键词 → RRF 融合）。

    不包含 Reranker；只做召回，保留 top-20 候选。
    """
    from src.agents.customer_service.intent import should_run_product_pipeline

    message: str = state.get("user_message", "")
    intent: str = state.get("intent") or "other"
    history: list[dict] = state.get("conversation_history") or []

    if not should_run_product_pipeline(intent, history):
        logger.info("[Pipeline:search] Skip — intent=%s requires no product search", intent)
        return {"search_results": []}

    results = await _hybrid_search(message)
    logger.info("[Pipeline:search] %d candidates retrieved", len(results))
    return {"search_results": results}


async def rerank_node(state: CSPipelineState) -> dict:
    """Step 3 — Reranker 精排（RerankerSkill cross-encoder）。

    输入: search_results (top-20)
    输出: reranked_results (top-5)
    """
    message: str = state.get("user_message", "")
    candidates: list[dict] = state.get("search_results") or []

    if not candidates:
        return {"reranked_results": []}

    reranked = await _apply_reranker(message, candidates)
    logger.info(
        "[Pipeline:rerank] %d → %d after reranking", len(candidates), len(reranked)
    )
    return {"reranked_results": reranked}


async def graphrag_node(state: CSPipelineState) -> dict:
    """Step 4 — GraphRAG：查 Neo4j 获取商品关联图谱上下文。

    输入: reranked_results
    输出: graph_context (str，可注入 system prompt)
    """
    products: list[dict] = state.get("reranked_results") or []

    if not products:
        return {"graph_context": None}

    graph_context = await _build_graphrag_context(products)
    logger.info(
        "[Pipeline:graphrag] context_len=%d",
        len(graph_context) if graph_context else 0,
    )
    return {"graph_context": graph_context}


async def reply_node(state: CSPipelineState) -> dict:
    """Step 5 — LLM 生成客服回复。

    整合 intent / reranked_results / graph_context 构建 prompt，
    调用 LLM 输出结构化回复。
    """
    message: str = state.get("user_message", "")
    session_id: str = state.get("session_id", "")
    pool = state.get("pool")
    intent: str = state.get("intent") or "other"
    history: list[dict] = state.get("conversation_history") or []
    product_results: list[dict] = (
        state.get("reranked_results") or state.get("search_results") or []
    )
    graph_context: str | None = state.get("graph_context")

    reply_text, needs_human, suggested_action, llm_confidence = await _generate_reply(
        message=message,
        session_id=session_id,
        pool=pool,
        intent=intent,
        conversation_history=history,
        product_results=product_results,
        graph_context=graph_context,
    )

    # 构建商品卡片
    product_cards: list[dict] = []
    for p in product_results[:3]:
        card = {
            "name": p.get("name", ""),
            "price": p.get("price") or p.get("retail_price"),
            "image_url": p.get("image_url") or p.get("image"),
            "description": (p.get("description") or "")[:200],
        }
        if card["name"]:
            product_cards.append(card)

    logger.info(
        "[Pipeline:reply] session=%s reply_len=%d needs_human=%s llm_conf=%.2f",
        session_id[:12],
        len(reply_text),
        needs_human,
        llm_confidence,
    )
    return {
        "reply": reply_text,
        "suggestions": [],
        "needs_human": needs_human,
        "suggested_action": suggested_action,
        "product_cards": product_cards,
        "reply_confidence": llm_confidence,  # LLM 对回复内容的把握度，独立于 intent_confidence
        # 不覆盖 intent_confidence，保留 intent_node 给的值
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 管线构建 & 编译
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_compiled_pipeline = None  # module-level singleton


def build_cs_pipeline():
    """构建并编译 CS Agent LangGraph 5步管线。

    Returns:
        CompiledGraph — 可直接 await pipeline.ainvoke(state) 调用。

    Raises:
        RuntimeError: 如果 langgraph 未安装。
    """
    global _compiled_pipeline

    if _compiled_pipeline is not None:
        return _compiled_pipeline

    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError(
            "langgraph is not installed. "
            "Run: pip install langgraph  (or set CS_USE_PIPELINE=false)"
        )

    graph: StateGraph = StateGraph(CSPipelineState)

    graph.add_node("intent", intent_node)
    graph.add_node("search", search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("graphrag", graphrag_node)
    graph.add_node("reply", reply_node)

    graph.set_entry_point("intent")
    graph.add_edge("intent", "search")
    graph.add_edge("search", "rerank")
    graph.add_edge("rerank", "graphrag")
    graph.add_edge("graphrag", "reply")
    graph.add_edge("reply", END)

    _compiled_pipeline = graph.compile()
    logger.info("[Pipeline] CS pipeline compiled: intent→search→rerank→graphrag→reply")
    return _compiled_pipeline


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 私有辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _hybrid_search(message: str) -> list[dict]:
    """向量 + 关键词并发检索 → RRF 融合（不含 Reranker）。"""
    try:
        from src.db import neo4j as neo4j_db
        from src.skills.embedding import EmbeddingSkill
        from src.skills.neo4j_skill import Neo4jSkill

        driver = neo4j_db.get_driver()
        neo4j_skill = Neo4jSkill(driver=driver)

        # Step A: 生成 Embedding
        query_embedding = None
        try:
            embedding_skill = EmbeddingSkill()
            query_embedding = embedding_skill.embed(message)
        except Exception as e:
            logger.warning("[Pipeline:search] Embedding failed (graceful): %s", e)

        # Step B: 并发向量检索 + 关键词检索
        async def _vec_search() -> list:
            if not query_embedding:
                return []
            try:
                return await neo4j_skill.vector_search(query_embedding, limit=10)
            except Exception as e:
                logger.warning("[Pipeline:search] Vector search failed: %s", e)
                return []

        async def _kw_search() -> list:
            try:
                words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", message)
                keywords = [w for w in words if len(w) >= 2][:10]
                if not keywords:
                    keywords = [message[:10]]
                return await neo4j_skill.keyword_search(keywords, limit=10)
            except Exception as e:
                logger.warning("[Pipeline:search] Keyword search failed: %s", e)
                return []

        vec_results, kw_results = await asyncio.gather(_vec_search(), _kw_search())

        # Step C: RRF 融合
        merged = neo4j_skill._rrf_merge(vec_results, kw_results)
        return [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "score": r.score,
            }
            for r in merged[:20]
        ]

    except Exception as e:
        logger.error("[Pipeline:search] Hybrid search failed: %s", e, exc_info=True)
        return []


async def _apply_reranker(message: str, candidates: list[dict]) -> list[dict]:
    """用 RerankerSkill 精排候选商品列表，返回 top-5。"""
    try:
        from src.skills.reranker import RerankerSkill

        loop = asyncio.get_event_loop()
        reranker = RerankerSkill()
        reranked = await loop.run_in_executor(
            None,
            lambda: reranker.rerank(message, candidates, top_k=5),
        )
        return reranked or candidates[:5]
    except Exception as e:
        logger.warning("[Pipeline:rerank] Reranker failed, fallback top-5: %s", e)
        return candidates[:5]


async def _build_graphrag_context(products: list[dict]) -> str | None:
    """从 Neo4j 获取商品关联图谱，构建可注入 prompt 的上下文字符串。"""
    try:
        from src.db import neo4j as neo4j_db
        from src.skills.neo4j_skill import Neo4jSkill

        driver = neo4j_db.get_driver()
        neo4j_skill = Neo4jSkill(driver=driver)

        async def _enrich_one(product: dict) -> dict:
            enriched = dict(product)
            pid = enriched.get("id")
            if not pid:
                return enriched
            try:
                graph_ctx, deep_ctx = await asyncio.gather(
                    neo4j_skill.get_product_graph(pid),
                    neo4j_skill.get_deep_context(pid),
                )
                if graph_ctx:
                    enriched["suitable_for"] = graph_ctx.suitable_for or []
                    enriched["contraindicated_for"] = [
                        c if isinstance(c, dict) else {"name": str(c)}
                        for c in (graph_ctx.contraindicated_for or [])
                    ]
                    enriched["related_products"] = [
                        r if isinstance(r, dict) else {"name": str(r)}
                        for r in (graph_ctx.related_products or [])
                    ]
                    enriched["scenarios"] = graph_ctx.scenarios or []
                if deep_ctx:
                    enriched["deep_context"] = {
                        "competitors": deep_ctx.get("competitors", []),
                        "seasons": deep_ctx.get("seasons", []),
                    }
            except Exception as e:
                logger.debug(
                    "[Pipeline:graphrag] Enrich failed for %s: %s", pid, e
                )
            return enriched

        enriched_products = await asyncio.gather(
            *(_enrich_one(p) for p in products),
            return_exceptions=True,
        )

        # 序列化为可注入 prompt 的文本
        context_lines: list[str] = []
        for idx, item in enumerate(enriched_products):
            if isinstance(item, BaseException):
                # gather with return_exceptions=True
                item = products[idx]
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if not name:
                continue
            parts = [f"[{name}]"]
            suitable = item.get("suitable_for") or []
            if suitable:
                parts.append(f"适用人群: {', '.join(str(s) for s in suitable[:4])}")
            related = item.get("related_products") or []
            if related:
                rel_names = [
                    r.get("name", str(r)) if isinstance(r, dict) else str(r)
                    for r in related[:3]
                ]
                parts.append(f"关联商品: {', '.join(rel_names)}")
            scenarios = item.get("scenarios") or []
            if scenarios:
                parts.append(f"使用场景: {', '.join(str(s) for s in scenarios[:3])}")
            context_lines.append(" | ".join(parts))

        return "\n".join(context_lines) if context_lines else None

    except Exception as e:
        logger.warning("[Pipeline:graphrag] GraphRAG failed (graceful): %s", e)
        return None


async def _generate_reply(
    *,
    message: str,
    session_id: str,
    pool: Any,
    intent: str,
    conversation_history: list[dict],
    product_results: list[dict],
    graph_context: str | None,
) -> tuple[str, bool, dict, float]:
    """调用 LLM 生成结构化客服回复。

    Returns:
        (reply_text, needs_human, suggested_action, confidence)
    """
    from src.agents.llm import MODEL_SONNET, call_tool

    # ── 构建 system prompt ───────────────────────────────────────────
    try:
        from src.agents.prompts.customer_service import AFTER_SALES_SCRIPTS
        from src.agents.prompts.customer_service_optimized import (
            build_optimized_system_prompt,
            build_optimized_user_message_with_context,
        )

        system_prompt = build_optimized_system_prompt(
            knowledge_base=[],
            after_sales_scripts=AFTER_SALES_SCRIPTS,
        )

        if graph_context:
            system_prompt += f"\n\n# 商品图谱上下文（GraphRAG）\n{graph_context}"

        context_prompt = build_optimized_user_message_with_context(
            user_message=message,
            conversation_history=None,   # 历史通过 llm_messages 传递
            product_results=product_results,
            conversation_context="",
            business_context=None,        # 永不暴露店铺经营数据
            intent=intent,
        )
    except Exception as e:
        logger.warning("[Pipeline:reply] Prompt build failed, using fallback: %s", e)
        system_prompt = (
            "你是一个专业的医疗器械电商AI客服助手。"
            "请根据提供的商品信息，用简洁友好的语气回答用户问题。"
            "回复控制在200字以内。"
        )
        ctx_parts = [f"用户问题：{message}"]
        if product_results:
            import json as _json
            ctx_parts.append("相关商品：" + _json.dumps(product_results[:3], ensure_ascii=False))
        context_prompt = "\n\n".join(ctx_parts)

    # ── 构建多轮 messages ────────────────────────────────────────────
    llm_messages: list[dict] = []
    prev_role: str | None = None
    for msg in (conversation_history or []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        if role == prev_role and llm_messages:
            llm_messages[-1]["content"] += f"\n{content}"
        else:
            llm_messages.append({"role": role, "content": content})
        prev_role = role

    # 当前用户消息（带完整上下文）
    if llm_messages and llm_messages[-1]["role"] == "user":
        llm_messages[-1]["content"] = context_prompt
    else:
        llm_messages.append({"role": "user", "content": context_prompt})

    # ── Tool schema ──────────────────────────────────────────────────
    tool_schema = {
        "name": "output_reply",
        "description": "输出客服回复",
        "input_schema": {
            "type": "object",
            "properties": {
                "reply_text": {"type": "string", "maxLength": 200},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "requires_human_review": {"type": "boolean"},
                "intent": {
                    "type": "string",
                    "enum": [
                        "product_inquiry",
                        "usage_question",
                        "recommendation",
                        "comparison",
                        "logistics",
                        "after_sales",
                        "complaint",
                        "medical_advice",
                        "greeting",
                        "other",
                    ],
                },
                "action": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "none",
                                "check_order",
                                "check_logistics",
                                "initiate_refund",
                                "initiate_exchange",
                                "apply_coupon",
                                "transfer_human",
                            ],
                        },
                        "order_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "amount": {"type": "number"},
                        "urgency": {"type": "string", "enum": ["normal", "urgent"]},
                    },
                    "required": ["type"],
                },
            },
            "required": ["reply_text", "confidence", "requires_human_review"],
        },
    }

    # ── LLM 调用 ────────────────────────────────────────────────────
    try:
        result = await call_tool(
            prompt=llm_messages,
            tool=tool_schema,
            model=MODEL_SONNET,
            max_tokens=512,
            system=system_prompt,
            trace_name="cs_pipeline_reply",
        )
        reply_text: str = result.get("reply_text", "亲，您的问题我已记录，稍后为您回复~")
        confidence: float = float(result.get("confidence", 0.8))
        needs_human: bool = bool(result.get("requires_human_review", False))
        suggested_action: dict = result.get("action") or {"type": "none"}

        if isinstance(suggested_action, dict) and suggested_action.get("type") == "transfer_human":
            needs_human = True
            # action 明确要求转人工 → 置信度强制为 0
            confidence = 0.0

        # 投诉 / 医疗建议类 → 置信度上限 0.5，必须转人工
        if intent in {"complaint", "medical_advice"}:
            confidence = min(confidence, 0.5)
            needs_human = True

        return reply_text, needs_human, suggested_action, confidence

    except Exception as e:
        logger.error("[Pipeline:reply] LLM call failed: %s", e, exc_info=True)
        return (
            "亲，系统繁忙，请稍后重试或联系人工客服🙏",
            True,
            {"type": "transfer_human"},
            0.0,
        )


__all__ = [
    "CSPipelineState",
    "build_cs_pipeline",
    "intent_node",
    "search_node",
    "rerank_node",
    "graphrag_node",
    "reply_node",
]
