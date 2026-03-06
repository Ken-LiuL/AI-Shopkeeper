"""
CustomerService Agent 新版实现 - 单次LLM调用模式

砍掉复杂的意图识别+检索+生成流程，改为：
用户消息 → 商品搜索 → 系统提示词+上下文 → LLM直接生成
"""

from __future__ import annotations

import asyncio
import logging

from ..llm import MODEL_DEEPSEEK, call_tool, call_vision
from .product_memory import get_product_memory

logger = logging.getLogger(__name__)


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
    """使用embedding搜索商品。

    优先使用 Neo4j 向量检索；当 Neo4j 不可用时（VECTOR_STORE != neo4j 或驱动未初始化），
    自动降级到 PostgreSQL pgvector 检索，并在失败时最终降级到关键词匹配。
    """
    import os

    vector_store = os.environ.get("VECTOR_STORE", "postgres").lower()

    # ── 生成查询 Embedding ─────────────────────────────────────────────
    query_embedding = None
    try:
        from src.skills.embedding import EmbeddingSkill

        embedding_skill = EmbeddingSkill()
        query_embedding = embedding_skill.embed(query)
        logger.info(f"Query embedding generated: dim={len(query_embedding)}")
    except Exception as e:
        logger.warning(f"Failed to generate query embedding: {e}", exc_info=True)

    # ── Neo4j 路径 ─────────────────────────────────────────────────────
    if vector_store == "neo4j":
        try:
            from src.db import neo4j as neo4j_db
            from src.skills.neo4j_skill import Neo4jSkill

            driver = neo4j_db.get_driver()
            neo4j_skill = Neo4jSkill(driver=driver)

            if query_embedding:
                neo4j_results = await neo4j_skill.vector_search(
                    query_embedding=query_embedding, limit=5
                )
            else:
                neo4j_results = await neo4j_skill.keyword_search(
                    keywords=query.split(), limit=5
                )

            if neo4j_results:
                results = [
                    {
                        "id": r.id,
                        "name": r.name,
                        "description": r.description,
                        "score": r.score,
                    }
                    for r in neo4j_results
                ]
                logger.info(
                    f"[CS] Neo4j vector search returned {len(results)} results for: {query[:50]}"
                )
                return results

            logger.warning("[CS] Neo4j returned 0 results, falling through to postgres fallback")
        except Exception as e:
            logger.warning(
                f"[CS] Neo4j vector search failed ({e}), switching to postgres vector fallback"
            )
        # Fall through to postgres fallback below

    # ── PostgreSQL pgvector 路径 / Neo4j 降级 ─────────────────────────
    if pool is not None and query_embedding is not None:
        try:
            from src.skills.pg_vector_search import search_products_by_vector

            logger.info("[CS] Using postgres vector fallback")
            pg_results = await search_products_by_vector(pool, query_embedding, top_k=5)
            if pg_results:
                logger.info(
                    f"[CS] pgvector returned {len(pg_results)} results for: {query[:50]}"
                )
                return pg_results
        except Exception as e:
            logger.warning(f"[CS] pgvector search failed ({e}), trying in-memory fallback")

    # ── 内存搜索 fallback（已加载时） ──────────────────────────────────
    try:
        product_memory = get_product_memory()

        if not product_memory.loaded and pool is not None:
            await product_memory.load_products(pool)

        if product_memory.loaded:
            logger.info("[CS] Using in-memory product search fallback")
            results = await product_memory.search_products(
                query_embedding=query_embedding, query_text=query, top_k=5
            )
            logger.info(f"[CS] In-memory search returned {len(results)} results for: {query[:50]}")
            return results
    except Exception as e:
        logger.error(f"[CS] In-memory product search also failed: {e}")

    # ── 最终 keyword fallback ──────────────────────────────────────────
    if pool is not None:
        try:
            from src.skills.pg_vector_search import search_products_by_keywords

            logger.info("[CS] Using postgres keyword fallback")
            return await search_products_by_keywords(pool, keywords=query.split()[:5], top_k=5)
        except Exception as e:
            logger.error(f"[CS] Keyword fallback failed: {e}")

    logger.error(f"[CS] All product search methods failed for: {query[:50]}")
    return []


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

        # 2. 搜索相关商品
        product_results = []
        if pool:
            product_results = await search_products_with_embedding(message, pool)

        # 2.5 获取实时经营数据（用于回答业务问题）
        business_context = {}
        if pool:
            try:
                import contextlib
                # 订单/经营数据
                with contextlib.suppress(Exception):
                    dm = await pool.fetchrow("""
                        SELECT COALESCE(SUM(transaction_volume),0)::int AS orders,
                               COALESCE(SUM(deal_amount),0) AS gmv,
                               CASE WHEN SUM(transaction_volume)>0 THEN SUM(deal_amount)/SUM(transaction_volume) ELSE 0 END AS avg_ov,
                               COALESCE(SUM(total_customers),0)::int AS customers,
                               COALESCE(SUM(new_customers),0)::int AS new_cust,
                               COALESCE(AVG(exposure_uv),0)::int AS uv,
                               COALESCE(AVG(exposure_pv),0)::int AS pv
                        FROM store_daily_metrics
                        WHERE metric_date >= CURRENT_DATE - INTERVAL '1 day'
                    """)
                    if dm and dm["orders"] > 0:
                        business_context["orders"] = {"count": dm["orders"], "gmv": round(float(dm["gmv"]),2), "avg_order_value": round(float(dm["avg_ov"]),2)}
                        business_context["customers"] = {"total": dm["customers"], "new": dm["new_cust"], "old": dm["customers"]-dm["new_cust"]}
                        business_context["exposure"] = {"uv": dm["uv"], "pv": dm["pv"]}

                # 库存状况
                with contextlib.suppress(Exception):
                    inv = await pool.fetchrow("""
                        SELECT COUNT(*) FILTER (WHERE status='active') AS total,
                               COUNT(*) FILTER (WHERE status='active' AND stock<5) AS low_stock,
                               COUNT(*) FILTER (WHERE status='active' AND stock=0) AS oos
                        FROM products
                    """)
                    if inv:
                        business_context["inventory"] = {"total": inv["total"], "low_stock": inv["low_stock"], "out_of_stock": inv["oos"]}

                # 热销商品
                with contextlib.suppress(Exception):
                    tops = await pool.fetch("SELECT name, monthly_sales, retail_price FROM products WHERE status='active' AND monthly_sales>0 ORDER BY monthly_sales DESC LIMIT 5")
                    if tops:
                        business_context["top_products"] = [{"name": r["name"], "sales": r["monthly_sales"], "price": float(r["retail_price"] or 0)} for r in tops]

                logger.info(f"Business context loaded: {list(business_context.keys())}")
            except Exception as e:
                logger.warning(f"Failed to load business context: {e}")

        # 3. 构建优化版系统提示词
        try:
            from ..prompts.customer_service import AFTER_SALES_SCRIPTS
            from ..prompts.customer_service_optimized import (
                build_optimized_system_prompt,
                build_optimized_user_message_with_context,
            )

            system_prompt = build_optimized_system_prompt(
                knowledge_base=knowledge_base, after_sales_scripts=AFTER_SALES_SCRIPTS
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

        # 4. 多轮意图追踪
        conversation_context = ""
        try:
            from .tracker import track_conversation

            tracking_result = track_conversation(
                conversation_history=conversation_history or [], user_message=message
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
                },
                "required": ["reply_text", "confidence", "requires_human_review"],
            },
        }

        if images and len(images) > 0:
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

        # 8. 返回结果
        return {
            "session_id": session_id,
            "reply": reply_text,
            "intent": intent,
            "sources": product_results,
            "needs_human": needs_human,
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
