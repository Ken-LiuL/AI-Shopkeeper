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
    """使用embedding搜索商品"""
    try:
        # 获取商品内存实例
        product_memory = get_product_memory()

        # 确保商品已加载
        if not product_memory.loaded:
            await product_memory.load_products(pool)

        # 为查询生成embedding
        query_embedding = None
        try:
            from src.skills.embedding import EmbeddingSkill

            embedding_skill = EmbeddingSkill()
            query_embedding = embedding_skill.embed(query)
            logger.info(f"Query embedding generated: dim={len(query_embedding)}")
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}", exc_info=True)

        # 搜索商品
        results = await product_memory.search_products(
            query_embedding=query_embedding, query_text=query, top_k=5
        )

        logger.info(f"Product search returned {len(results)} results for: {query[:50]}")
        return results

    except Exception as e:
        logger.error(f"Product search failed: {e}")
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

        # 3. 构建系统提示词
        from ..prompts.customer_service import (
            AFTER_SALES_SCRIPTS,
            build_system_prompt,
            build_user_message_with_context,
        )

        system_prompt = build_system_prompt(
            knowledge_base=knowledge_base, after_sales_scripts=AFTER_SALES_SCRIPTS
        )

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

        # 5. 构建包含上下文的用户消息
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
