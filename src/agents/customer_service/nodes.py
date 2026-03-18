"""
CustomerService Agent 新版实现 - 完整检索管线

管线：意图识别 → 向量+关键词 Hybrid Search → Reranker → GraphRAG 子图丰富 → LLM 生成
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import time

from ..llm import MODEL_DEEPSEEK, MODEL_SONNET, call_chat, call_tool, call_vision

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# P0-1: Fast-Path 秒回（仅拦截确定性高频简单消息）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FAST_PATH_GREETINGS = frozenset({
    "你好", "您好", "在吗", "在不在", "有人吗", "hi", "hello",
    "你好啊", "您好啊", "嗨", "hey", "ni hao",
})

_FAST_PATH_THANKS = frozenset({
    "谢谢", "谢谢你", "谢谢您", "感谢", "多谢", "thank you",
    "thanks", "非常感谢", "太感谢了", "感谢您",
})

_FAST_PATH_ACKS = frozenset({
    "好的", "嗯嗯", "嗯", "知道了", "收到", "好哒", "ok", "okay",
})

_GREETING_REPLIES = [
    "亲，您好！😊 欢迎光临，请问有什么可以帮您的呢？",
    "您好亲！🌟 我是AI客服小康，随时为您服务，请问有什么需要帮忙吗？",
    "亲好！😊 很高兴为您服务，请问想了解哪方面的商品或问题呢？",
]
_THANKS_REPLIES = [
    "亲，不客气！😊 还有其他需要帮忙的吗？",
    "应该的亲！🌟 如有任何问题随时告诉我哦~",
    "不用谢亲！😊 祝您购物愉快，有需要随时来找我~",
]
_ACK_REPLIES = [
    "亲，好的！😊 有其他问题随时告诉我哦~",
    "好的亲！🌟 如还有需要帮忙的随时找我~",
]


def _fast_path_reply(session_id: str, message: str) -> dict | None:
    """
    P0-1 快速路径：只拦截确定性高频简单消息（问候、感谢、简单确认）。
    不拦截任何需要推理的商品/订单/售后问题。
    命中时打印 [CS-PERF] Fast-path hit 日志。
    """
    m = message.strip().lower().rstrip("~！!。，,.?？ ")

    if m in _FAST_PATH_GREETINGS:
        reply = random.choice(_GREETING_REPLIES)
        logger.info("[CS-PERF] Fast-path hit: greeting")
        return {
            "session_id": session_id,
            "reply": reply,
            "intent": "greeting",
            "sources": [],
            "needs_human": False,
            "action": {"type": "none"},
            "product_cards": [],
        }

    if m in _FAST_PATH_THANKS:
        reply = random.choice(_THANKS_REPLIES)
        logger.info("[CS-PERF] Fast-path hit: thanks")
        return {
            "session_id": session_id,
            "reply": reply,
            "intent": "greeting",
            "sources": [],
            "needs_human": False,
            "action": {"type": "none"},
            "product_cards": [],
        }

    # 简单确认：只对极短消息触发（防止"好的，那血压计多少钱"被拦截）
    if m in _FAST_PATH_ACKS and len(message.strip()) <= 6:
        reply = random.choice(_ACK_REPLIES)
        logger.info("[CS-PERF] Fast-path hit: ack")
        return {
            "session_id": session_id,
            "reply": reply,
            "intent": "greeting",
            "sources": [],
            "needs_human": False,
            "action": {"type": "none"},
            "product_cards": [],
        }

    return None



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# P1-1: 合规过滤层（医疗器械红线）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 医疗器械合规词替换表（顺序敏感：长词优先）
_COMPLIANCE_MAP: list[tuple[str, str]] = [
    ("100%有效", "效果显著"),
    ("100%治好", "有效辅助改善"),
    ("100%治愈", "有效辅助改善"),
    ("彻底治好", "有效辅助改善"),
    ("彻底治愈", "有效辅助改善"),
    ("根治", "有效辅助改善"),
    ("治愈", "辅助改善"),
    ("保证疗效", "有助于改善"),
    ("代替就医", "辅助居家健康管理"),
    ("替代就医", "辅助居家健康管理"),
    ("包治百病", "广泛适用"),
    ("药到病除", "效果显著"),
]


def _compliance_filter(reply_text: str) -> str:
    """
    P1-1 合规过滤层（额外安全层，不替代 prompt 引导）。
    过滤医疗器械禁用词，替换为合规表述。
    """
    filtered = reply_text
    for forbidden, replacement in _COMPLIANCE_MAP:
        if forbidden in filtered:
            new_text = filtered.replace(forbidden, replacement)
            logger.info(f"[CS-COMPLIANCE] Filtered: {forbidden} -> {replacement}")
            filtered = new_text
    return filtered



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 快速意图预判 + 上下文预算器（不额外调 LLM）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _quick_intent_guess(message: str, conversation_history: list[dict] | None = None) -> str:
    """基于关键词的快速意图预判，结合对话历史判断上下文延续。

    核心原则：短/模糊消息（如"有哪些"/"多少钱"）必须结合历史判断，
    不能当作独立新问题。否则会丢失"我们一直在聊血压计"的上下文。
    """
    m = message.strip().lower()

    # ===== 第一层：明确意图，关键词足够强，无需历史 =====
    if any(kw in m for kw in ["投诉", "举报", "315", "律师", "消协", "骗"]):
        return "complaint"
    if any(kw in m for kw in ["退", "换", "坏了", "破损", "过期", "质量"]):
        return "after_sales"
    if any(kw in m for kw in ["吃什么药", "用药", "治疗", "诊断", "处方", "药"]):
        return "medical_advice"
    if any(kw in m for kw in ["发货", "物流", "送到", "配送", "骑手", "多久到", "还没到", "催单"]):
        return "logistics"
    if "订单" in m and any(kw in m for kw in ["还没", "多久", "到了吗", "在哪", "怎么"]):
        return "logistics"
    if any(kw in m for kw in ["对比", "区别", "vs", "哪个更"]):
        return "comparison"
    if any(kw in m for kw in ["和", "跟"]) and any(kw in m for kw in ["哪个好", "哪个更", "区别", "好"]):
        return "comparison"
    if any(kw in m for kw in ["怎么用", "用法", "用量", "一盒", "能用多久"]):
        return "usage_question"

    # ===== 第二层：模糊/短消息 → 从历史推断 =====
    vague_kws = [
        "有哪些", "都有什么", "还有吗", "有啥", "哪个", "哪款",
        "多少钱", "价格", "贵吗", "便宜", "打折", "推荐",
        "有没有", "哪个好", "什么牌子", "不是", "那个",
    ]
    is_vague = len(m) <= 20 and any(kw in m for kw in vague_kws)

    if is_vague and conversation_history:
        # 向上扫描最近对话，找到最近的"商品话题"
        product_signals = [
            "推荐", "血压", "体温", "血糖", "口罩", "创可贴",
            "型号", "库存", "月销", "欧姆龙", "鱼跃", "体重秤",
            "轮椅", "拐杖", "雾化", "制氧", "呼吸机",
            "退热贴", "纱布", "绷带", "面膜", "敷料",
        ]
        for msg in reversed(conversation_history[-8:]):
            content = (msg.get("content") or "").lower()
            if any(kw in content for kw in product_signals):
                return "product_inquiry"  # 延续商品话题
        # 历史里没有商品话题，但用户在追问 → 大概率还是商品
        return "product_inquiry"

    # ===== 第三层：非模糊的常规判断 =====
    if any(kw in m for kw in ["推荐", "有没有", "哪个好", "哪款", "什么牌子"]):
        return "recommendation"
    if any(kw in m for kw in ["价格", "多少钱", "贵", "便宜", "打折"]):
        return "product_inquiry"

    # 自报身份（"我是XX"）：在有历史对话时视为上下文延续，不是新对话
    if re.match(r"^我是.{1,10}$", m) and conversation_history:
        # 用户只是报了个名字，延续之前的话题
        _id_product_kw = ["血压", "体温", "血糖", "口罩", "推荐", "型号", "价格"]
        for msg in reversed(conversation_history[-6:]):
            content = (msg.get("content") or "").lower()
            if any(kw in content for kw in _id_product_kw):
                return "product_inquiry"
        return "other"

    # greeting: 仅在对话开头或纯问候短语时触发
    # "我是塔哥" 这种自报身份不是 greeting（对话已经在进行中）
    if any(kw in m for kw in ["你好", "在吗", "hi", "hello"]):
        if not conversation_history or len(m) <= 5:
            return "greeting"
        # 有历史对话时，"你好"可能是打断但不应该重置上下文
        return "other"

    return "other"


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


async def _full_pipeline_search(message: str, pool=None) -> list[dict]:
    """完整检索管线：向量+关键词 Hybrid Search → Reranker → GraphRAG 子图丰富。

    任何一步失败都有 graceful fallback，不会抛出异常。
    """
    try:
        from src.db import neo4j as neo4j_db
        from src.skills.embedding import EmbeddingSkill
        from src.skills.neo4j_skill import Neo4jSkill

        driver = neo4j_db.get_driver()
        neo4j_skill = Neo4jSkill(driver=driver)

        # ── Step 1: 生成 Embedding ─────────────────────────────────────
        query_embedding = None
        try:
            embedding_skill = EmbeddingSkill()
            query_embedding = embedding_skill.embed(message)
            logger.info(f"[CS] Query embedding generated: dim={len(query_embedding)}")
        except Exception as e:
            logger.warning(f"[CS] Embedding generation failed (graceful): {e}")

        # ── Step 2: 并发向量检索 + 关键词检索 ─────────────────────────
        vector_results = []
        keyword_results = []

        async def _vector_search():
            if query_embedding:
                try:
                    return await neo4j_skill.vector_search(query_embedding, limit=10)
                except Exception as e:
                    logger.warning(f"[CS] Vector search failed (graceful): {e}")
            return []

        async def _keyword_search():
            try:
                keywords = [w for w in message.split() if len(w) > 1]
                if not keywords:
                    keywords = [message[:10]]
                return await neo4j_skill.keyword_search(keywords, limit=10)
            except Exception as e:
                logger.warning(f"[CS] Keyword search failed (graceful): {e}")
                return []

        vector_results, keyword_results = await asyncio.gather(
            _vector_search(), _keyword_search()
        )
        logger.info(
            f"[CS] Retrieval: vector={len(vector_results)}, keyword={len(keyword_results)}"
        )

        # ── Step 3: RRF 融合 ──────────────────────────────────────────
        merged_models = neo4j_skill._rrf_merge(vector_results, keyword_results)
        merged_dicts = [
            {"id": r.id, "name": r.name, "description": r.description, "score": r.score}
            for r in merged_models
        ]
        logger.info(f"[CS] RRF merged: {len(merged_dicts)} candidates")

        # ── Step 4: Reranker 精排 ────────────────────────────────────
        reranked: list[dict] = []
        try:
            from src.skills.reranker import RerankerSkill

            reranker = RerankerSkill()
            loop = asyncio.get_event_loop()
            reranked = await loop.run_in_executor(
                None,
                lambda: reranker.rerank(message, merged_dicts, top_k=5),
            )
            logger.info(f"[CS] Reranker returned {len(reranked)} results")
        except Exception as e:
            logger.warning(f"[CS] Reranker failed (graceful fallback to top-5 RRF): {e}")
            reranked = merged_dicts[:5]

        if not reranked:
            reranked = merged_dicts[:5]

        # ── Step 5: GraphRAG 子图丰富 ────────────────────────────────
        async def _enrich_product(product: dict) -> dict:
            enriched_product = dict(product)
            try:
                product_id = enriched_product.get("id")
                if product_id:
                    graph_ctx, deep_ctx = await asyncio.gather(
                        neo4j_skill.get_product_graph(product_id),
                        neo4j_skill.get_deep_context(product_id),
                    )
                    if graph_ctx:
                        enriched_product["suitable_for"] = graph_ctx.suitable_for or []
                        enriched_product["contraindicated_for"] = [
                            {"name": c.get("name", ""), "reason": c.get("reason", "")}
                            if isinstance(c, dict) else {"name": str(c)}
                            for c in (graph_ctx.contraindicated_for or [])
                        ]
                        enriched_product["related_products"] = [
                            {"id": r.get("id", ""), "name": r.get("name", "")}
                            if isinstance(r, dict) else {"name": str(r)}
                            for r in (graph_ctx.related_products or [])
                        ]
                        enriched_product["scenarios"] = graph_ctx.scenarios or []
                    if deep_ctx:
                        competitors = deep_ctx.get("competitors") or []
                        seasons = deep_ctx.get("seasons") or []
                        if competitors:
                            enriched_product["deep_competitors"] = competitors
                        if seasons:
                            enriched_product["deep_seasons"] = seasons
                        if competitors or seasons:
                            enriched_product["deep_context"] = {
                                "competitors": competitors,
                                "seasons": seasons,
                            }
            except Exception as e:
                logger.warning(
                    f"[CS] GraphRAG enrichment failed for {enriched_product.get('id')} (graceful): {e}"
                )
            return enriched_product

        enriched = await asyncio.gather(
            *(_enrich_product(product) for product in reranked)
        )

        logger.info(f"[CS] Pipeline complete: {len(enriched)} enriched products")
        return enriched

    except Exception as e:
        logger.error(f"[CS] Full pipeline search failed: {e}", exc_info=True)
        return []


async def load_knowledge_base(pool) -> list[dict]:
    """从数据库加载完整知识库"""
    try:
        rows = await pool.fetch("""
            SELECT category, subcategory, question, answer, keywords, priority, product_categories
            FROM knowledge_base
            ORDER BY priority DESC, id
        """)

        knowledge_base = []
        for row in rows:
            knowledge_base.append(
                {
                    "category": row["category"],
                    "subcategory": row["subcategory"],
                    "question": row["question"],
                    "answer": row["answer"],
                    "keywords": row["keywords"] or [],
                    "priority": row["priority"],
                    "product_categories": row["product_categories"] or [],
                }
            )

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

    patterns = [f"%{q}%"]
    patterns.extend([f"%{kw}%" for kw in q.split() if len(kw.strip()) >= 2][:5])

    matched: list[dict] = []
    seen_ids: set[int] = set()
    seen_questions: set[str] = set()

    try:
        for pattern in patterns:
            if len(matched) >= limit:
                break
            rows = await pool.fetch(
                """
                SELECT id, question, answer_template, keywords
                FROM auto_faq
                WHERE question ILIKE $1
                ORDER BY id DESC
                LIMIT $2
                """,
                pattern,
                limit,
            )
            for row in rows:
                row_id = row.get("id")
                question = (row.get("question") or "").strip()
                if row_id is not None and row_id in seen_ids:
                    continue
                if question and question in seen_questions:
                    continue
                if row_id is not None:
                    seen_ids.add(row_id)
                if question:
                    seen_questions.add(question)
                matched.append(
                    {
                        "id": row_id,
                        "question": question,
                        "answer_template": row.get("answer_template") or "",
                        "keywords": row.get("keywords") or [],
                    }
                )
                if len(matched) >= limit:
                    break
        logger.info(f"[CS] FAQ context matched: {len(matched)}")
    except Exception as e:
        logger.warning(f"[CS] Failed to load auto_faq context (graceful): {e}")

    return matched[:limit]


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
    sources: list[dict] | None = None,
    confidence: float = 0.0,
) -> None:
    """异步记录对话日志"""
    if not pool:
        return

    try:
        # 提取商品IDs用于日志
        product_ids = []
        if sources:
            for source in sources:
                if source.get("id"):
                    product_ids.append(source["id"])

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


async def chat(
    session_id: str,
    message: str,
    pool=None,
    conversation_history: list[dict] | None = None,
    images: list[str] | None = None,
) -> dict:
    """
    新版客服聊天函数 - 单次LLM调用完成所有任务

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

    try:
        # P0-1: Fast-path 秒回（确定性高频简单消息，无需调 LLM）
        _fast = _fast_path_reply(session_id, message)
        if _fast is not None:
            _t_fast = time.time()
            logger.info(f"[CS-PERF] Fast-path total: {(_t_fast - _t0)*1000:.0f}ms")
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

        faq_context = []
        product_results = []
        order_context_str = ""
        customer_profile_str = ""
        intent_result = {}
        sentiment = "neutral"
        emotion_instruction = ""

        summary_task = None
        faq_task = None
        product_task = None
        business_task = None
        order_task = None
        profile_task = None
        intent_task = None
        build_profile_context_str = None

        # 性能优先配置（默认开启）
        fast_mode = os.getenv("CS_FAST_MODE", "1") == "1"
        pipeline_timeout = float(os.getenv("CS_PIPELINE_TIMEOUT", "4.0" if fast_mode else "10.0"))
        enable_intent_llm = os.getenv("CS_INTENT_LLM", "0") == "1" and not fast_mode
        max_reply_tokens = int(os.getenv("CS_REPLY_MAX_TOKENS", "512"))

        if history_to_summarize:
            summary_task = asyncio.create_task(
                _summarize_conversation(history_to_summarize)
            )

        # ── 额外并行任务（原来在第二轮 gather，现在合并到第一轮） ──
        policy_task = None
        few_shot_task = None
        cm_task = None
        memory_task = None

        if pool:
            faq_task = asyncio.create_task(_search_auto_faq_context(message, pool))

            async def _run_product_pipeline() -> list[dict]:
                try:
                    return await asyncio.wait_for(
                        _full_pipeline_search(message, pool),
                        timeout=pipeline_timeout,
                    )
                except TimeoutError:
                    logger.warning("[CS] Pipeline timeout, falling back")
                    return []

            product_task = asyncio.create_task(_run_product_pipeline())
            async def _cached_business_context():
                global _business_ctx_cache, _business_ctx_ts
                if _business_ctx_cache is not None and (time.time() - _business_ctx_ts) < _CACHE_TTL:
                    return _business_ctx_cache
                result = await _load_business_context(pool)
                _business_ctx_cache = result
                _business_ctx_ts = time.time()
                return result

            business_task = asyncio.create_task(_cached_business_context())

            try:
                from .order_context import build_order_context_str, has_order_mention

                if has_order_mention(message):
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

            policy_task = asyncio.create_task(_safe_load_policy())
            few_shot_task = asyncio.create_task(_safe_load_dynamic_few_shots())

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

            memory_task = asyncio.create_task(_safe_load_memory())

        # ── 话题管理器（原来串行等待，现在并行） ──────────────────
        from .conversation_manager import load_conversation_manager, save_conversation_manager

        from src.db import redis as redis_db

        _redis = redis_db.get_redis()
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

        task_labels = {
            id(summary_task): "summary",
            id(faq_task): "faq",
            id(product_task): "product",
            id(business_task): "business",
            id(order_task): "order",
            id(profile_task): "profile",
            id(intent_task): "intent",
            id(policy_task): "policy",
            id(few_shot_task): "few_shot",
            id(cm_task): "conv_mgr",
            id(memory_task): "memory",
        }

        first_batch_tasks = [
            task
            for task in [
                summary_task,
                faq_task,
                product_task,
                business_task,
                order_task,
                profile_task,
                intent_task,
                policy_task,
                few_shot_task,
                cm_task,
                memory_task,
            ]
            if task is not None
        ]
        if first_batch_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*first_batch_tasks, return_exceptions=True),
                    timeout=5.0,  # 所有前置数据加载总共不超过5秒
                )
            except TimeoutError:
                logger.warning("[CS] First batch tasks timed out at 5s, proceeding with available data")

        _t_tasks_done = time.time()
        # 逐个任务报告耗时和状态
        _task_perf = []
        for task in [summary_task, faq_task, product_task, business_task, order_task, profile_task, intent_task, policy_task, few_shot_task, cm_task, memory_task]:
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

        if business_task:
            _consume_task_result(business_task, {})

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

        if pool and not product_results:
            # Fallback：降级到纯向量检索
            product_results = await search_products_with_embedding(message, pool)

        # 2.6 售后政策 + 动态 few-shot（已在第一轮并行加载，直接取结果）
        policy_context = _consume_task_result(policy_task, [])
        dynamic_few_shots = _consume_task_result(few_shot_task, {})

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

        # ── 快速意图预判（用于上下文路由，不依赖 LLM） ──────────────
        quick_intent = _quick_intent_guess(message, conversation_history)
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

        # 调试日志：打印传给 LLM 的 messages 结构（只打角色和前50字）
        _msg_debug = [f"{m['role']}: {(m.get('content',''))[:50]}..." for m in llm_messages]
        logger.info(f"[CS-DEBUG] LLM messages ({len(llm_messages)} turns): {_msg_debug}")

        _t_pre_llm = time.time()
        logger.info(f"[CS-PERF] Pre-LLM pipeline took {(_t_pre_llm - _t0)*1000:.0f}ms")

        # 5. 调用 LLM 生成回复（纯文本模式，不用 tool_choice，速度快很多）
        #
        # 把 JSON 格式要求写进 system prompt，让模型直接输出 JSON 文本，
        # 然后我们自己解析。避免 tool_choice 的巨大开销。

        _json_instruction = """

# 输出格式（严格 JSON，不要输出其他内容）
{"reply_text":"你的回复(80-150字)","confidence":0.9,"requires_human_review":false,"intent":"product_inquiry","action":{"type":"none"}}

intent 可选: product_inquiry, usage_question, recommendation, comparison, logistics, after_sales, complaint, medical_advice, greeting, other
action.type 可选: none, check_order, check_logistics, initiate_refund, initiate_exchange, apply_coupon, transfer_human"""

        _full_system = system_prompt + _json_instruction

        if images and len(images) > 0:
            # 图片场景仍用 tool_choice（call_vision 需要）
            tool_schema = {
                "name": "output_reply",
                "description": "输出客服回复",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reply_text": {"type": "string", "maxLength": 200},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "requires_human_review": {"type": "boolean"},
                        "intent": {"type": "string"},
                        "action": {"type": "object", "properties": {"type": {"type": "string"}}, "required": ["type"]},
                    },
                    "required": ["reply_text", "confidence", "requires_human_review"],
                },
            }
            result = await call_vision(
                text=user_message_with_context,
                images=images,
                tool=tool_schema,
                model="google/gemini-2.0-flash-001",
                max_tokens=max_reply_tokens,
                system=_full_system
                + "\n\n当用户上传图片时：仔细观察图片内容，如果是商品损坏照片 → 确认质量问题并给退换方案；如果是商品照片 → 识别商品并提供信息",
                trace_name="customer_service_vision_chat",
            )
        else:
            # 纯文本模式：call_chat + JSON 解析（比 tool_choice 快 3-5 倍）
            raw_content, _, _ = await call_chat(
                prompt=user_message_with_context,
                model=MODEL_SONNET,
                max_tokens=max_reply_tokens,
                system=_full_system,
                response_format={"type": "json_object"},
                trace_name="customer_service_chat",
            )

            # 解析 JSON 回复
            raw_content = raw_content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                result = json.loads(raw_content)
            except json.JSONDecodeError:
                logger.warning(f"[CS] JSON parse failed, extracting text. Raw: {raw_content[:200]}")
                # fallback: 把整个回复当作 reply_text
                result = {
                    "reply_text": raw_content[:200] if raw_content else "亲，请稍后重试~",
                    "confidence": 0.7,
                    "requires_human_review": False,
                    "intent": current_intent,
                    "action": {"type": "none"},
                }

        _t_post_llm = time.time()
        logger.info(f"[CS-PERF] LLM call took {(_t_post_llm - _t_pre_llm)*1000:.0f}ms | Total so far: {(_t_post_llm - _t0)*1000:.0f}ms")

        # 6. 提取结果
        reply_text = result.get("reply_text", "亲，您的问题我已记录，稍后为您回复~")
        confidence = result.get("confidence", 0.8)
        needs_human = result.get("requires_human_review", False)
        intent = result.get("intent", "other")
        suggested_action = result.get("action", {"type": "none"})

        # P1-1: 合规过滤层（额外安全层）
        reply_text = _compliance_filter(reply_text)


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
                    sources=product_results,
                    confidence=confidence,
                )
            )

            from .auto_evolve import after_reply_hook
            from .evaluator import evaluate_and_store

            context = {
                "conversation_history": conversation_history,
                "product_results": product_results,
                "intent": intent,
                "confidence": confidence,
                "needs_human": needs_human,
            }

            # 8. 异步评分+进化（合并为一个任务，避免重复评分）
            async def _evaluate_and_evolve():
                """先评分存储，再触发进化（共享评分结果，不重复调用 LLM）"""
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
        return {
            "session_id": session_id,
            "reply": reply_text,
            "intent": intent,
            "sources": product_results,
            "needs_human": needs_human,
            "action": suggested_action,
            "product_cards": product_cards,  # P2-1
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
        else:
            error_code = "llm_unknown_error"

        error_detail = err_text[:500]
        logger.error(f"Chat function failed [{error_code}]: {e}", exc_info=True)
        return {
            "session_id": session_id,
            "reply": f"亲，系统繁忙，请稍后重试或联系人工客服🙏（错误码: {error_code}）",
            "intent": "other",
            "sources": [],
            "needs_human": True,
            "error_code": error_code,
            "error_detail": error_detail,
        }


# 为了向后兼容，保留一些原有函数签名（但实现很简单）
async def _search_knowledge_base(
    pool, query: str, intent: str = None, limit: int = 3
) -> list[dict]:
    """向后兼容的知识库搜索（已废弃，新版本不使用）"""
    logger.warning("_search_knowledge_base is deprecated, use new chat() function instead")
    return []


async def _log_conversation_compat(
    pool,
    session_id: str = None,
    user_message: str = "",
    intent: str = "",
    ai_response: str = "",
    matched_kb_ids: list[int] = None,
    matched_product_ids: list[str] = None,
    confidence: float = 0.0,
) -> None:
    """向后兼容的日志记录函数"""
    await _log_conversation(pool, session_id, user_message, intent, ai_response, None, confidence)


# 导出兼容接口
__all__ = [
    "chat",
    "load_knowledge_base",
    "search_products_with_embedding",
    "_search_knowledge_base",  # 向后兼容
    "_log_conversation_compat",  # 向后兼容
]
