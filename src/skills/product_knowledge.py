"""Product Knowledge — semantic search via OpenRouter embeddings + Postgres JSONB."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from .embedding import EmbeddingSkill

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class ProductKnowledgeSkill:
    """商品知识库语义搜索。"""

    def __init__(self, pool: Any = None, embedding: EmbeddingSkill | None = None):
        self._pool = pool
        self._embedding = embedding or EmbeddingSkill()

    async def search_product(
        self,
        query: str,
        limit: int = 5,
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        """语义搜索商品，fallback 到 SQL ILIKE。"""
        from src.db import postgres as pg

        pool = self._pool or pg.get_pool()
        if pool is None:
            return []

        # Try semantic search first
        try:
            result = await self._semantic_search(pool, query, limit)
            if result:
                return result
        except Exception as e:
            logger.warning("Semantic search failed, falling back to SQL: %s", e)

        # Fallback: SQL ILIKE
        return await self._sql_search(pool, query, limit)

    async def _semantic_search(self, pool: Any, query: str, limit: int) -> list[dict[str, Any]]:
        """Embed query, compute cosine similarity against all products."""
        # Check if we have embeddings
        count = await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE embedding IS NOT NULL")
        if count == 0:
            return []

        query_vec = self._embedding.embed(query)

        rows = await pool.fetch(
            """SELECT spu_id, name, category, brand, spec, retail_price, status, image_url, embedding
               FROM qnh_products WHERE embedding IS NOT NULL"""
        )

        scored = []
        for r in rows:
            emb = r["embedding"]
            if isinstance(emb, str):
                emb = json.loads(emb)
            if not emb:
                continue
            score = _cosine_similarity(query_vec, emb)
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        items = []
        for score, r in scored[:limit]:
            items.append(
                {
                    "spu_id": r["spu_id"],
                    "name": r["name"] or "",
                    "category": r["category"] or "",
                    "brand": r["brand"] or "",
                    "spec": r["spec"] or "",
                    "description": "",
                    "image_text": "",
                    "price": float(r["retail_price"]) if r["retail_price"] else None,
                    "status": r["status"] or "",
                    "image_urls": [r["image_url"]] if r.get("image_url") else [],
                    "score": round(score, 4),
                }
            )
        return items

    async def _sql_search(self, pool: Any, query: str, limit: int) -> list[dict[str, Any]]:
        like_query = f"%{query}%"
        rows = await pool.fetch(
            """SELECT spu_id, name, category, brand, spec, retail_price, status, image_url
               FROM qnh_products
               WHERE name ILIKE $1 OR brand ILIKE $1 OR spec ILIKE $1 OR category ILIKE $1
               LIMIT $2""",
            like_query,
            limit,
        )
        return [
            {
                "spu_id": r["spu_id"],
                "name": r["name"] or "",
                "category": r["category"] or "",
                "brand": r["brand"] or "",
                "spec": r["spec"] or "",
                "description": "",
                "image_text": "",
                "price": float(r["retail_price"]) if r["retail_price"] else None,
                "status": r["status"] or "",
                "image_urls": [r["image_url"]] if r.get("image_url") else [],
                "score": 1.0,
            }
            for r in rows
        ]


async def build_embeddings(pool: Any, embedding: EmbeddingSkill | None = None) -> dict:
    """为所有缺少 embedding 的商品构建向量，批量处理。"""
    emb = embedding or EmbeddingSkill()

    rows = await pool.fetch(
        """SELECT spu_id, name, category, brand, spec
           FROM qnh_products WHERE embedding IS NULL"""
    )
    if not rows:
        logger.info("All products already have embeddings")
        return {"total": 0, "updated": 0, "errors": 0}

    logger.info("Building embeddings for %d products…", len(rows))
    total = len(rows)
    updated = 0
    errors = 0
    batch_size = 50

    for i in range(0, total, batch_size):
        chunk = rows[i : i + batch_size]
        texts = []
        for r in chunk:
            text = " ".join(
                filter(
                    None,
                    [
                        r["name"] or "",
                        r["brand"] or "",
                        r["category"] or "",
                        r["spec"] or "",
                    ],
                )
            )
            texts.append(text or "unknown")

        try:
            embeddings = emb.embed_batch(texts)
        except Exception as e:
            logger.error("Embedding batch %d failed: %s", i, e)
            errors += len(chunk)
            continue

        for r, vec in zip(chunk, embeddings, strict=False):
            try:
                await pool.execute(
                    "UPDATE qnh_products SET embedding = $1::jsonb WHERE spu_id = $2",
                    json.dumps(vec),
                    r["spu_id"],
                )
                updated += 1
            except Exception as e:
                logger.error("Update embedding for %s failed: %s", r["spu_id"], e)
                errors += 1

        logger.info("Embeddings: %d/%d done", min(i + batch_size, total), total)

    logger.info("Embedding build complete: %d updated, %d errors", updated, errors)
    return {"total": total, "updated": updated, "errors": errors}
