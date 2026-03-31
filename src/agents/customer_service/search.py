"""检索管线模块 — Hybrid Search → Reranker → GraphRAG 子图丰富。

对应 SPEC 4.3 Hybrid Search + 2.5 Reranker + 2.4 GraphRAG。

管线：
1. 向量检索 (Neo4j/PgVector) + 关键词检索 → 召回 ~50 条
2. Reranker (BGE CrossEncoder) → 精排 Top 5
3. GraphRAG (Neo4j 子图) → 丰富商品知识图谱
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


async def full_pipeline_search(message: str, pool=None) -> list[dict]:
    """完整检索管线：向量+关键词 Hybrid Search → Reranker → GraphRAG 子图丰富。

    This is the core retrieval pipeline per SPEC 4.3.
    """
    if not pool:
        return []

    # ── Step 1-2: 向量检索 ──────────────────────────────────
    async def _vector_search():
        try:
            from src.agents.customer_service.skills_registry import get_skills

            skills = get_skills()
            embedding_skill = skills.get("embedding")
            neo4j_skill = skills.get("vector_store")
            if not embedding_skill or not neo4j_skill:
                return []
            query_embedding = embedding_skill.embed(message)
            vec_results = await neo4j_skill.vector_search(query_embedding, limit=10)
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "score": r.score,
                    "source": "vector",
                }
                for r in vec_results
            ]
        except Exception as e:
            logger.warning("[Search] Vector search failed: %s", e)
            return []

    # ── Step 3: 关键词检索 ──────────────────────────────────
    async def _keyword_search():
        try:
            from src.agents.customer_service.skills_registry import get_skills

            skills = get_skills()
            neo4j_skill = skills.get("vector_store")
            if not neo4j_skill:
                return []
            # 提取关键词
            keywords = _extract_keywords(message)
            if not keywords:
                return []
            kw_results = await neo4j_skill.keyword_search(keywords, limit=10)
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "score": r.score,
                    "source": "keyword",
                }
                for r in kw_results
            ]
        except Exception as e:
            logger.warning("[Search] Keyword search failed: %s", e)
            return []

    # 并行执行向量和关键词检索
    vec_task = asyncio.create_task(_vector_search())
    kw_task = asyncio.create_task(_keyword_search())

    vec_results, kw_results = await asyncio.gather(vec_task, kw_task)

    # ── Step 3.5: RRF 融合 ──────────────────────────────────
    merged = _rrf_merge(vec_results, kw_results, k=60)
    if not merged:
        return []

    merged_dicts = merged[:20]  # 取 top 20 进 Reranker

    # ── Step 4: Reranker 精排 ──────────────────────────────
    reranked: list[dict] = []
    try:
        from src.skills.reranker import RerankerSkill

        loop = asyncio.get_event_loop()
        reranker = RerankerSkill()
        reranked = await loop.run_in_executor(
            None,
            lambda: reranker.rerank(message, merged_dicts, top_k=5),
        )
        logger.info("[Search] Reranker returned %d results", len(reranked))
    except Exception as e:
        logger.warning("[Search] Reranker failed (fallback to top-5 RRF): %s", e)
        reranked = merged_dicts[:5]

    if not reranked:
        reranked = merged_dicts[:5]

    # ── Step 5: GraphRAG 子图丰富 ──────────────────────────
    enriched = await _graphrag_enrich(reranked)

    return enriched


def _extract_keywords(message: str) -> list[str]:
    """从用户消息中提取搜索关键词。"""
    import re

    # 简单分词 + 过滤停用词
    stopwords = {"的", "了", "吗", "呢", "啊", "吧", "是", "有", "在", "我", "你", "他",
                 "她", "它", "和", "与", "或", "不", "很", "也", "都", "这", "那", "什么",
                 "怎么", "哪", "多少", "可以", "能", "想", "要", "请", "问", "一个", "一下"}
    words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", message)
    keywords = [w for w in words if w not in stopwords and len(w) >= 2]
    return keywords[:10]


def _rrf_merge(
    vec_results: list[dict],
    kw_results: list[dict],
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion 合并两路检索结果。"""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for rank, item in enumerate(vec_results):
        item_id = item.get("id", item.get("name", ""))
        scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
        items[item_id] = item

    for rank, item in enumerate(kw_results):
        item_id = item.get("id", item.get("name", ""))
        scores[item_id] = scores.get(item_id, 0) + 1.0 / (k + rank + 1)
        if item_id not in items:
            items[item_id] = item

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [items[item_id] for item_id in sorted_ids if item_id in items]


async def _graphrag_enrich(products: list[dict]) -> list[dict]:
    """GraphRAG 子图丰富 — 从 Neo4j 获取完整商品知识图谱。"""
    try:
        from src.agents.customer_service.skills_registry import get_skills

        skills = get_skills()
        neo4j_skill = skills.get("vector_store")
        if not neo4j_skill or not hasattr(neo4j_skill, "get_product_graph"):
            return products

        async def _enrich_one(product: dict) -> dict:
            product_id = product.get("id", "")
            if not product_id:
                return product
            try:
                graph = await neo4j_skill.get_product_graph(product_id)
                if graph:
                    product["graph_data"] = {
                        "faqs": getattr(graph, "faqs", []),
                        "related_products": getattr(graph, "related_products", []),
                        "suitable_for": getattr(graph, "suitable_for", []),
                        "scenarios": getattr(graph, "scenarios", []),
                        "contraindicated_for": getattr(graph, "contraindicated_for", []),
                    }
            except Exception as e:
                logger.debug("[Search] GraphRAG enrichment failed for %s: %s", product_id, e)
            return product

        enriched = await asyncio.gather(
            *(_enrich_one(p) for p in products),
            return_exceptions=True,
        )
        return [r if isinstance(r, dict) else products[i] for i, r in enumerate(enriched)]

    except Exception as e:
        logger.warning("[Search] GraphRAG module not available: %s", e)
        return products


def build_retrieval_cache_key(
    session_id: str,
    message: str,
    conversation_history: list[dict] | None = None,
    quick_intent: str = "",
) -> str:
    """构建检索结果缓存 key。"""
    parts = [session_id, message, quick_intent]
    if conversation_history:
        last_msgs = [str(m.get("content", ""))[:50] for m in conversation_history[-2:]]
        parts.extend(last_msgs)
    raw = "|".join(parts)
    return f"cs:retrieval:{hashlib.md5(raw.encode()).hexdigest()}"


async def load_cached_retrieval(redis_client, cache_key: str) -> list[dict] | None:
    """从 Redis 加载缓存的检索结果。"""
    if not redis_client:
        return None
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None


async def store_cached_retrieval(redis_client, cache_key: str, results: list[dict]) -> None:
    """缓存检索结果到 Redis。"""
    if not redis_client or not results:
        return
    with contextlib.suppress(Exception):
        await redis_client.setex(cache_key, 300, json.dumps(results, default=str))
