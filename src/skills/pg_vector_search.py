"""PostgreSQL pgvector 向量检索技能。

当 Neo4j 不可用时作为向量检索的 fallback 后端。
支持：
  1. pgvector `<->` 余弦距离向量搜索
  2. 若无 embedding 列 / 向量数据不足，降级为关键词 ILIKE 全文匹配
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def search_products_by_vector(
    pool,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """使用 pgvector <-> 余弦距离算子检索商品。

    Args:
        pool:            asyncpg 连接池
        query_embedding: 查询向量（1536维，text-embedding-3-small）
        top_k:           返回最多 top_k 条结果

    Returns:
        list of dicts with keys: id, name, category, brand, price, description, score
    """
    if pool is None:
        logger.warning("[PgVectorSearch] pool is None, cannot search")
        return []

    # ── 尝试 pgvector 向量检索 ────────────────────────────────────────
    try:
        # 将 Python list 转为 pgvector 期望的字符串表示
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        rows = await pool.fetch(
            """
            SELECT
                spu_id          AS id,
                name,
                category,
                brand,
                spec,
                retail_price    AS price,
                extra->>'description' AS description,
                1 - (embedding <-> $1::vector) AS score
            FROM qnh_products
            WHERE status != 'disabled'
              AND embedding IS NOT NULL
            ORDER BY embedding <-> $1::vector
            LIMIT $2
            """,
            embedding_str,
            top_k,
        )

        if rows:
            results = [
                {
                    "id": r["id"],
                    "name": r["name"] or "",
                    "category": r["category"] or "",
                    "brand": r["brand"] or "",
                    "spec": r["spec"] or "",
                    "price": float(r["price"] or 0),
                    "description": r["description"] or "",
                    "score": float(r["score"] or 0),
                }
                for r in rows
            ]
            logger.info(
                "[PgVectorSearch] pgvector returned %d results (top score=%.3f)",
                len(results),
                results[0]["score"] if results else 0,
            )
            return results

        logger.info("[PgVectorSearch] pgvector returned 0 results, falling back to keyword search")

    except Exception as e:
        # embedding 列不存在 / pgvector 未安装等情况
        logger.warning("[PgVectorSearch] pgvector query failed (%s), falling back to ILIKE", e)

    # ── Fallback：关键词 ILIKE 匹配 ───────────────────────────────────
    return await _keyword_fallback(pool, top_k=top_k)


async def _keyword_fallback(
    pool,
    keywords: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """基于关键词 ILIKE 的简单匹配，作为向量检索的最终 fallback。"""
    try:
        if keywords:
            # 构建 ILIKE 条件
            conditions = " OR ".join(
                f"(name ILIKE '%{kw}%' OR category ILIKE '%{kw}%')"
                for kw in keywords[:5]  # 最多5个关键词
            )
            where_clause = f"AND ({conditions})"
        else:
            where_clause = ""

        rows = await pool.fetch(
            f"""
            SELECT
                spu_id          AS id,
                name,
                category,
                brand,
                spec,
                retail_price    AS price,
                extra->>'description' AS description,
                0.5             AS score
            FROM qnh_products
            WHERE status != 'disabled'
            {where_clause}
            ORDER BY monthly_sales DESC NULLS LAST
            LIMIT $1
            """,
            top_k,
        )

        results = [
            {
                "id": r["id"],
                "name": r["name"] or "",
                "category": r["category"] or "",
                "brand": r["brand"] or "",
                "spec": r["spec"] or "",
                "price": float(r["price"] or 0),
                "description": r["description"] or "",
                "score": float(r["score"] or 0.5),
            }
            for r in rows
        ]
        logger.info("[PgVectorSearch] keyword fallback returned %d results", len(results))
        return results

    except Exception as e:
        logger.error("[PgVectorSearch] keyword fallback also failed: %s", e)
        return []


async def search_products_by_keywords(
    pool,
    keywords: list[str],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """直接关键词搜索（供外部调用）。"""
    return await _keyword_fallback(pool, keywords=keywords, top_k=top_k)
