"""
CustomerService Agent 新版实现 - 完整检索管线

管线：意图识别 → 向量+关键词 Hybrid Search → Reranker → GraphRAG 子图丰富 → LLM 生成
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from ..llm import MODEL_DEEPSEEK, call_tool, call_tool_with_reflection, call_vision

logger = logging.getLogger(__name__)


async def _summarize_conversation(messages: list[dict]) -> str:
    """使用 LLM 总结对话历史，避免 context 过长

    Args:
        messages: 要总结的消息列表（role/content 格式）

    Returns:
        对话摘要字符串
    """
    if not messages:
        return ""

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
        logger.info(f"[CS] Conversation summarized: {len(messages)} msgs → {len(summary)} chars")
        return summary
    except Exception as e:
        logger.warning(f"[CS] Conversation summarization failed (graceful): {e}")
        # Fallback: 简单截取最早几条的文本
        fallback_lines = []
        for m in messages[:4]:
            role = "用户" if m.get("role") == "user" else "客服"
            content = (m.get("content") or "")[:50]
            fallback_lines.append(f"{role}：{content}…")
        return "【早期对话摘要】\n" + "\n".join(fallback_lines)


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

    try:
        # 1. 加载知识库（带缓存）
        if not _cache_loaded:
            _knowledge_base_cache = await load_knowledge_base(pool)
            _cache_loaded = True

        knowledge_base = _knowledge_base_cache or []

        # 1.5 对话摘要：超过6轮（12条）时压缩早期历史
        effective_history = conversation_history or []
        conversation_summary = ""
        history_to_summarize: list[dict] = []
        if effective_history and len(effective_history) > 12:
            history_to_summarize = effective_history[:-6]  # 保留最近6条，摘要其余
            effective_history = effective_history[-6:]
        conversation_history = effective_history

        faq_context = []
        product_results = []
        business_context = {}
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

        if history_to_summarize:
            summary_task = asyncio.create_task(
                _summarize_conversation(history_to_summarize)
            )

        if pool:
            faq_task = asyncio.create_task(_search_auto_faq_context(message, pool))

            async def _run_product_pipeline() -> list[dict]:
                try:
                    return await asyncio.wait_for(
                        _full_pipeline_search(message, pool),
                        timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("[CS] Pipeline timeout, falling back")
                    return []

            product_task = asyncio.create_task(_run_product_pipeline())
            business_task = asyncio.create_task(_load_business_context(pool))

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

        try:
            from src.agents.customer_service.tracker import ConversationTracker

            _tracker = ConversationTracker()
            intent_task = asyncio.create_task(_tracker.classify_intent_llm(message))
        except Exception:
            intent_task = None

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
            ]
            if task is not None
        ]
        if first_batch_tasks:
            await asyncio.gather(*first_batch_tasks, return_exceptions=True)

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
            business_context = _consume_task_result(business_task, {})

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

        if pool and not product_results:
            # Fallback：降级到纯向量检索
            product_results = await search_products_with_embedding(message, pool)

        # 2.6 新增补充上下文：售后政策 + 商品评价情感
        policy_context = []
        review_sentiment_context = []
        if pool:
            policy_context, review_sentiment_context = await asyncio.gather(
                _load_policy_documents_context(pool),
                _load_review_sentiment_context(pool, product_results),
            )

        # 3. 构建优化版系统提示词
        try:
            from ..prompts.customer_service import AFTER_SALES_SCRIPTS
            from ..prompts.customer_service_optimized import (
                build_optimized_system_prompt,
                build_optimized_user_message_with_context,
            )

            system_prompt = build_optimized_system_prompt(
                knowledge_base=knowledge_base,
                after_sales_scripts=AFTER_SALES_SCRIPTS,
                customer_profile_str=customer_profile_str if customer_profile_str else None,
            )
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
                knowledge_base=knowledge_base, after_sales_scripts=AFTER_SALES_SCRIPTS
            )
            use_optimized = False
            logger.warning("Using fallback prompts")

        # 3.5 LLM 意图+情感检测（替代关键词规则）
        if emotion_instruction:
            system_prompt = f"{system_prompt}{emotion_instruction}"

        # 加载客服历史决策记忆（非阻塞主流程，失败不影响回复）
        memory_ctx = ""
        try:
            from src.agents.action_tracker import format_memory_context

            memory_ctx = await format_memory_context(
                pool=pool,
                agent_name="customer_service",
                context_type=intent_result.get("intent", "inquiry")
                if "intent_result" in dir()
                else "inquiry",
            )
        except Exception as e:
            logger.debug(f"CS memory context load failed (non-critical): {e}")

        if memory_ctx:
            system_prompt = f"{system_prompt}\n\n{memory_ctx}"

        # 4. 多轮意图追踪
        conversation_context = ""
        try:
            from .tracker import track_conversation

            tracking_result = track_conversation(
                conversation_history=conversation_history or [],
                user_intent=intent_result.get("intent", ""),
                user_message=message,
            )
            conversation_context = tracking_result.get("context_summary", "")
            logger.info(f"Conversation state: {tracking_result.get('state', 'unknown')}")
        except Exception as e:
            logger.warning(f"Failed to track conversation: {e}")

        # 5. 构建包含上下文的用户消息（优化版）
        if use_optimized:
            user_message_with_context = build_optimized_user_message_with_context(
                user_message=message,
                conversation_history=conversation_history,
                product_results=product_results,
                conversation_context=conversation_context,
                business_context=business_context,
            )
        else:
            from ..prompts.customer_service import build_user_message_with_context

            user_message_with_context = build_user_message_with_context(
                user_message=message,
                conversation_history=conversation_history,
                product_results=product_results,
                conversation_context=conversation_context,
            )

        # 5.5 把 FAQ / 售后政策 / 评价情感 / 订单上下文 / 客户画像 / 对话摘要作为补充上下文注入给 LLM
        extra_sections = []

        # 对话摘要（最优先注入，避免遗失上文）
        if conversation_summary:
            extra_sections.append(f"【早期对话摘要（之前轮次要点）】\n{conversation_summary}")

        # 客户画像（让 AI 识别 VIP 并差异化服务）
        if customer_profile_str:
            extra_sections.append(customer_profile_str)

        # 订单上下文（直接注入相关订单数据）
        if order_context_str:
            extra_sections.append(order_context_str)

        if faq_context:
            extra_sections.append(
                "【FAQ 匹配参考（仅参考，不要逐字照搬）】\n"
                + json.dumps(faq_context, ensure_ascii=False)
            )
        if policy_context:
            extra_sections.append(
                "【售后政策参考】\n"
                + json.dumps(policy_context, ensure_ascii=False)
            )
        if review_sentiment_context:
            extra_sections.append(
                "【商品评价情感参考】\n"
                + json.dumps(review_sentiment_context, ensure_ascii=False)
            )
        if extra_sections:
            user_message_with_context = (
                f"{user_message_with_context}\n\n" + "\n\n".join(extra_sections)
            )

        # 5. 调用LLM生成回复（支持图片）
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

        _needs_reflection = (
            "intent_result" in dir()
            and intent_result.get("intent") in ("after_sales", "complaint")
        )

        if _needs_reflection and not images:
            def _reflect_cs_reply(initial_result_str: str) -> str:
                return f"""请审查以下客服回复，检查：
1. 是否先表达了共情和歉意
2. 解决方案是否具体可执行
3. 是否遗漏了用户关心的要点
4. 回复语气是否得体（不过分生硬也不过分卑微）
5. 涉及退款/换货是否符合平台政策

初始回复：
{initial_result_str}

请给出修订后的版本。"""

            result = await call_tool_with_reflection(
                initial_prompt=user_message_with_context,
                reflection_prompt_fn=_reflect_cs_reply,
                tool=tool_schema,
                model=MODEL_DEEPSEEK,
                system=system_prompt,
                trace_name="customer_service_chat_reflected",
            )
        elif images and len(images) > 0:
            # Use vision model for image processing
            result = await call_vision(
                text=user_message_with_context,
                images=images,
                tool=tool_schema,
                model="google/gemini-2.0-flash-001",
                system=system_prompt
                + "\n\n当用户上传图片时：仔细观察图片内容，如果是商品损坏照片 → 确认质量问题并给退换方案；如果是商品照片 → 识别商品并提供信息",
                trace_name="customer_service_vision_chat",
            )
        else:
            # Use regular text model
            result = await call_tool(
                prompt=user_message_with_context,
                tool=tool_schema,
                model=MODEL_DEEPSEEK,
                system=system_prompt,
                trace_name="customer_service_chat",
            )

        # 6. 提取结果
        reply_text = result.get("reply_text", "亲，您的问题我已记录，稍后为您回复~")
        confidence = result.get("confidence", 0.8)
        needs_human = result.get("requires_human_review", False)
        intent = result.get("intent", "other")
        suggested_action = result.get("action", {"type": "none"})

        # 如果 action 要求转人工，自动设置 needs_human
        if isinstance(suggested_action, dict) and suggested_action.get("type") == "transfer_human":
            needs_human = True

        # 事实核查（仅售后/投诉场景）
        if intent in ("after_sales", "complaint") and pool:
            try:
                from src.agents.fact_checker import validate_agent_output

                check_result = await validate_agent_output(
                    agent_name="customer_service",
                    output=result,
                    pool=pool,
                )
                if check_result and not check_result.get("passed", True):
                    warnings = check_result.get("warnings", [])
                    if warnings:
                        reply_text += "\n\n⚠️ 温馨提示：以上为AI回复，涉及售后问题建议联系人工客服确认。"
                        needs_human = True
            except Exception:
                pass

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

            # 8. 异步评分（不阻塞响应）
            from .evaluator import evaluate_and_store

            asyncio.create_task(
                evaluate_and_store(
                    pool=pool,
                    session_id=session_id,
                    user_message=message,
                    ai_reply=reply_text,
                    conversation_history=conversation_history,
                    product_results=product_results,
                )
            )

            # 9. 自动进化Hook（不阻塞响应）
            from .auto_evolve import after_reply_hook

            context = {
                "conversation_history": conversation_history,
                "product_results": product_results,
                "intent": intent,
                "confidence": confidence,
                "needs_human": needs_human,
            }

            asyncio.create_task(
                after_reply_hook(
                    session_id=session_id,
                    user_msg=message,
                    reply=reply_text,
                    context=context,
                    pool=pool,
                )
            )

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
        return {
            "session_id": session_id,
            "reply": reply_text,
            "intent": intent,
            "sources": product_results,
            "needs_human": needs_human,
            "action": suggested_action,
        }

    except Exception as e:
        logger.error(f"Chat function failed: {e}")
        return {
            "session_id": session_id,
            "reply": "亲，系统繁忙，请稍后重试或联系人工客服🙏",
            "intent": "other",
            "sources": [],
            "needs_human": True,  # 出错时转人工
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
