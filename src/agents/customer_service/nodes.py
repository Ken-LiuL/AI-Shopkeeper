"""
CustomerService Agent 新版实现 - 完整检索管线

管线：意图识别 → 向量+关键词 Hybrid Search → Reranker → GraphRAG 子图丰富 → LLM 生成

模块拆分:
- fast_path.py   - 快速路径秒回
- intent.py      - 意图识别 + 分流逻辑
- search.py      - Hybrid Search + Reranker + GraphRAG 检索管线
- nodes.py       - 主编排入口 (chat 函数) + 历史遗留代码

TODO: 后续逐步将 nodes.py 中的内联实现替换为对子模块的调用。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

# P1-1: 合规过滤层（医疗器械红线）
from src.agents.customer_service.compliance import (
    COMPLIANCE_STREAM_HOLDBACK_CHARS as _COMPLIANCE_STREAM_HOLDBACK_CHARS_NEW,
)
from src.agents.customer_service.compliance import (
    soft_filter as _compliance_soft_filter,
)
from src.services.knowledge_service import (
    load_structured_knowledge,
    search_faq_context,
)

from ..llm import MODEL_DEEPSEEK, MODEL_SONNET, call_chat_stream, call_tool, call_vision

# Re-export sub-modules for gradual migration
from .fast_path import (  # noqa: F401
    is_non_actionable_placeholder,
    new_ai_reply_id,
    try_fast_path,
)
from .intent import (  # noqa: F401
    HUMAN_HANDOFF_INTENTS,
    ORDER_INTENTS,
    POLICY_INTENTS,
    PRODUCT_INTENTS,
    PROFILE_INTENTS,
    PROMPT_ENHANCER_INTENTS,
    quick_intent_guess,
    select_context_by_intent,
    should_run_product_pipeline,
)
from .search import (  # noqa: F401
    build_retrieval_cache_key,
    full_pipeline_search,
    load_cached_retrieval,
    store_cached_retrieval,
)

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LangGraph 管线开关
# 设置环境变量 CS_USE_PIPELINE=false 可回退到原有线性调用链
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USE_LANGGRAPH_PIPELINE: bool = (
    os.environ.get("CS_USE_PIPELINE", "true").lower() == "true"
)

_MAX_REPLY_TEXT_LEN = 220
# 流式回写保留的最大前瞻字符数
_COMPLIANCE_STREAM_HOLDBACK_CHARS = _COMPLIANCE_STREAM_HOLDBACK_CHARS_NEW


def _postprocess_reply_text(reply_text: str) -> str:
    """统一回复后处理：软合规过滤 + 长度限制。

    注意：此处仅执行软替换（不做硬拦截）。
    硬拦截需要 session_id 上下文，由调用方（_chat_via_pipeline / _chat_legacy）
    在返回前调用 compliance.check() 完成。
    """
    processed = _compliance_soft_filter(reply_text or "")
    if len(processed) > _MAX_REPLY_TEXT_LEN:
        processed = processed[:_MAX_REPLY_TEXT_LEN].rstrip()
    return processed


def _clean_context_text(value: object, max_len: int = 220) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def _build_extension_context_str(
    session_id: str,
    customer_info: dict[str, Any] | None,
    order_context: dict[str, Any] | None,
) -> str:
    """把扩展采集到的客服侧上下文拼成可控长度的注入段。"""
    lines: list[str] = []

    if isinstance(customer_info, dict) and customer_info:
        nickname = _clean_context_text(
            customer_info.get("nickname")
            or customer_info.get("name")
            or customer_info.get("userName")
        )
        customer_id = _clean_context_text(
            customer_info.get("customerId")
            or customer_info.get("uid")
            or customer_info.get("userId")
        )
        if nickname:
            lines.append(f"- 客户昵称：{nickname}")
        if customer_id:
            lines.append(f"- 客户标识：{customer_id}")

    if isinstance(order_context, dict) and order_context:
        active_session_id = _clean_context_text(order_context.get("active_session_id"), 80)
        if active_session_id and active_session_id != session_id:
            logger.info(
                "[CS] Skip order_context due session mismatch: request=%s active=%s",
                session_id,
                active_session_id,
            )
        else:
            fields = order_context.get("fields")
            if isinstance(fields, dict):
                label_map = {
                    "order_id": "订单号",
                    "payment_amount": "顾客支付",
                    "delivery_status": "配送状态",
                    "rider": "骑手",
                    "order_time": "下单时间",
                    "customer": "收货人",
                    "address": "收货地址",
                    "store": "门店",
                }
                for key in (
                    "order_id",
                    "payment_amount",
                    "delivery_status",
                    "rider",
                    "order_time",
                    "customer",
                    "address",
                    "store",
                ):
                    val = _clean_context_text(fields.get(key))
                    if val:
                        lines.append(f"- {label_map.get(key, key)}：{val}")

            items = order_context.get("items")
            if isinstance(items, list) and items:
                rendered_items: list[str] = []
                for item in items[:4]:
                    if not isinstance(item, dict):
                        continue
                    name = _clean_context_text(item.get("name"), 80)
                    spec = _clean_context_text(item.get("spec"), 60)
                    qty = _clean_context_text(item.get("quantity"), 30)
                    if not name:
                        continue
                    piece = name
                    if spec:
                        piece = f"{piece}（{spec}）"
                    if qty:
                        piece = f"{piece} x{qty}"
                    rendered_items.append(piece)
                if rendered_items:
                    lines.append(f"- 订单商品：{'; '.join(rendered_items)}")

            raw_text = _clean_context_text(order_context.get("raw_text"), 420)
            if raw_text:
                lines.append(f"- 工作台摘要：{raw_text}")

    if not lines:
        return ""
    return "【客服工作台上下文】\n" + "\n".join(lines)


def _extract_extension_order_fields(
    session_id: str,
    order_context: dict[str, Any] | None,
) -> dict[str, str]:
    if not isinstance(order_context, dict):
        return {}

    active_session_id = _clean_context_text(order_context.get("active_session_id"), 80)
    if active_session_id and active_session_id != session_id:
        return {}

    raw_fields = order_context.get("fields")
    if not isinstance(raw_fields, dict):
        return {}

    result: dict[str, str] = {}
    for key in (
        "order_id",
        "payment_amount",
        "delivery_status",
        "rider",
        "order_time",
        "customer",
        "address",
        "store",
    ):
        val = _clean_context_text(raw_fields.get(key), 120)
        if val:
            result[key] = val
    return result


def _is_eta_or_logistics_question(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False
    return any(
        kw in m
        for kw in (
            "什么时候",
            "多久",
            "几分钟",
            "几点",
            "还没到",
            "在哪",
            "什么意思",
            "配送",
            "骑手",
            "送达",
            "到吗",
            "催单",
        )
    )


def _build_logistics_reply_from_extension_context(
    message: str,
    session_id: str,
    order_context: dict[str, Any] | None,
) -> str | None:
    fields = _extract_extension_order_fields(session_id=session_id, order_context=order_context)
    if not fields:
        return None

    status = fields.get("delivery_status", "")
    rider = fields.get("rider", "")
    order_id = fields.get("order_id", "")
    order_time = fields.get("order_time", "")

    parts: list[str] = []

    if status:
        parts.append(f"亲，我这边帮您看到了当前配送状态是\u201c{status}\u201d。")
    else:
        parts.append("亲，我这边已经帮您查询到订单配送进度了。")

    if _is_eta_or_logistics_question(message):
        if any(kw in status for kw in ("已送达", "已完成", "已签收")):
            parts.append("订单已经送达啦，您可以查看一下门口或与骑手电话确认。")
        elif any(kw in status for kw in ("配送中", "派送中", "已接单", "已取货", "骑手已接单", "骑手已取货")):
            parts.append("目前正在配送中，通常预计 20-40 分钟内送达。")
        elif any(kw in status for kw in ("待分配", "待接单", "等待骑手", "商家备货")):
            parts.append("目前处于待配送阶段，一般会在 10-20 分钟内分配骑手后尽快送达。")
        else:
            parts.append("预计会尽快送达，建议您再留意一下骑手动态。")

    if rider and rider not in ("\u2014", "-", "暂无", "未分配"):
        parts.append(f"当前骑手信息：{rider}。")

    if order_time:
        parts.append(f"下单时间是 {order_time}。")

    if order_id:
        masked_order_id = order_id
        if len(order_id) > 8 and order_id.isdigit():
            masked_order_id = f"{order_id[:3]}***{order_id[-4:]}"
        parts.append(f"订单号（尾号）{masked_order_id}。")

    parts.append("如果超过预计时间还未送达，我这边可以继续帮您催单处理。")
    return "".join(parts)


def _build_vision_prompt_text(messages: list[dict[str, Any]], fallback_user_prompt: str) -> str:
    """把多轮 messages 压缩成适合视觉模型的纯文本 prompt。"""
    dialogue_lines: list[str] = []
    for msg in messages[-10:]:
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _clean_context_text(msg.get("content"), 320)
        if not content:
            continue
        speaker = "用户" if role == "user" else "客服"
        dialogue_lines.append(f"{speaker}：{content}")

    if dialogue_lines:
        return "【最近对话】\n" + "\n".join(dialogue_lines)
    return _clean_context_text(fallback_user_prompt, 1600)



def _select_context_by_intent(intent: str, has_product_history: bool = False) -> set:
    """返回该意图下应注入的上下文类型（上下文预算器）

    has_product_history: 如果之前对话涉及商品，即使当前意图不是商品类，
    也保留 products 上下文以避免上下文断裂。
    """
    intent_context_map = {
        "product_inquiry": {"products", "faq"},
        "recommendation": {"products", "faq"},
        "usage_question": {"products", "faq"},
        "comparison": {"products"},
        "logistics": {"order", "faq"},
        "after_sales": {"policy", "order"},
        "complaint": {"policy", "order", "profile"},
        "medical_advice": {"products", "policy"},
        "greeting": {"faq"},
        "other": {"faq"},
    }
    result = intent_context_map.get(intent, {"faq"})

    # 如果历史中有商品话题，保持 products 上下文不丢失
    if has_product_history and "products" not in result:
        result = result | {"products"}

    return result


# in-flight 检索任务去重（避免同一 cache_key 重复计算）
_retrieval_inflight: dict[str, asyncio.Task[list[dict]]] = {}


async def _run_product_pipeline_with_cache(
    *,
    message: str,
    pool,
    pipeline_timeout: float,
    redis_client,
    cache_key: str | None,
) -> list[dict]:
    async def _compute_results() -> list[dict]:
        try:
            results = await asyncio.wait_for(
                full_pipeline_search(message, pool),
                timeout=pipeline_timeout,
            )
        except TimeoutError:
            logger.warning("[CS] Pipeline timeout, falling back")
            return []

        if cache_key and results:
            await store_cached_retrieval(redis_client, cache_key, results)
        return results

    if cache_key:
        cached_results = await load_cached_retrieval(redis_client, cache_key)
        if cached_results is not None:
            return cached_results

        inflight_task = _retrieval_inflight.get(cache_key)
        if inflight_task is not None:
            try:
                logger.debug("[CS] Awaiting inflight retrieval: %s", cache_key)
                return await inflight_task
            except Exception:
                # in-flight 失败时降级为重新计算
                pass

        task = asyncio.create_task(_compute_results())
        _retrieval_inflight[cache_key] = task
        try:
            return await task
        finally:
            if _retrieval_inflight.get(cache_key) is task:
                _retrieval_inflight.pop(cache_key, None)

    return await _compute_results()



def _extract_summary(messages: list[dict]) -> str:
    """
    P2-2 提取式摘要：扫描历史，提取商品名、价格、关键问题，拼成简洁摘要。
    用于历史 <= 30 条时替代 LLM 摘要，速度快且不消耗 token。
    确保摘要包含足够上下文，不丢关键信息。
    """
    _product_kws = [
        "血压计", "体温计", "血糖仪", "血氧仪", "口罩", "创可贴", "轮椅", "拐杖",
        "雾化器", "制氧机", "听诊器", "试纸", "绷带", "护理", "康复",
        "欧姆龙", "鱼跃", "体重秤", "针头", "消毒", "纱布", "敷料",
        "退热贴", "额温枪", "耳温枪",
    ]
    _issue_kws = [
        "退款", "换货", "破损", "坏了", "质量问题", "发货",
        "物流", "投诉", "超时", "未收到",
    ]

    product_mentions: list[str] = []
    price_mentions: list[str] = []
    key_issues: list[str] = []
    condensed_lines: list[str] = []

    for msg in messages:
        role_str = msg.get("role", "user")
        if role_str == "system":
            continue
        role_label = "用户" if role_str == "user" else "客服"
        content = (msg.get("content") or "").strip()
        if not content:
            continue

        for kw in _product_kws:
            if kw in content and kw not in product_mentions:
                product_mentions.append(kw)

        prices = re.findall(r"\d+(?:\.\d+)?元", content)
        for p in prices:
            if p not in price_mentions:
                price_mentions.append(p)

        for kw in _issue_kws:
            if kw in content and kw not in key_issues:
                key_issues.append(kw)

        condensed = content[:80].replace("\n", " ")
        condensed_lines.append(f"{role_label}：{condensed}")

    parts: list[str] = []
    if product_mentions:
        parts.append(f"涉及商品：{'、'.join(product_mentions[:6])}")
    if price_mentions:
        parts.append(f"价格信息：{'、'.join(price_mentions[:4])}")
    if key_issues:
        parts.append(f"待处理问题：{'、'.join(key_issues[:4])}")

    header = "【早期对话摘要（提取式）】"
    if parts:
        header += "（" + "；".join(parts) + "）"

    # 保留近8条压缩对话，保证上下文连贯
    context_lines = condensed_lines[-8:] if len(condensed_lines) > 8 else condensed_lines
    context_str = "\n".join(context_lines)

    return f"{header}\n{context_str}" if context_str else header



async def _summarize_conversation(messages: list[dict]) -> str:
    """总结对话历史，避免 context 过长。

    P2-2 改进：
    - 历史 <= 30 条：使用提取式摘要（无需调用 LLM，快速且保留关键信息）
    - 历史 > 30 条：使用 LLM 摘要（更准确，适合长对话）

    Args:
        messages: 要总结的消息列表（role/content 格式）

    Returns:
        对话摘要字符串
    """
    if not messages:
        return ""

    # P2-2 轻量路径：<=30 条用提取式摘要，不调 LLM
    if len(messages) <= 30:
        summary = _extract_summary(messages)
        logger.info(f"[CS] Extractive summary (P2-2): {len(messages)} msgs → {len(summary)} chars")
        return summary

    # LLM 路径：>30 条才用 LLM 摘要
    try:
        dialogue_text = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '客服'}：{m.get('content', '')}"
            for m in messages
        )
        summary_prompt = (
            f"请用100字以内总结以下客服对话的关键信息（用户需求、已处理事项、待解决问题）：\n\n{dialogue_text}"
        )
        result = await call_tool(
            prompt=summary_prompt,
            tool={
                "name": "summarize",
                "description": "输出对话摘要",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "对话摘要（100字以内）"},
                    },
                    "required": ["summary"],
                },
            },
            model=MODEL_DEEPSEEK,
            system="你是一个对话摘要助手，请简洁提炼对话要点。",
            trace_name="conversation_summary",
        )
        summary = result.get("summary", "")
        logger.info(f"[CS] LLM summary: {len(messages)} msgs → {len(summary)} chars")
        return summary
    except Exception as e:
        logger.warning(f"[CS] Conversation summarization failed (graceful): {e}")
        # Fallback: 提取式摘要兜底
        return _extract_summary(messages)


async def load_knowledge_base(pool) -> list[dict]:
    """从数据库加载完整知识库"""
    try:
        knowledge_base = await load_structured_knowledge(pool)
        logger.info(f"Loaded {len(knowledge_base)} knowledge base items")
        return knowledge_base

    except Exception as e:
        logger.error(f"Failed to load knowledge base: {e}")
        return []


async def search_products_with_embedding(query: str, pool) -> list[dict]:
    """使用 Neo4j 向量检索搜索商品。

    强制使用 Neo4j，不做任何降级（pgvector / 内存搜索均已移除）。
    连接失败直接返回空列表并记录 ERROR。
    """
    # ── 生成查询 Embedding ─────────────────────────────────────────────
    query_embedding = None
    try:
        from src.skills.embedding import EmbeddingSkill

        embedding_skill = EmbeddingSkill()
        query_embedding = embedding_skill.embed(query)
        logger.info(f"[CS] Query embedding generated: dim={len(query_embedding)}")
    except Exception as e:
        logger.error(f"[CS] Failed to generate query embedding: {e}", exc_info=True)

    # ── Neo4j 向量检索（唯一路径，不降级） ────────────────────────────
    try:
        from src.db import neo4j as neo4j_db
        from src.skills.neo4j_skill import Neo4jSkill

        driver = neo4j_db.get_driver()
        neo4j_skill = Neo4jSkill(driver=driver)

        if query_embedding:
            results = await neo4j_skill.search_similar(
                query_embedding=query_embedding, top_k=5
            )
        else:
            # 无 embedding 时做关键词检索（仍走 Neo4j fulltext）
            kw_results = await neo4j_skill.keyword_search(
                keywords=query.split(), limit=5
            )
            results = [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "score": r.score,
                }
                for r in kw_results
            ]

        logger.info(
            f"[CS] Neo4j vector search returned {len(results)} results for: {query[:50]}"
        )
        return results

    except Exception as e:
        logger.error(
            f"[CS] Neo4j vector search failed for query '{query[:50]}': {e}",
            exc_info=True,
        )
        return []


async def _search_auto_faq_context(query: str, pool, limit: int = 3) -> list[dict]:
    """FAQ 快速匹配：优先用问题模糊匹配，结果仅作为 LLM 上下文。"""
    if not pool:
        return []

    q = (query or "").strip()
    if not q:
        return []

    try:
        matched = await search_faq_context(pool, q, limit=limit)
        logger.info(f"[CS] FAQ context matched: {len(matched)}")
        return matched[:limit]
    except Exception as e:
        logger.warning(f"[CS] Failed to load auto_faq context (graceful): {e}")
        return []


async def _load_policy_documents_context(pool, limit: int = 5) -> list[dict]:
    """加载售后政策文档，作为回复前补充上下文。"""
    if not pool:
        return []

    try:
        rows = await pool.fetch("SELECT * FROM policy_documents LIMIT $1", limit)
        docs: list[dict] = []
        for row in rows:
            data = dict(row)
            title = (
                data.get("title")
                or data.get("name")
                or data.get("policy_name")
                or "售后政策"
            )
            content = (
                data.get("content")
                or data.get("body")
                or data.get("text")
                or data.get("policy_text")
                or ""
            )
            if not content:
                continue
            docs.append(
                {
                    "title": str(title),
                    "type": str(data.get("policy_type") or data.get("category") or ""),
                    "content": str(content)[:1200],
                }
            )
        logger.info(f"[CS] Policy context loaded: {len(docs)}")
        return docs[:limit]
    except Exception as e:
        logger.warning(f"[CS] Failed to load policy_documents context (graceful): {e}")
        return []


async def _load_review_sentiment_context(
    pool, product_results: list[dict], limit: int = 5
) -> list[dict]:
    """按候选商品补充评价情感信息，辅助回复。"""
    if not pool or not product_results:
        return []

    product_ids = []
    product_names = []
    for item in product_results:
        pid = item.get("id")
        pname = item.get("name")
        if pid:
            product_ids.append(str(pid))
        if pname:
            product_names.append(str(pname))

    matched_rows: list[dict] = []
    seen_keys: set[str] = set()

    def _append_rows(rows) -> None:
        for row in rows:
            data = dict(row)
            key = (
                str(data.get("product_id") or "")
                or str(data.get("spu_id") or "")
                or str(data.get("sku_id") or "")
                or str(data.get("product_name") or data.get("name") or "")
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)

            analysis_fields = {}
            for f in [
                "sentiment",
                "sentiment_summary",
                "review_summary",
                "positive_rate",
                "negative_rate",
                "neutral_rate",
                "avg_rating",
                "rating",
                "total_reviews",
                "review_count",
                "high_freq_issues",
                "highlights",
            ]:
                if data.get(f) is not None:
                    analysis_fields[f] = data.get(f)

            if not analysis_fields:
                continue

            matched_rows.append(
                {
                    "product_id": data.get("product_id")
                    or data.get("spu_id")
                    or data.get("sku_id"),
                    "product_name": data.get("product_name") or data.get("name") or "",
                    "analysis": analysis_fields,
                }
            )

    try:
        if product_ids:
            rows = await pool.fetch(
                """
                SELECT *
                FROM qnh_review_analysis
                WHERE product_id = ANY($1::text[])
                   OR spu_id = ANY($1::text[])
                   OR sku_id = ANY($1::text[])
                LIMIT $2
                """,
                product_ids,
                limit,
            )
            _append_rows(rows)
    except Exception as e:
        logger.warning(f"[CS] Review sentiment lookup by id failed (graceful): {e}")

    if len(matched_rows) < limit and product_names:
        for name in product_names[:5]:
            if len(matched_rows) >= limit:
                break
            try:
                rows = await pool.fetch(
                    """
                    SELECT *
                    FROM qnh_review_analysis
                    WHERE product_name ILIKE $1
                       OR name ILIKE $1
                    LIMIT $2
                    """,
                    f"%{name}%",
                    max(1, limit - len(matched_rows)),
                )
                _append_rows(rows)
            except Exception as e:
                logger.warning(
                    f"[CS] Review sentiment lookup by name failed for '{name}' (graceful): {e}"
                )

    logger.info(f"[CS] Review sentiment context loaded: {len(matched_rows)}")
    return matched_rows[:limit]


async def _log_conversation(
    pool,
    session_id: str = "",
    user_message: str = "",
    intent: str = "",
    ai_response: str = "",
    ai_reply_id: str | None = None,
    sources: list[dict] | None = None,
    confidence: float = 0.0,
) -> None:
    """异步记录对话日志"""
    global _conversation_log_supports_ai_reply_id
    if not pool:
        return

    try:
        # 提取商品IDs用于日志
        product_ids = []
        if sources:
            for source in sources:
                if source.get("id"):
                    product_ids.append(source["id"])

        if _conversation_log_supports_ai_reply_id is not False:
            try:
                await pool.execute(
                    """
                    INSERT INTO cs_conversation_log (
                        session_id, user_message, intent, ai_response, ai_reply_id,
                        matched_kb_ids, matched_product_ids, confidence, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    """,
                    session_id,
                    user_message[:1000],  # 限制长度
                    intent,
                    ai_response[:2000],
                    ai_reply_id,
                    [],  # 不再使用KB IDs
                    product_ids,
                    confidence,
                )
                _conversation_log_supports_ai_reply_id = True
                return
            except Exception:
                _conversation_log_supports_ai_reply_id = False
                logger.debug(
                    "[CS] cs_conversation_log.ai_reply_id unavailable, fallback to legacy insert"
                )

        await pool.execute(
            """
            INSERT INTO cs_conversation_log (
                session_id, user_message, intent, ai_response,
                matched_kb_ids, matched_product_ids, confidence, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """,
            session_id,
            user_message[:1000],  # 限制长度
            intent,
            ai_response[:2000],
            [],  # 不再使用KB IDs
            product_ids,
            confidence,
        )
    except Exception as e:
        logger.warning(f"Failed to log conversation: {e}")


async def _load_business_context(pool) -> dict:
    """并发加载业务数据上下文。"""
    if not pool:
        return {}

    async def _load_orders_and_customers() -> dict:
        with contextlib.suppress(Exception):
            dm = await pool.fetchrow("""
                SELECT COALESCE(SUM(transaction_volume),0)::int AS orders,
                       COALESCE(SUM(deal_amount),0) AS gmv,
                       CASE WHEN SUM(transaction_volume)>0 THEN SUM(deal_amount)/SUM(transaction_volume) ELSE 0 END AS avg_ov,
                       COALESCE(SUM(total_customers),0)::int AS customers,
                       COALESCE(SUM(new_customers),0)::int AS new_cust
                FROM qnh_daily_metrics
                WHERE metric_date >= CURRENT_DATE - INTERVAL '1 day'
            """)
            if dm and dm["orders"] > 0:
                return {
                    "orders": {
                        "count": dm["orders"],
                        "gmv": round(float(dm["gmv"]), 2),
                        "avg_order_value": round(float(dm["avg_ov"]), 2),
                    },
                    "customers": {
                        "total": dm["customers"],
                        "new": dm["new_cust"],
                        "old": dm["customers"] - dm["new_cust"],
                    },
                }
        return {}

    async def _load_exposure() -> dict:
        with contextlib.suppress(Exception):
            exposure = await pool.fetchrow("""
                SELECT COALESCE(AVG(exposure_uv),0)::int AS uv,
                       COALESCE(AVG(exposure_pv),0)::int AS pv
                FROM qnh_daily_metrics
                WHERE metric_date >= CURRENT_DATE - INTERVAL '1 day'
            """)
            if exposure:
                return {"exposure": {"uv": exposure["uv"], "pv": exposure["pv"]}}
        return {}

    async def _load_inventory() -> dict:
        with contextlib.suppress(Exception):
            inv = await pool.fetchrow("""
                SELECT COUNT(*) FILTER (WHERE status='active') AS total,
                       COUNT(*) FILTER (WHERE status='active' AND stock<5) AS low_stock,
                       COUNT(*) FILTER (WHERE status='active' AND stock=0) AS oos
                FROM qnh_products
            """)
            if inv:
                return {
                    "inventory": {
                        "total": inv["total"],
                        "low_stock": inv["low_stock"],
                        "out_of_stock": inv["oos"],
                    }
                }
        return {}

    async def _load_top_products() -> dict:
        with contextlib.suppress(Exception):
            tops = await pool.fetch("""
                SELECT name, monthly_sales, retail_price
                FROM qnh_products
                WHERE status='active' AND monthly_sales>0
                ORDER BY monthly_sales DESC
                LIMIT 5
            """)
            if tops:
                return {
                    "top_products": [
                        {
                            "name": r["name"],
                            "sales": r["monthly_sales"],
                            "price": float(r["retail_price"] or 0),
                        }
                        for r in tops
                    ]
                }
        return {}

    try:
        parts = await asyncio.gather(
            _load_orders_and_customers(),
            _load_inventory(),
            _load_top_products(),
            _load_exposure(),
        )
        business_context: dict = {}
        for part in parts:
            business_context.update(part)
        logger.info(f"Business context loaded: {list(business_context.keys())}")
        return business_context
    except Exception as e:
        logger.warning(f"Failed to load business context: {e}")
        return {}


# 全局知识库缓存
_knowledge_base_cache: list[dict] | None = None
_cache_loaded = False
_business_ctx_cache: dict | None = None
_business_ctx_ts: float = 0
_policy_ctx_cache: list[dict] | None = None
_policy_ctx_ts: float = 0
_conversation_log_supports_ai_reply_id: bool | None = None
_CACHE_TTL = 300  # 5 minutes


def _filter_relevant_knowledge(
    knowledge_base: list[dict], message: str, intent: str, max_items: int = 15
) -> list[dict]:
    """按相关性筛选知识库条目，避免全量注入 prompt。"""
    if not knowledge_base:
        return []

    message_lower = message.lower()
    scored_items: list[tuple[float, dict]] = []

    intent_category_map = {
        "product_inquiry": ["商品", "产品", "功能", "规格"],
        "usage_question": ["使用", "用法", "注意事项"],
        "recommendation": ["推荐", "适用", "人群"],
        "comparison": ["对比", "区别", "差异"],
        "logistics": ["物流", "配送", "快递", "发货"],
        "after_sales": ["售后", "退货", "换货", "退款", "质量"],
        "complaint": ["投诉", "售后", "处理"],
        "medical_advice": ["医疗", "健康", "安全"],
        "greeting": [],
    }

    intent_keywords = intent_category_map.get(intent, [])

    for item in knowledge_base:
        score = 0.0
        question = (item.get("question") or "").lower()
        answer = (item.get("answer") or "").lower()
        category = (item.get("category") or "").lower()
        keywords = item.get("keywords") or []
        item_text = f"{question} {answer} {category}"

        for word in message_lower.split():
            if len(word) >= 2 and word in item_text:
                score += 2.0

        if message_lower in question or question in message_lower:
            score += 5.0

        for kw in keywords:
            if isinstance(kw, str) and kw.lower() in message_lower:
                score += 3.0

        for ik in intent_keywords:
            if ik in category or ik in item_text:
                score += 1.0

        priority = item.get("priority", 0) or 0
        score += priority * 0.5

        scored_items.append((score, item))

    scored_items.sort(key=lambda x: -x[0])
    result = [item for _, item in scored_items[:max_items]]

    logger.info(f"[CS] Knowledge filtered: {len(knowledge_base)} -> {len(result)} items")
    return result


async def _chat_legacy(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
    customer_info: dict[str, Any] | None = None,
    order_context: dict[str, Any] | None = None,
    stream: bool = False,
    token_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """
    原有客服聊天函数（保留用于回退）- 单次LLM调用完成所有任务。

    此函数是 chat() 重构前的原始实现。
    通过设置 CS_USE_PIPELINE=false 可令 chat() 走此路径。

    Args:
        session_id: 会话ID
        message: 用户消息
        pool: 数据库连接池
        conversation_history: 对话历史

    Returns:
        {
            "session_id": str,
            "reply": str,
            "intent": str,
            "sources": list[dict],
            "needs_human": bool
        }
    """
    global _knowledge_base_cache, _cache_loaded

    _t0 = time.time()
    _legacy_received_at = datetime.now(UTC)
    ai_reply_id = new_ai_reply_id()
    context_trace: dict[str, Any] = {
        "has_extension_context": False,
        "has_extension_order_fields": False,
        "extension_order_field_keys": [],
        "direct_logistics_from_extension": False,
    }

    try:
        if is_non_actionable_placeholder(message):
            logger.info("[CS] Placeholder message skip LLM: session=%s message=%s", session_id, message[:80])
            return {
                "session_id": session_id,
                "reply": "亲，已收到这条图片/卡片消息。为便于我准确处理，麻烦再发一下您的具体问题（例如\u201c什么时候到\u201d\u201c怎么使用\u201d）。",
                "ai_reply_id": ai_reply_id,
                "intent": "other",
                "sources": [],
                "needs_human": False,
                "action": {"type": "none"},
                "product_cards": [],
                "context_trace": context_trace,
                "compliance_filtered": False,
            }

        # P0-1: Fast-path 秒回（确定性高频简单消息，无需调 LLM）
        _fast = try_fast_path(
            session_id,
            message,
            ai_reply_id=ai_reply_id,
            conversation_history=conversation_history,
        )
        if _fast is not None:
            if isinstance(_fast, dict):
                _fast.setdefault("context_trace", context_trace)
                _fast.setdefault("compliance_filtered", False)
            _t_fast = time.time()
            logger.info(f"[CS-PERF] Fast-path total: {(_t_fast - _t0)*1000:.0f}ms")
            # Metrics: fast-path hit
            _fast_replied_at = datetime.now(UTC)
            try:
                from src.services.cs_metrics import record_cs_metric as _record_metric
                asyncio.create_task(
                    _record_metric(
                        pool,
                        session_id=session_id,
                        ai_reply_id=ai_reply_id,
                        received_at=_legacy_received_at,
                        replied_at=_fast_replied_at,
                        intent=_fast.get("intent") if isinstance(_fast, dict) else "greeting",
                        confidence=1.0,
                        needs_human=False,
                        was_fast_path=True,
                        compliance_filtered=False,
                    )
                )
            except Exception:
                pass
            return _fast

        # 1. 加载知识库（带缓存）
        if not _cache_loaded:
            _knowledge_base_cache = await load_knowledge_base(pool)
            _cache_loaded = True

        knowledge_base = _knowledge_base_cache or []

        # 1.5 对话摘要：超过6轮（12条）时压缩早期历史
        # 但如果 API 层已经注入了摘要（system message），则跳过
        effective_history = conversation_history or []
        conversation_summary = ""
        has_api_summary = any(
            m.get("role") == "system" and "早期对话摘要" in (m.get("content") or "")
            for m in effective_history
        )
        history_to_summarize: list[dict] = []
        summarize_threshold = 20 if os.getenv("CS_FAST_MODE", "1") == "1" else 12
        if not has_api_summary and effective_history and len(effective_history) > summarize_threshold:
            history_to_summarize = effective_history[:-6]  # 保留最近6条，摘要其余
            effective_history = effective_history[-6:]
        conversation_history = effective_history
        extension_context_str = _build_extension_context_str(
            session_id=session_id,
            customer_info=customer_info,
            order_context=order_context,
        )
        extension_order_fields = _extract_extension_order_fields(
            session_id=session_id,
            order_context=order_context,
        )
        context_trace.update(
            {
                "has_extension_context": bool(extension_context_str),
                "has_extension_order_fields": bool(extension_order_fields),
                "extension_order_field_keys": sorted(extension_order_fields.keys()),
            }
        )

        faq_context = []
        product_results = []
        order_context_str = ""
        customer_profile_str = ""
        intent_result = {}
        sentiment = "neutral"
        emotion_instruction = ""
        quick_intent_hint = quick_intent_guess(message, conversation_history)
        should_load_products = should_run_product_pipeline(quick_intent_hint, conversation_history)
        should_load_order_context = quick_intent_hint in ORDER_INTENTS
        should_load_profile_context = quick_intent_hint in PROFILE_INTENTS
        should_load_policy_context = quick_intent_hint in POLICY_INTENTS
        should_load_prompt_enhancers = quick_intent_hint in PROMPT_ENHANCER_INTENTS
        should_load_memory = should_load_prompt_enhancers or bool(conversation_history and len(conversation_history) >= 4)

        summary_task = None
        faq_task = None
        product_task = None
        order_task = None
        profile_task = None
        intent_task = None
        build_profile_context_str = None

        # 性能优先配置（默认开启）
        fast_mode = os.getenv("CS_FAST_MODE", "1") == "1"
        pipeline_timeout = float(os.getenv("CS_PIPELINE_TIMEOUT", "4.0" if fast_mode else "10.0"))
        enable_intent_llm = os.getenv("CS_INTENT_LLM", "0") == "1" and not fast_mode
        max_reply_tokens = int(os.getenv("CS_REPLY_MAX_TOKENS", "512"))
        critical_wait_timeout = float(os.getenv("CS_CRITICAL_WAIT_TIMEOUT", "3.8" if stream else "4.6"))
        optional_wait_timeout = float(os.getenv("CS_OPTIONAL_WAIT_TIMEOUT", "0.35" if stream else "0.8"))
        stream_decision_timeout = float(os.getenv("CS_STREAM_DECISION_TIMEOUT", "1.2"))

        if history_to_summarize:
            summary_task = asyncio.create_task(
                _summarize_conversation(history_to_summarize)
            )

        # ── 话题管理器（原来串行等待，现在并行） ──────────────────
        from src.db import redis as redis_db

        from .conversation_manager import load_conversation_manager, save_conversation_manager

        _redis = redis_db.get_redis()

        # ── 额外并行任务（原来在第二轮 gather，现在合并到第一轮） ──
        policy_task = None
        few_shot_task = None
        negative_task = None
        cm_task = None
        memory_task = None

        logger.info(
            "[CS] Intent pre-route: quick=%s product=%s order=%s profile=%s policy=%s few_shot=%s memory=%s",
            quick_intent_hint,
            should_load_products,
            should_load_order_context,
            should_load_profile_context,
            should_load_policy_context,
            should_load_prompt_enhancers,
            should_load_memory,
        )

        if pool:
            faq_task = asyncio.create_task(_search_auto_faq_context(message, pool))

            if should_load_products:
                async def _run_product_pipeline() -> list[dict]:
                    cache_key = build_retrieval_cache_key(
                        session_id=session_id,
                        message=message,
                        conversation_history=conversation_history,
                        quick_intent=quick_intent_hint,
                    )
                    return await _run_product_pipeline_with_cache(
                        message=message,
                        pool=pool,
                        pipeline_timeout=pipeline_timeout,
                        redis_client=_redis,
                        cache_key=cache_key,
                    )

                product_task = asyncio.create_task(_run_product_pipeline())

            try:
                from .order_context import build_order_context_str, has_order_mention

                should_lookup_order = should_load_order_context
                if has_order_mention(message):
                    should_lookup_order = True

                if should_lookup_order:
                    order_task = asyncio.create_task(
                        build_order_context_str(
                            pool=pool,
                            message=message,
                        )
                    )
            except Exception as e:
                logger.debug(f"[CS] Order context load failed (non-critical): {e}")

            try:
                from .customer_profile import (
                    build_profile_context_str,
                    get_customer_profile,
                )

                if should_load_profile_context:
                    profile_task = asyncio.create_task(
                        get_customer_profile(pool, session_id=session_id)
                    )
            except Exception as e:
                logger.debug(f"[CS] Customer profile load failed (non-critical): {e}")

            # ── 原第二轮 gather 的任务，提前启动 ──────────────────
            async def _safe_load_policy():
                global _policy_ctx_cache, _policy_ctx_ts
                if _policy_ctx_cache is not None and (time.time() - _policy_ctx_ts) < _CACHE_TTL:
                    return _policy_ctx_cache
                try:
                    result = await asyncio.wait_for(_load_policy_documents_context(pool), timeout=2.0)
                    _policy_ctx_cache = result
                    _policy_ctx_ts = time.time()
                    return result
                except Exception:
                    return _policy_ctx_cache or []

            async def _safe_load_dynamic_few_shots():
                try:
                    row = await asyncio.wait_for(
                        pool.fetchrow("SELECT value FROM system_config WHERE key = 'cs_few_shot_examples'"),
                        timeout=1.0,
                    )
                    if row:
                        return json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                except Exception:
                    pass
                return {}

            async def _safe_load_negative_examples():
                try:
                    row = await asyncio.wait_for(
                        pool.fetchrow("SELECT value FROM system_config WHERE key = 'cs_negative_examples'"),
                        timeout=1.0,
                    )
                    if row:
                        return json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                except Exception:
                    pass
                return {}

            if should_load_policy_context:
                policy_task = asyncio.create_task(_safe_load_policy())
            if should_load_prompt_enhancers:
                few_shot_task = asyncio.create_task(_safe_load_dynamic_few_shots())
                negative_task = asyncio.create_task(_safe_load_negative_examples())

            # ── 记忆上下文（原来串行等待，现在并行） ──────────────
            async def _safe_load_memory():
                try:
                    from src.agents.action_tracker import format_memory_context
                    return await asyncio.wait_for(
                        format_memory_context(
                            pool=pool,
                            agent_name="customer_service",
                            context_type="inquiry",
                        ),
                        timeout=2.0,
                    )
                except Exception:
                    return ""

            if should_load_memory:
                memory_task = asyncio.create_task(_safe_load_memory())

        if _redis:
            cm_task = asyncio.create_task(load_conversation_manager(_redis, session_id))

        if enable_intent_llm:
            try:
                from src.agents.customer_service.tracker import ConversationTracker

                _tracker = ConversationTracker()
                intent_task = asyncio.create_task(_tracker.classify_intent_llm(message))
            except Exception:
                intent_task = None

        _t_tasks_start = time.time()
        logger.info(f"[CS-PERF] Task setup took {(_t_tasks_start - _t0)*1000:.0f}ms")

        tracked_tasks = [
            ("summary", summary_task),
            ("faq", faq_task),
            ("product", product_task),
            ("order", order_task),
            ("profile", profile_task),
            ("intent", intent_task),
            ("policy", policy_task),
            ("few_shot", few_shot_task),
            ("negative", negative_task),
            ("conv_mgr", cm_task),
            ("memory", memory_task),
        ]
        task_labels = {id(task): label for label, task in tracked_tasks if task is not None}
        critical_task_labels = {"faq", "product", "order", "profile", "policy", "conv_mgr"}
        critical_tasks = [
            task
            for label, task in tracked_tasks
            if task is not None and label in critical_task_labels
        ]
        optional_tasks = [
            task
            for label, task in tracked_tasks
            if task is not None and label not in critical_task_labels
        ]

        if critical_tasks:
            _, critical_pending = await asyncio.wait(
                critical_tasks,
                timeout=critical_wait_timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            if critical_pending:
                logger.warning(
                    "[CS] Critical tasks timeout at %.2fs, pending=%d",
                    critical_wait_timeout,
                    len(critical_pending),
                )

        if optional_tasks and optional_wait_timeout > 0:
            _, optional_pending = await asyncio.wait(
                optional_tasks,
                timeout=optional_wait_timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            if optional_pending:
                logger.debug(
                    "[CS] Optional tasks timeout at %.2fs, pending=%d",
                    optional_wait_timeout,
                    len(optional_pending),
                )

        _t_tasks_done = time.time()
        # 逐个任务报告耗时和状态
        _task_perf = []
        for _, task in tracked_tasks:
            if task is None:
                continue
            label = task_labels.get(id(task), "unknown")
            status = "done" if task.done() and not task.cancelled() else ("cancelled" if task.cancelled() else "pending")
            if status == "done":
                try:
                    r = task.result()
                    if isinstance(r, BaseException):
                        status = f"error:{type(r).__name__}"
                except Exception as e:
                    status = f"error:{type(e).__name__}"
            _task_perf.append(f"{label}={status}")
        logger.info(
            f"[CS-PERF] All tasks waited {(_t_tasks_done - _t_tasks_start)*1000:.0f}ms | "
            f"Tasks: {', '.join(_task_perf)}"
        )

        def _consume_task_result(task, default=None):
            if not task:
                return default
            if not task.done():
                return default
            if task.cancelled():
                return default
            try:
                result = task.result()
                if isinstance(result, BaseException):
                    return default
                return result
            except Exception:
                return default

        if summary_task:
            summary_result = _consume_task_result(summary_task, "")
            if summary_result:
                conversation_summary = summary_result
                logger.info("[CS] Long conversation compressed: kept 6 msgs + summary")

        if faq_task:
            faq_context = _consume_task_result(faq_task, [])

        if product_task:
            product_results = _consume_task_result(product_task, [])

        if order_task:
            order_context_str = _consume_task_result(order_task, "")

        if profile_task:
            profile_result = _consume_task_result(profile_task)
            if profile_result is not None and build_profile_context_str:
                try:
                    customer_profile_str = build_profile_context_str(profile_result)
                except Exception as e:
                    logger.debug(f"[CS] Customer profile formatting failed (non-critical): {e}")

        if intent_task:
            intent_task_result = _consume_task_result(intent_task, {})
            if intent_task_result:
                intent_result = intent_task_result
                sentiment = intent_result.get("sentiment", "neutral")
                if sentiment == "angry":
                    emotion_instruction = (
                        "\n\n⚠️ 用户情绪激动，请特别注意：先共情安抚，再解决问题。"
                        "避免机械回复。必要时主动提供补偿方案或转人工。"
                    )
                elif sentiment == "frustrated":
                    emotion_instruction = (
                        "\n\n注意：用户有些不耐烦，请简洁高效回复，快速给出解决方案。"
                    )

        relevant_knowledge = knowledge_base
        if knowledge_base and len(knowledge_base) > 20:
            relevant_knowledge = _filter_relevant_knowledge(
                knowledge_base, message, intent_result.get("intent", "")
            )

        if pool and should_load_products and not product_results:
            # Fallback：降级到纯向量检索
            product_results = await search_products_with_embedding(message, pool)

        # 2.6 售后政策 + 动态 few-shot（已在第一轮并行加载，直接取结果）
        policy_context = _consume_task_result(policy_task, [])
        dynamic_few_shots = _consume_task_result(few_shot_task, {})
        negative_examples = _consume_task_result(negative_task, {})

        # review_sentiment 依赖 product_results，只能在此处加载（唯一的串行例外）
        review_sentiment_context = []
        if pool and product_results:
            try:
                review_sentiment_context = await asyncio.wait_for(
                    _load_review_sentiment_context(pool, product_results), timeout=2.0
                )
            except Exception:
                review_sentiment_context = []

        # ── 话题管理器（已在第一轮并行加载） ──────────────────────
        cm = _consume_task_result(cm_task)
        if cm is None and cm_task and not cm_task.cancelled() and not cm_task.done():
            try:
                cm = await asyncio.wait_for(
                    cm_task,
                    timeout=0.15 if stream else 0.4,
                )
            except Exception:
                cm = None
        if cm is None:
            from .conversation_manager import load_conversation_manager
            cm = await load_conversation_manager(_redis, session_id)
        current_topic = cm.resolve_topic(message, conversation_history)
        topic_context = cm.build_topic_context(current_topic)

        # 把商品搜索结果关联到当前话题
        if product_results:
            for p in product_results[:3]:
                cm.add_product_to_topic(p.get("name", ""))

        # 异步保存话题状态（不阻塞）
        asyncio.create_task(save_conversation_manager(_redis, session_id, cm))

        logger.info(
            f"[CM] Topic resolved: name={current_topic.name}, "
            f"category={current_topic.category}, "
            f"ephemeral={current_topic.ephemeral}, "
            f"stack_depth={len(cm.topic_stack)}"
        )

        pending_tasks = [
            task
            for _, task in tracked_tasks
            if task is not None and not task.done()
        ]
        if pending_tasks:
            for task in pending_tasks:
                task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # ── 快速意图预判（用于上下文路由，不依赖 LLM） ──────────────
        quick_intent = quick_intent_hint
        # 如果 intent_result 有 LLM 结果就用 LLM 的，否则用快速预判
        current_intent = intent_result.get("intent") if intent_result else quick_intent
        if current_intent == "other":
            current_intent = quick_intent  # LLM 也不确定时用规则兜底

        # 话题管理器覆盖意图：如果话题是商品类但 intent 判成了 greeting/other，纠正
        if current_topic.category == "product" and current_intent in ("greeting", "other"):
            logger.info(f"[CM] Topic override: intent {current_intent} → product_inquiry (topic={current_topic.name})")
            current_intent = "product_inquiry"
        elif current_topic.category == "after_sales" and current_intent in ("greeting", "other"):
            current_intent = "after_sales"
        elif current_topic.category == "complaint" and current_intent in ("greeting", "other"):
            current_intent = "complaint"

        logger.info(f"[CS] Intent routing: quick={quick_intent}, llm={intent_result.get('intent', 'N/A')}, topic={current_topic.name}, final={current_intent}")

        # 如果扩展已经提供了订单配送上下文，物流类问题优先走确定性回复，避免反问订单号。
        if current_intent == "logistics":
            direct_logistics_reply = _build_logistics_reply_from_extension_context(
                message=message,
                session_id=session_id,
                order_context=order_context,
            )
            if direct_logistics_reply:
                context_trace["direct_logistics_from_extension"] = True
                if pool:
                    asyncio.create_task(
                        _log_conversation(
                            pool=pool,
                            session_id=session_id,
                            user_message=message,
                            intent=current_intent,
                            ai_response=direct_logistics_reply,
                            ai_reply_id=ai_reply_id,
                            sources=product_results,
                            confidence=0.92,
                        )
                    )
                return {
                    "session_id": session_id,
                    "reply": direct_logistics_reply,
                    "ai_reply_id": ai_reply_id,
                    "intent": current_intent,
                    "sources": product_results,
                    "needs_human": False,
                    "action": {"type": "check_logistics"},
                    "product_cards": [],
                    "context_trace": context_trace,
                }

        # 3. 构建优化版系统提示词
        try:
            from ..prompts.customer_service import AFTER_SALES_SCRIPTS
            from ..prompts.customer_service_optimized import (
                SCENARIO_CONTEXTS,
                build_optimized_system_prompt,
                build_optimized_user_message_with_context,
            )

            system_prompt = build_optimized_system_prompt(
                knowledge_base=relevant_knowledge,
                after_sales_scripts=AFTER_SALES_SCRIPTS,
                customer_profile_str=customer_profile_str if customer_profile_str else None,
                dynamic_few_shots=dynamic_few_shots if dynamic_few_shots else None,
                negative_examples=negative_examples if negative_examples else None,
            )

            # 场景指引注入到 system prompt（按当前意图）
            scenario_hint = SCENARIO_CONTEXTS.get(current_intent, "")
            if scenario_hint:
                system_prompt += f"\n\n# 当前场景指引\n{scenario_hint}"


            # P3-1: 话术模板注入（按意图注入参考素材，LLM 自由组织语言）
            try:
                from .templates import get_templates_for_intent

                template_hint = get_templates_for_intent(current_intent)
                if template_hint:
                    system_prompt += f"\n\n{template_hint}"
            except Exception as _tmpl_err:
                logger.debug(f"[CS] Template injection skipped: {_tmpl_err}")

            # 话题上下文注入（最高优先级的上下文信号）
            if topic_context:
                system_prompt += f"\n\n# 当前对话话题\n{topic_context}"

            use_optimized = True
            logger.info("Using optimized prompts for better quality")
        except ImportError:
            # Fallback to original prompts
            from ..prompts.customer_service import (
                AFTER_SALES_SCRIPTS,
                build_system_prompt,
                build_user_message_with_context,
            )

            system_prompt = build_system_prompt(
                knowledge_base=relevant_knowledge, after_sales_scripts=AFTER_SALES_SCRIPTS
            )
            use_optimized = False
            logger.warning("Using fallback prompts")

        # 3.5 情感指令 + 记忆上下文 + 多轮追踪
        if emotion_instruction:
            system_prompt = f"{system_prompt}{emotion_instruction}"

        # 记忆上下文（已在第一轮并行加载）
        memory_ctx = _consume_task_result(memory_task, "")

        # 多轮追踪（纯 CPU 计算，同步即可）
        conversation_context = ""
        try:
            from .tracker import track_conversation
            _track_result = track_conversation(
                conversation_history=conversation_history or [],
                user_intent=intent_result.get("intent", ""),
                user_message=message,
            )
            conversation_context = _track_result.get("context_summary", "")
        except Exception:
            pass

        if memory_ctx:
            system_prompt = f"{system_prompt}\n\n{memory_ctx}"

        # 5. 构建多轮对话 messages（让 LLM 真正理解对话上下文）
        #
        # 之前：把对话历史当文本塞进一条 user message → LLM 不理解追问关系
        # 现在：用真正的 messages 数组，LLM 能天然理解多轮对话
        #

        # 5.1 构建补充上下文（作为最终 user message 的一部分）
        if use_optimized:
            context_prompt = build_optimized_user_message_with_context(
                user_message=message,
                conversation_history=None,  # 不再把历史塞这里
                product_results=product_results,
                conversation_context=conversation_context,
                business_context=None,  # 永远不向买家暴露经营数据
                dynamic_few_shots=dynamic_few_shots if dynamic_few_shots else None,
                intent=current_intent,
            )
        else:
            from ..prompts.customer_service import build_user_message_with_context

            context_prompt = build_user_message_with_context(
                user_message=message,
                conversation_history=None,  # 不再把历史塞这里
                product_results=product_results,
                conversation_context=conversation_context,
            )

        # 5.2 上下文预算器：按意图选择性注入上下文（不再全量塞入）
        # 判断历史中是否有商品话题（用于上下文预算器保持商品上下文不丢）
        _has_product_history = bool(product_results)
        if not _has_product_history and conversation_history:
            _product_signals = ["推荐", "血压", "体温", "血糖", "口罩", "型号", "价格", "库存"]
            for _h_msg in conversation_history[-6:]:
                if any(kw in (_h_msg.get("content") or "") for kw in _product_signals):
                    _has_product_history = True
                    break
        allowed_contexts = _select_context_by_intent(current_intent, _has_product_history)
        logger.info(f"[CS] Context budget for intent '{current_intent}': {allowed_contexts}")

        extra_sections = []
        if extension_context_str:
            extra_sections.append(extension_context_str)
        if "profile" in allowed_contexts and customer_profile_str:
            extra_sections.append(customer_profile_str)
        if "order" in allowed_contexts and order_context_str:
            extra_sections.append(order_context_str)
        if "faq" in allowed_contexts and faq_context:
            extra_sections.append(
                "【FAQ参考】\n"
                + json.dumps(faq_context[:3], ensure_ascii=False)
            )
        if "policy" in allowed_contexts and policy_context:
            extra_sections.append(
                "【售后政策】\n"
                + json.dumps(policy_context[:3], ensure_ascii=False)
            )
        if "products" in allowed_contexts and review_sentiment_context:
            extra_sections.append(
                "【商品评价】\n"
                + json.dumps(review_sentiment_context[:3], ensure_ascii=False)
            )
        # 注意：business_context（店铺经营数据）永远不注入客服回复
        if extra_sections:
            context_prompt = f"{context_prompt}\n\n" + "\n\n".join(extra_sections)

        # 5.3 构建真正的多轮 messages 数组
        llm_messages: list[dict] = []

        # 对话摘要（如果有）
        if conversation_summary:
            llm_messages.append({
                "role": "user",
                "content": f"[早期对话摘要] {conversation_summary}",
            })
            llm_messages.append({
                "role": "assistant",
                "content": "好的，我已了解之前的对话内容。",
            })

        # 真正的对话历史（user/assistant 交替）
        if conversation_history:
            prev_role = None
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not content:
                    continue
                if role == "system":
                    # system 消息（如对话摘要）已经通过 conversation_summary 处理，跳过
                    continue
                # 确保 user/assistant 严格交替（某些 LLM 要求）
                # 如果连续两条同 role，合并到前一条
                if role == prev_role and llm_messages:
                    llm_messages[-1]["content"] += f"\n{content}"
                else:
                    llm_messages.append({"role": role, "content": content})
                prev_role = role

        # 当前用户消息 + 所有上下文
        # 如果最后一条已经是 user（可能 history 包含了当前消息），合并
        if llm_messages and llm_messages[-1]["role"] == "user":
            llm_messages[-1]["content"] = context_prompt  # 用带上下文的版本替换
        else:
            llm_messages.append({"role": "user", "content": context_prompt})

        # 用于 LLM 调用的最终 prompt
        user_message_with_context = llm_messages
        vision_prompt_text = _build_vision_prompt_text(llm_messages, context_prompt)

        # 调试日志：打印传给 LLM 的 messages 结构（只打角色和前50字）
        _msg_debug = [f"{m['role']}: {(m.get('content',''))[:50]}..." for m in llm_messages]
        logger.info(f"[CS-DEBUG] LLM messages ({len(llm_messages)} turns): {_msg_debug}")

        _t_pre_llm = time.time()
        logger.info(f"[CS-PERF] Pre-LLM pipeline took {(_t_pre_llm - _t0)*1000:.0f}ms")

        # 5. 调用 LLM 生成回复（tool_choice 模式，质量优先）
        tool_schema = {
            "name": "output_reply",
            "description": "输出客服回复",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reply_text": {"type": "string", "maxLength": 200},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "requires_human_review": {"type": "boolean", "description": "是否需要转人工"},
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
                        "description": "AI 建议执行的操作（可选）",
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
                                "description": "操作类型",
                            },
                            "order_id": {"type": "string", "description": "相关订单号"},
                            "reason": {"type": "string", "description": "操作原因"},
                            "amount": {"type": "number", "description": "退款金额（如适用）"},
                            "urgency": {"type": "string", "enum": ["normal", "urgent"]},
                        },
                        "required": ["type"],
                    },
                },
                "required": ["reply_text", "confidence", "requires_human_review"],
            },
        }

        async def _extract_stream_structured_result(stream_reply_text: str) -> dict:
            """流式文本生成后补一轮轻量结构化判定，避免丢失转人工/动作建议。"""
            decision_tool_schema = {
                "name": "stream_decision",
                "description": "基于客服回复输出结构化决策字段",
                "input_schema": {
                    "type": "object",
                    "properties": {
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
                            "description": "AI 建议执行的操作（可选）",
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
                    "required": ["confidence", "requires_human_review", "intent", "action"],
                },
            }
            decision_prompt = (
                "请根据用户问题与当前客服回复，输出结构化决策字段。\n"
                "要求：\n"
                "1) 不要改写回复文本，不要输出解释。\n"
                "2) 若无需操作，action.type 必须为 none。\n"
                f"用户消息：{message}\n"
                f"快速意图：{current_intent}\n"
                f"用户情绪：{sentiment}\n"
                f"客服回复：{stream_reply_text}"
            )
            return await call_tool(
                prompt=decision_prompt,
                tool=decision_tool_schema,
                model=MODEL_DEEPSEEK,
                max_tokens=256,
                trace_name="customer_service_stream_decision",
            )

        async def _run_stream_structured_result(stream_reply_text: str) -> dict:
            if not stream_reply_text or stream_decision_timeout <= 0:
                return {}
            try:
                return await asyncio.wait_for(
                    _extract_stream_structured_result(stream_reply_text),
                    timeout=stream_decision_timeout,
                )
            except TimeoutError:
                logger.warning(
                    "[CS] Stream structured decision timeout at %.2fs, fallback to heuristic",
                    stream_decision_timeout,
                )
            except Exception as decision_err:
                logger.warning(
                    "[CS] Stream structured decision failed, fallback to heuristic: %s",
                    decision_err,
                )
            return {}

        stream_ready = bool(stream and token_callback and not images)
        stream_structured_result: dict = {}
        result: dict = {}
        reply_text = ""
        confidence = 0.8
        needs_human = current_intent in {"complaint"}
        intent = current_intent
        suggested_action = {"type": "none"}

        if stream_ready:
            raw_stream_text = ""
            emitted_stream_text = ""

            async def _emit_stream_delta(force_flush: bool = False) -> None:
                nonlocal emitted_stream_text
                if not raw_stream_text:
                    return

                if force_flush or _COMPLIANCE_STREAM_HOLDBACK_CHARS <= 0:
                    candidate_raw_text = raw_stream_text
                else:
                    if len(raw_stream_text) <= _COMPLIANCE_STREAM_HOLDBACK_CHARS:
                        return
                    candidate_raw_text = raw_stream_text[:-_COMPLIANCE_STREAM_HOLDBACK_CHARS]

                candidate_processed_text = _postprocess_reply_text(candidate_raw_text)
                if len(candidate_processed_text) <= len(emitted_stream_text):
                    return

                delta = candidate_processed_text[len(emitted_stream_text):]
                if not delta:
                    return

                emitted_stream_text += delta
                try:
                    await token_callback(delta)
                except Exception as cb_err:
                    logger.debug("[CS] Stream token callback failed: %s", cb_err)

            try:
                async for chunk in call_chat_stream(
                    prompt=user_message_with_context,
                    model=MODEL_SONNET,
                    max_tokens=max_reply_tokens,
                    system=system_prompt,
                    trace_name="customer_service_chat_stream",
                ):
                    if not chunk:
                        continue
                    raw_stream_text += chunk
                    await _emit_stream_delta(force_flush=False)
                    if len(emitted_stream_text) >= _MAX_REPLY_TEXT_LEN:
                        break

                await _emit_stream_delta(force_flush=True)

                # 保证 done.reply 与已发 token 一致
                final_processed_reply = _postprocess_reply_text(raw_stream_text)
                if len(final_processed_reply) > len(emitted_stream_text):
                    final_delta = final_processed_reply[len(emitted_stream_text):]
                    if final_delta:
                        emitted_stream_text += final_delta
                        try:
                            await token_callback(final_delta)
                        except Exception as cb_err:
                            logger.debug("[CS] Stream final callback failed: %s", cb_err)
                reply_text = emitted_stream_text or final_processed_reply
                if reply_text:
                    intent = current_intent
                    needs_human = current_intent in {"complaint"} or sentiment == "angry"
                    stream_structured_result = await _run_stream_structured_result(reply_text)
                else:
                    stream_ready = False
            except Exception as e:
                if raw_stream_text:
                    final_processed_reply = _postprocess_reply_text(raw_stream_text)
                    if len(final_processed_reply) > len(emitted_stream_text):
                        final_delta = final_processed_reply[len(emitted_stream_text):]
                        if final_delta:
                            emitted_stream_text += final_delta
                            try:
                                await token_callback(final_delta)
                            except Exception as cb_err:
                                logger.debug("[CS] Stream exception callback failed: %s", cb_err)
                    reply_text = emitted_stream_text or final_processed_reply
                    intent = current_intent
                    needs_human = current_intent in {"complaint"} or sentiment == "angry"
                    stream_structured_result = await _run_stream_structured_result(reply_text)
                    logger.warning("[CS] Stream interrupted, using partial reply: %s", e)
                else:
                    logger.warning("[CS] Stream generation failed, fallback to tool mode: %s", e)
                    stream_ready = False

        if not stream_ready:
            if images and len(images) > 0:
                result = await call_vision(
                    text=vision_prompt_text,
                    images=images,
                    tool=tool_schema,
                    model="google/gemini-2.0-flash-001",
                    max_tokens=max_reply_tokens,
                    system=system_prompt
                    + "\n\n当用户上传图片时：仔细观察图片内容，如果是商品损坏照片 → 确认质量问题并给退换方案；如果是商品照片 → 识别商品并提供信息",
                    trace_name="customer_service_vision_chat",
                )
            else:
                result = await call_tool(
                    prompt=user_message_with_context,
                    tool=tool_schema,
                    model=MODEL_SONNET,
                    max_tokens=max_reply_tokens,
                    system=system_prompt,
                    trace_name="customer_service_chat",
                )

        _t_post_llm = time.time()
        logger.info(f"[CS-PERF] LLM call took {(_t_post_llm - _t_pre_llm)*1000:.0f}ms | Total so far: {(_t_post_llm - _t0)*1000:.0f}ms")

        # 6. 提取结果
        if not reply_text:
            reply_text = result.get("reply_text", "亲，您的问题我已记录，稍后为您回复~")
            confidence = result.get("confidence", 0.8)
            needs_human = result.get("requires_human_review", False)
            intent = result.get("intent", "other")
            suggested_action = result.get("action", {"type": "none"})
        elif stream_structured_result:
            stream_confidence = stream_structured_result.get("confidence")
            if isinstance(stream_confidence, (int, float)):
                confidence = max(0.0, min(1.0, float(stream_confidence)))

            needs_human = bool(stream_structured_result.get("requires_human_review", needs_human))

            stream_intent = stream_structured_result.get("intent")
            if isinstance(stream_intent, str) and stream_intent.strip():
                intent = stream_intent.strip()

            stream_action = stream_structured_result.get("action")
            if isinstance(stream_action, dict) and stream_action:
                suggested_action = stream_action

        # P1-1: 合规过滤层（额外安全层）
        reply_text = _postprocess_reply_text(reply_text)


        # P2-1: 商品卡片富媒体回复
        product_cards: list[dict] = []
        if product_results:
            for _p in product_results[:3]:
                _card = {
                    "name": _p.get("name", ""),
                    "price": _p.get("price") or _p.get("retail_price"),
                    "image_url": _p.get("image_url") or _p.get("image"),
                    "description": (_p.get("description") or "")[:200],
                }
                if _card["name"]:
                    product_cards.append(_card)

        # 如果 action 要求转人工，自动设置 needs_human
        if isinstance(suggested_action, dict) and suggested_action.get("type") == "transfer_human":
            needs_human = True

        # 7. 异步记录日志（不阻塞响应）
        if pool:
            asyncio.create_task(
                _log_conversation(
                    pool=pool,
                    session_id=session_id,
                    user_message=message,
                    intent=intent,
                    ai_response=reply_text,
                    ai_reply_id=ai_reply_id,
                    sources=product_results,
                    confidence=confidence,
                )
            )

            context = {
                "conversation_history": conversation_history,
                "product_results": product_results,
                "intent": intent,
                "confidence": confidence,
                "needs_human": needs_human,
            }

            # 8. 异步评分+进化（可选能力，不得影响主回复）
            try:
                from .auto_evolve import after_reply_hook
                from .evaluator import evaluate_and_store
            except Exception as import_err:
                logger.warning(
                    "[CS] Optional evaluator/auto_evolve unavailable, skip evolve hook: %s",
                    import_err,
                )
            else:
                async def _evaluate_and_evolve():
                    """先评分存储，再触发进化（共享评分结果，不重复调用 LLM）"""
                    try:
                        await evaluate_and_store(
                            pool=pool,
                            session_id=session_id,
                            user_message=message,
                            ai_reply=reply_text,
                            conversation_history=conversation_history,
                            product_results=product_results,
                        )
                        await after_reply_hook(
                            session_id=session_id,
                            user_msg=message,
                            reply=reply_text,
                            context=context,
                            pool=pool,
                            skip_scoring=True,
                        )
                    except Exception as evolve_err:
                        logger.debug("CS evaluate/evolve failed (non-critical): %s", evolve_err)

                asyncio.create_task(_evaluate_and_evolve())

            # 异步记录客服决策（不阻塞主流程）
            async def _record_cs_action(
                pool, session_id, message, reply_text, intent, sentiment
            ):
                try:
                    from src.agents.action_tracker import record_action

                    await record_action(
                        pool=pool,
                        agent_name="customer_service",
                        action_type=f"cs_{intent}",
                        description=f"用户:{message[:100]}... → 回复:{reply_text[:100]}...",
                        parameters={
                            "session_id": session_id,
                            "intent": intent,
                            "sentiment": sentiment,
                            "reply_length": len(reply_text),
                        },
                        baseline_metrics={"intent": intent, "sentiment": sentiment},
                    )
                except Exception as e:
                    logger.debug(f"CS action recording failed (non-critical): {e}")

            asyncio.create_task(
                _record_cs_action(
                    pool, session_id, message, reply_text, intent, sentiment
                )
            )

        # 8. 返回结果
        _t_end = time.time()
        logger.info(
            f"[CS-PERF] ===== Total: {(_t_end - _t0)*1000:.0f}ms ===== "
            f"(setup={(_t_tasks_start - _t0)*1000:.0f}ms, "
            f"tasks={(_t_tasks_done - _t_tasks_start)*1000:.0f}ms, "
            f"pre-llm={(_t_pre_llm - _t_tasks_done)*1000:.0f}ms, "
            f"llm={(_t_post_llm - _t_pre_llm)*1000:.0f}ms, "
            f"post-llm={(_t_end - _t_post_llm)*1000:.0f}ms) "
            f"| reply_len={len(reply_text)}"
        )
        # Metrics: main LLM path
        _legacy_replied_at = datetime.now(UTC)

        # ── P1-1 合规过滤（硬拦截 + 软替换） ───────────────────────────────
        from src.agents.customer_service.compliance import check as _compliance_check
        _compliance_result = _compliance_check(reply_text, session_id=session_id)
        if _compliance_result.needs_human:
            needs_human = True
        reply_text = _compliance_result.text

        _compliance_was_filtered = _compliance_result.was_filtered
        try:
            from src.services.cs_metrics import record_cs_metric as _record_metric
            asyncio.create_task(
                _record_metric(
                    pool,
                    session_id=session_id,
                    ai_reply_id=ai_reply_id,
                    received_at=_legacy_received_at,
                    replied_at=_legacy_replied_at,
                    intent=intent,
                    confidence=confidence,
                    needs_human=needs_human,
                    was_fast_path=False,
                    compliance_filtered=_compliance_was_filtered,
                )
            )
        except Exception:
            pass
        return {
            "session_id": session_id,
            "reply": reply_text,
            "ai_reply_id": ai_reply_id,
            "intent": intent,
            "sources": product_results,
            "needs_human": needs_human,
            "action": suggested_action,
            "product_cards": product_cards,  # P2-1
            "context_trace": context_trace,
            "compliance_filtered": _compliance_was_filtered,
        }

    except Exception as e:
        err_text = str(e)
        err_lower = err_text.lower()
        if "timeout" in err_lower:
            error_code = "llm_timeout"
        elif "rate" in err_lower or "429" in err_lower:
            error_code = "llm_rate_limit"
        elif "auth" in err_lower or "key" in err_lower or "401" in err_lower:
            error_code = "llm_auth_error"
        elif "tool call" in err_lower or "tool arguments" in err_lower:
            error_code = "llm_tool_output_error"
        else:
            error_code = "llm_unknown_error"

        error_detail = err_text[:500]
        logger.error(f"Chat function failed [{error_code}]: {e}", exc_info=True)
        return {
            "session_id": session_id,
            "reply": f"亲，系统繁忙，请稍后重试或联系人工客服🙏（错误码: {error_code}）",
            "ai_reply_id": ai_reply_id,
            "intent": "other",
            "sources": [],
            "needs_human": True,
            "error_code": error_code,
            "error_detail": error_detail,
            "context_trace": context_trace,
            "compliance_filtered": False,
        }


async def _chat_via_pipeline(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
    customer_info: dict[str, Any] | None = None,
    order_context: dict[str, Any] | None = None,
    stream: bool = False,
    token_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """通过 LangGraph 5 步管线执行客服回复。"""
    from .pipeline import build_cs_pipeline

    _pipeline_received_at = datetime.now(UTC)
    ai_reply_id = new_ai_reply_id()
    context_trace: dict[str, Any] = {
        "has_extension_context": bool(
            _build_extension_context_str(
                session_id=session_id,
                customer_info=customer_info,
                order_context=order_context,
            )
        ),
        "has_extension_order_fields": bool(
            _extract_extension_order_fields(session_id=session_id, order_context=order_context)
        ),
        "extension_order_field_keys": sorted(
            _extract_extension_order_fields(session_id=session_id, order_context=order_context).keys()
        ),
        "direct_logistics_from_extension": False,
    }

    # 当前 pipeline 聚焦文本问答。流式/视觉场景先走 legacy，保证兼容。
    if stream or (images and len(images) > 0):
        logger.info("[CS] Pipeline fallback to legacy for stream/images session=%s", session_id)
        return await _chat_legacy(
            session_id=session_id,
            message=message,
            pool=pool,
            conversation_history=conversation_history,
            images=images,
            customer_info=customer_info,
            order_context=order_context,
            stream=stream,
            token_callback=token_callback,
        )

    try:
        pipeline = build_cs_pipeline()
        initial_state = {
            "user_message": message,
            "session_id": session_id,
            "pool": pool,
            "conversation_history": conversation_history or [],
            "images": images or [],
            "customer_info": customer_info or {},
            "order_context": order_context or {},
            "stream": stream,
            "token_callback": token_callback,
            "ai_reply_id": ai_reply_id,
        }

        result_state = await pipeline.ainvoke(initial_state)

        reply_text = result_state.get("reply") or "亲，系统繁忙，请稍后重试或联系人工客服🙏"
        intent = result_state.get("intent") or "other"
        sources = result_state.get("reranked_results") or result_state.get("search_results") or []
        needs_human = bool(result_state.get("needs_human", intent in {"complaint"}))
        suggested_action = result_state.get("suggested_action") or {"type": "none"}
        product_cards = result_state.get("product_cards") or []

        # ── 置信度兜底：基于 intent_confidence 决定是否强制转人工 ──────────
        conf_low = float(os.environ.get("CS_CONFIDENCE_LOW", "0.4"))
        conf_med = float(os.environ.get("CS_CONFIDENCE_MED", "0.6"))
        intent_confidence = float(result_state.get("intent_confidence", 1.0) or 1.0)

        if intent_confidence < conf_low:
            logger.warning(
                "[CS-CONFIDENCE] LOW session=%s confidence=%.3f intent=%s → force transfer",
                session_id,
                intent_confidence,
                intent,
            )
            needs_human = True
            reply_text = "亲，您的问题我需要转接专业客服为您解答，请稍等一下哦~ 🙏"
            suggested_action = {"type": "transfer_human", "reason": "low_confidence"}
        elif intent_confidence < conf_med:
            logger.warning(
                "[CS-CONFIDENCE] MED session=%s confidence=%.3f intent=%s → mark human (AI reply kept)",
                session_id,
                intent_confidence,
                intent,
            )
            needs_human = True
            # 保留 AI 回复文本，仅标记转人工

        if pool:
            asyncio.create_task(
                _log_conversation(
                    pool=pool,
                    session_id=session_id,
                    user_message=message,
                    intent=intent,
                    ai_response=reply_text,
                    ai_reply_id=ai_reply_id,
                    sources=sources,
                    confidence=float(result_state.get("intent_confidence", 0.8) or 0.8),
                )
            )

        # Metrics: pipeline path
        _pipeline_replied_at = datetime.now(UTC)
        try:
            from src.services.cs_metrics import record_cs_metric as _record_metric
            asyncio.create_task(
                _record_metric(
                    pool,
                    session_id=session_id,
                    ai_reply_id=ai_reply_id,
                    received_at=_pipeline_received_at,
                    replied_at=_pipeline_replied_at,
                    intent=intent,
                    confidence=float(result_state.get("intent_confidence", 0.8) or 0.8),
                    needs_human=needs_human,
                    was_fast_path=False,
                    compliance_filtered=False,
                )
            )
        except Exception:
            pass

        # ── P1-1 合规过滤（硬拦截 + 软替换） ───────────────────────────────
        from src.agents.customer_service.compliance import check as _compliance_check
        postprocessed = _postprocess_reply_text(reply_text)
        compliance_result = _compliance_check(postprocessed, session_id=session_id)
        if compliance_result.needs_human:
            needs_human = True
        final_reply = compliance_result.text

        return {
            "session_id": session_id,
            "reply": final_reply,
            "ai_reply_id": ai_reply_id,
            "intent": intent,
            "sources": sources,
            "needs_human": needs_human,
            "action": suggested_action,
            "product_cards": product_cards,
            "context_trace": context_trace,
            "compliance_filtered": compliance_result.was_filtered,
        }
    except Exception as e:
        logger.error("[CS] Pipeline execution failed, fallback to legacy: %s", e, exc_info=True)
        return await _chat_legacy(
            session_id=session_id,
            message=message,
            pool=pool,
            conversation_history=conversation_history,
            images=images,
            customer_info=customer_info,
            order_context=order_context,
            stream=stream,
            token_callback=token_callback,
        )


async def chat(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
    customer_info: dict[str, Any] | None = None,
    order_context: dict[str, Any] | None = None,
    stream: bool = False,
    token_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """客服聊天入口：按开关路由到 LangGraph 管线或 legacy 实现。"""
    if USE_LANGGRAPH_PIPELINE:
        return await _chat_via_pipeline(
            session_id=session_id,
            message=message,
            pool=pool,
            conversation_history=conversation_history,
            images=images,
            customer_info=customer_info,
            order_context=order_context,
            stream=stream,
            token_callback=token_callback,
        )

    return await _chat_legacy(
        session_id=session_id,
        message=message,
        pool=pool,
        conversation_history=conversation_history,
        images=images,
        customer_info=customer_info,
        order_context=order_context,
        stream=stream,
        token_callback=token_callback,
    )


__all__ = [
    "chat",
    "load_knowledge_base",
    "search_products_with_embedding",
]
