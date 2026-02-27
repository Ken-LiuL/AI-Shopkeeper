"""CustomerService Agent 各节点实现

融合数据:
  - 客服知识库 (knowledge_base) — 检索标准回答和专业指导
  - 客户画像 (qnh_customers) — 高价值客户优先处理、语气更重视
  - 待处理订单 (qnh_orders_raw) — 客服回复时带上订单状态上下文
  - 热销商品 (qnh_products_raw) — 客服推荐时有数据支撑
  - 对话日志 (cs_conversation_log) — 记录所有对话用于分析优化
"""

from __future__ import annotations

import json
import logging

from src.services.raw_data import fetch_latest_raw

from ..llm import MODEL_FLASH, MODEL_SONNET, call_tool
from ..prompts.customer_service import (
    FAQ_TEMPLATES,
    HUMAN_TRANSFER_KEYWORDS,
    intent_prompt,
    reply_prompt,
)
from ..tools import INTENT_TOOL, REPLY_TOOL
from .state import CustomerServiceState

logger = logging.getLogger(__name__)


async def _search_knowledge_base(
    pool, query: str, intent: str = None, limit: int = 3
) -> list[dict]:
    """从客服知识库中检索相关知识。

    基于意图分类 + 关键词匹配，优先级排序。
    """
    if not pool:
        return []
    try:
        # 构建查询词列表 — 中文关键词提取（不依赖分词库）
        # 1. 先按空格/标点拆分
        import re

        raw_tokens = re.split(r"[\s,，。？！?!、；;：:]+", query)
        query_words = []
        # 2. 常见客服关键词字典（匹配知识库 keywords）
        _CS_KEYWORDS = [
            "退货",
            "退款",
            "退换货",
            "换货",
            "退换",
            "拆封",
            "质量问题",
            "保质期",
            "过期",
            "发票",
            "配送",
            "运费",
            "价格",
            "优惠",
            "活动",
            "口罩",
            "血压计",
            "体温计",
            "血糖仪",
            "血氧仪",
            "雾化",
            "轮椅",
            "护具",
            "护膝",
            "拐杖",
            "隐形眼镜",
            "护理液",
            "消毒",
            "创可贴",
            "敷贴",
            "纱布",
            "绷带",
            "怎么用",
            "使用方法",
            "注意事项",
            "保修",
            "赔偿",
            "投诉",
            "差评",
            "多久到",
            "送到",
            "配送时间",
            "到账",
            "发货",
            "卫生巾",
            "避孕套",
            "医疗器械",
            "处方药",
            "安全",
            "个人信息",
            "隐私",
            "客服",
        ]
        for token in raw_tokens:
            token = token.strip().lower()
            if not token:
                continue
            # 从 token 中提取匹配的关键词
            for kw in _CS_KEYWORDS:
                if kw in token and kw not in query_words:
                    query_words.append(kw)
            # 也保留原始 token 用于 ILIKE 匹配
            if len(token) > 1 and token not in query_words:
                query_words.append(token)

        # 根据意图推荐对应类别
        intent_category_map = {
            "product_inquiry": ["faq", "usage_guide"],
            "recommendation": ["faq", "usage_guide"],
            "comparison": ["faq", "usage_guide"],
            "after_sales": ["policy", "faq"],
            "complaint": ["compliance", "policy"],
            "usage_question": ["usage_guide", "compliance"],
            "medical_advice": ["compliance", "usage_guide"],
            "logistics": ["faq", "policy"],
            "greeting": ["faq"],
        }
        preferred_categories = intent_category_map.get(intent, [])

        # Build params list from scratch: $1..$N for words, then categories, then limit
        params: list = []
        word_conditions = []
        word_scores = []

        for w in query_words[:10]:
            idx = len(params) + 1
            params.append(w)
            word_conditions.append(
                f"(keywords && ARRAY[${idx}]::text[] "
                f"OR question ILIKE '%' || ${idx} || '%' "
                f"OR answer ILIKE '%' || ${idx} || '%')"
            )
            word_scores.append(
                f"(CASE WHEN keywords && ARRAY[${idx}]::text[] THEN 2 ELSE 0 END + "
                f"CASE WHEN question ILIKE '%' || ${idx} || '%' THEN 1 ELSE 0 END + "
                f"CASE WHEN answer ILIKE '%' || ${idx} || '%' THEN 0.5 ELSE 0 END)"
            )

        # Category filter
        if preferred_categories:
            cat_idx = len(params) + 1
            params.append(preferred_categories)
            category_condition = f"AND category = ANY(${cat_idx})"
        else:
            category_condition = ""

        # Limit
        limit_idx = len(params) + 1
        params.append(limit)

        where_words = " OR ".join(word_conditions) if word_conditions else "TRUE"
        score_expr = " + ".join(word_scores) if word_scores else "0"

        sql = f"""
            SELECT id, category, subcategory, question, answer, keywords,
                   priority, product_categories,
                   ({score_expr} + priority * 0.1) as relevance_score
            FROM knowledge_base
            WHERE ({where_words})
            {category_condition}
            ORDER BY relevance_score DESC, priority DESC, id
            LIMIT ${limit_idx}
        """

        rows = await pool.fetch(sql, *params)

        results = []
        for r in rows:
            result = dict(r)
            # 只返回相关性分数 > 0 的结果
            if result.get("relevance_score", 0) > 0:
                results.append(result)

        logger.info(
            f"Knowledge base search returned {len(results)} results for query: {query[:50]}"
        )
        return results

    except Exception as e:
        logger.warning(f"Knowledge base search failed: {e}")
        return []


async def _log_conversation(
    pool,
    session_id: str = None,
    user_message: str = "",
    intent: str = "",
    ai_response: str = "",
    matched_kb_ids: list[int] = None,
    matched_product_ids: list[str] = None,
    confidence: float = 0.0,
) -> None:
    """记录对话日志，用于后续分析和训练。"""
    if not pool:
        return

    try:
        await pool.execute(
            """
            INSERT INTO cs_conversation_log (
                session_id, user_message, intent, ai_response,
                matched_kb_ids, matched_product_ids, confidence, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """,
            session_id,
            user_message[:1000],  # 限制长度避免数据库问题
            intent,
            ai_response[:2000],
            matched_kb_ids or [],
            matched_product_ids or [],
            confidence,
        )
    except Exception as e:
        logger.warning(f"Failed to log conversation: {e}")
        # 不中断正常流程


async def _get_customer_profile(pool, phone_tail: str | None = None) -> dict | None:
    """查询客户画像信息（消费排行、价值等级）。"""
    if not pool or not phone_tail:
        return None
    try:
        row = await pool.fetchrow(
            """
            SELECT customer_id, nickname, total_amount, order_count,
                   repurchase_rate, tags
            FROM qnh_customers
            WHERE phone_tail = $1
            ORDER BY total_amount DESC
            LIMIT 1
            """,
            phone_tail,
        )
        return dict(row) if row else None
    except Exception as e:
        logger.warning(f"Customer profile lookup failed: {e}")
        return None


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

    # 检查消息中是否包含投诉类转人工触发词
    msg = state.get("user_message", "").lower()
    has_complaint_kw = any(kw in msg for kw in HUMAN_TRANSFER_KEYWORDS)

    # 仅投诉意图 或 包含投诉关键词 → 转人工
    if intent == "complaint" or has_complaint_kw:
        return {"route": "human"}

    # FAQ 路由（纯模板可答）
    if intent == "greeting":
        return {"route": "faq"}

    # 其他所有意图（包括 after_sales, medical_advice, logistics, product_inquiry 等）
    # → 走知识库+商品检索，让 LLM 基于知识库生成专业回复
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

    # 模板变量默认值
    tpl_defaults = {
        "delivery_time": "30-60分钟内",
        "order_status": "已接单",
        "status_detail": "正在为您配货中~",
        "after_sales_detail": "",
    }

    for tpl in templates:
        triggers = tpl.get("trigger", [])
        if any(t in msg for t in triggers):
            reply = tpl["reply"]
            for k, v in tpl_defaults.items():
                reply = reply.replace("{" + k + "}", v)
            return {"faq_reply": reply}

    if templates:
        reply = templates[0]["reply"]
        for k, v in tpl_defaults.items():
            reply = reply.replace("{" + k + "}", v)
        return {"faq_reply": reply}
    return {"faq_reply": "亲，在的呢~请问有什么可以帮您？😊"}


async def hybrid_search_node(state: CustomerServiceState) -> dict:
    """Hybrid Search: 向量 + 关键词混合检索（EmbeddingSkill + Neo4jSkill）+ 商品知识库。"""
    from .skills_registry import get_embedding, get_neo4j, get_product_knowledge

    neo4j = get_neo4j()
    embedding_skill = get_embedding()
    product_knowledge = get_product_knowledge()
    intent_data = state.get("intent", {})
    entities = intent_data.get("extracted_entities", {})
    query = state.get("user_message", "")

    search_results: list[dict] = []

    # 1. 商品知识库检索（优先级最高，数据最全）
    if product_knowledge:
        try:
            pk_results = await product_knowledge.search_product(query, limit=5)
            if pk_results:
                for r in pk_results:
                    search_results.append(
                        {
                            "id": r["spu_id"],
                            "name": r["name"],
                            "description": (
                                f"分类: {r['category']} | 品牌: {r['brand']} | "
                                f"规格: {r['spec']} | 价格: {r['price']}\n"
                                f"{r['description']}\n{r['image_text']}"
                            ).strip(),
                            "score": r["score"],
                            "source": "product_knowledge",
                        }
                    )
                logger.info(
                    f"Product knowledge returned {len(pk_results)} results for: {query[:50]}"
                )
        except Exception as e:
            logger.warning(f"Product knowledge search failed: {e}")

    # 2. Neo4j/PgVector 知识图谱检索（补充）
    if neo4j and embedding_skill:
        try:
            keywords: list[str] = []
            if isinstance(entities, dict):
                for v in entities.values():
                    if isinstance(v, list):
                        keywords.extend(str(i) for i in v)
                    elif v:
                        keywords.append(str(v))
            if not keywords:
                keywords = [w for w in query.split() if len(w) > 1]

            query_vec = embedding_skill.embed(query)
            results = await neo4j.hybrid_search(
                query=query,
                query_embedding=query_vec,
                keywords=keywords,
                limit=20,
            )
            kg_results = [r.model_dump() for r in results]
            # Deduplicate by id
            existing_ids = {r["id"] for r in search_results}
            for r in kg_results:
                if r.get("id") not in existing_ids:
                    r["source"] = "knowledge_graph"
                    search_results.append(r)
            logger.info(f"KG search returned {len(kg_results)} results for: {query[:50]}")
        except Exception as e:
            logger.error(f"KG hybrid search failed: {e}")

    if not search_results:
        logger.warning("No search results from any source")

    logger.info(f"Total search results: {len(search_results)} for: {query[:50]}")
    return {"search_results": search_results}


async def reranker_node(state: CustomerServiceState) -> dict:
    """Reranker: BGE 精排 Top 5。"""
    from .skills_registry import get_reranker

    reranker = get_reranker()
    candidates = state.get("search_results", [])
    query = state.get("user_message", "")

    if not reranker or not candidates:
        logger.info(
            f"Reranker skip: reranker={'yes' if reranker else 'no'}, candidates={len(candidates)}"
        )
        return {"reranked_results": candidates[:5]}

    try:
        reranked = reranker.rerank(
            query=query, documents=candidates, text_field="description", top_k=5
        )
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
        for item, graph in zip(reranked, graphs, strict=False):
            enriched_item = dict(item)
            if isinstance(graph, Exception):
                logger.warning(f"Graph fetch failed for {item.get('id')}: {graph}")
            elif graph is not None:
                enriched_item.update(
                    {
                        "suitable_for": graph.suitable_for,
                        "contraindicated_for": [
                            c for c in graph.contraindicated_for if c.get("name")
                        ],
                        "scenarios": graph.scenarios,
                        "related_products": graph.related_products,
                        "faqs": graph.faqs,
                        "price": graph.price,
                    }
                )
            enriched.append(enriched_item)

        logger.info(f"GraphRAG enriched {len(enriched)} products")
        return {"enriched_results": enriched}

    except Exception as e:
        logger.error(f"GraphRAG failed, using raw reranked results: {e}")
        return {"enriched_results": reranked, "errors": [f"graphrag: {e}"]}


async def reply_generation_node(state: CustomerServiceState) -> dict:
    """Reply Sub-Agent: 生成回复（使用 Sonnet）

    融合:
      - 知识库中的标准回答作为参考
      - 客户画像：高价值客户语气更重视
      - 自动记录对话日志用于后续分析
    """
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
        pool = state.get("db_pool")
        user_message = state["user_message"]

        # 检索知识库中的相关知识
        intent_name = state.get("intent", {}).get("intent", "")
        kb_results = await _search_knowledge_base(pool, user_message, intent_name)
        kb_context = ""
        if kb_results:
            # 格式化知识库结果为上下文
            kb_items = []
            for kb in kb_results[:3]:  # 取前3个最相关的
                if kb.get("question"):
                    kb_items.append(f"Q: {kb['question']}\nA: {kb['answer']}")
                else:
                    kb_items.append(f"知识: {kb['answer']}")
            kb_context = "\n\n# 知识库参考（客服标准回答）:\n" + "\n---\n".join(kb_items)

        # 新增: 获取待处理订单上下文（来自 qnh_orders_raw）
        orders_data = await fetch_latest_raw(pool, "qnh_orders_raw")
        order_context = ""
        if orders_data:
            # 提取待处理订单数等关键信息
            if isinstance(orders_data, dict):
                pending = orders_data.get("pendingCount", orders_data.get("待处理", 0))
                if pending:
                    order_context = f"\n\n# 当前待处理订单数: {pending}"
            elif isinstance(orders_data, list):
                order_context = f"\n\n# 当前待处理订单: {len(orders_data)} 条"

        # 新增: 获取热销商品信息（来自 qnh_products_raw，客服推荐用）
        hotsale_data = await fetch_latest_raw(pool, "qnh_products_raw")
        hotsale_context = ""
        if hotsale_data:
            top_items = hotsale_data[:5] if isinstance(hotsale_data, list) else [hotsale_data]
            names = [
                item.get("productName", item.get("name", ""))
                for item in top_items
                if item.get("productName") or item.get("name")
            ]
            if names:
                hotsale_context = f"\n\n# 当前热销商品（可推荐给客户）: {', '.join(names[:5])}"

        # 查询客户画像
        phone_tail = state.get("customer_phone_tail")
        customer = await _get_customer_profile(pool, phone_tail)
        customer_context = ""
        if customer:
            amount = float(customer.get("total_amount", 0))
            if amount >= 1000:
                customer_context = (
                    f"\n\n# 客户画像: 高价值客户（累计消费{amount:.0f}元，"
                    f"下单{customer.get('order_count', 0)}次）。"
                    f"请用更尊重、更重视的语气回复，优先处理。"
                )
            elif amount >= 300:
                customer_context = f"\n\n# 客户画像: 回头客（累计消费{amount:.0f}元）。"

        prompt = reply_prompt(
            user_message=user_message
            + kb_context
            + customer_context
            + order_context
            + hotsale_context,
            intent=json.dumps(state.get("intent", {}), ensure_ascii=False),
            retrieved_products_with_graph=json.dumps(enriched, ensure_ascii=False),
        )
        result = await call_tool(prompt, REPLY_TOOL, model=MODEL_SONNET)

        # 高价值客户标记需要人工审核以确保服务质量
        if customer and float(customer.get("total_amount", 0)) >= 2000:
            result["vip_customer"] = True

        # 记录对话日志
        await _log_conversation(
            pool=pool,
            session_id=state.get("session_id"),
            user_message=user_message,
            intent=intent_name,
            ai_response=result.get("reply_text", ""),
            matched_kb_ids=[kb.get("id") for kb in kb_results if kb.get("id")],
            matched_product_ids=[p.get("id") for p in enriched if p.get("id")],
            confidence=result.get("confidence", 0.0),
        )

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
    """转人工处理 — 仅用于严重投诉/法律威胁场景"""
    reason = state.get("intent", {}).get("human_reason", "用户需求需要人工处理")
    return {
        "reply": {
            "reply_text": "亲，非常抱歉给您带来不好的体验🙏 您的问题我们非常重视，已为您转接专属客服处理，请稍等。我们一定给您一个满意的答复！",
            "confidence": 1.0,
            "requires_human_review": True,
            "review_reason": reason,
        }
    }
