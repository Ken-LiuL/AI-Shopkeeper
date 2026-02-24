"""PgVector Skill — PostgreSQL pgvector 向量检索 + 全文检索。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .neo4j_skill import (
    KeywordSearchResult,
    Population,
    ProductGraph,
    RelatedProduct,
    VectorSearchResult,
)

logger = logging.getLogger(__name__)


class PgVectorSkill:
    """PostgreSQL pgvector 向量 + 全文混合检索技能。

    接口与 Neo4jSkill 完全一致，可作为 drop-in replacement。
    """

    def __init__(self, pool: Any = None):
        """
        Args:
            pool: asyncpg.Pool instance (injected).
        """
        self._pool = pool

    # ── helpers ───────────────────────────────────────────────────────────

    async def _fetch(self, query: str, *args: Any) -> List[Dict[str, Any]]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]

    async def _fetchrow(self, query: str, *args: Any) -> Optional[Dict[str, Any]]:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    # ── 向量检索 ─────────────────────────────────────────────────────────

    async def vector_search(
        self,
        query_embedding: List[float],
        index_name: str = "product_embedding_index",
        limit: int = 10,
    ) -> List[VectorSearchResult]:
        """向量语义检索（cosine similarity）。"""
        # pgvector uses <=> for cosine distance; score = 1 - distance
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        query = """
        SELECT product_id AS id, name, COALESCE(description, '') AS description,
               1 - (embedding <=> $1::vector) AS score
        FROM kg_products
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """
        rows = await self._fetch(query, embedding_str, limit)
        return [VectorSearchResult(**r) for r in rows]

    # ── 关键词检索 ───────────────────────────────────────────────────────

    async def keyword_search(
        self,
        keywords: List[str],
        limit: int = 10,
    ) -> List[KeywordSearchResult]:
        """关键词全文检索（tsvector）。"""
        if not keywords:
            return []
        # Build tsquery: join keywords with |
        tsquery = " | ".join(keywords)
        query = """
        SELECT product_id AS id, name, COALESCE(description, '') AS description,
               ts_rank(fts, to_tsquery('simple', $1)) AS score
        FROM kg_products
        WHERE fts @@ to_tsquery('simple', $1)
        ORDER BY score DESC
        LIMIT $2
        """
        rows = await self._fetch(query, tsquery, limit)
        return [KeywordSearchResult(**r) for r in rows]

    # ── RRF 融合（复用 Neo4jSkill 的静态方法）──────────────────────────

    @staticmethod
    def _rrf_merge(
        vector_results: List[VectorSearchResult],
        keyword_results: List[KeywordSearchResult],
        k: int = 60,
    ) -> List[VectorSearchResult]:
        """Reciprocal Rank Fusion 合并两路检索结果。"""
        scores: Dict[str, float] = {}
        items: Dict[str, VectorSearchResult] = {}

        for rank, item in enumerate(vector_results, start=1):
            scores[item.id] = scores.get(item.id, 0) + 1.0 / (k + rank)
            items[item.id] = item

        for rank, item in enumerate(keyword_results, start=1):
            scores[item.id] = scores.get(item.id, 0) + 1.0 / (k + rank)
            if item.id not in items:
                items[item.id] = VectorSearchResult(
                    id=item.id, name=item.name,
                    description=item.description, score=item.score,
                )

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        for sid in sorted_ids:
            items[sid].score = scores[sid]
        return [items[sid] for sid in sorted_ids]

    # ── 混合检索 ─────────────────────────────────────────────────────────

    async def hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        keywords: List[str],
        limit: int = 10,
    ) -> List[VectorSearchResult]:
        """混合检索：向量 + 关键词 + RRF 融合。"""
        vector_results, keyword_results = await asyncio.gather(
            self.vector_search(query_embedding, limit=30),
            self.keyword_search(keywords, limit=30),
        )
        merged = self._rrf_merge(vector_results, keyword_results)
        return merged[:limit]

    # ── GraphRAG ─────────────────────────────────────────────────────────

    async def get_product_graph(self, product_id: str) -> Optional[ProductGraph]:
        """获取商品完整关联信息（从 PostgreSQL 关系表）。"""
        # Main product
        product = await self._fetchrow(
            """SELECT product_id, name, COALESCE(description, '') AS description,
                      COALESCE(price, 0) AS price
               FROM kg_products WHERE product_id = $1""",
            product_id,
        )
        if not product:
            return None

        # Suitable populations
        suitable_rows = await self._fetch(
            """SELECT pop.name
               FROM kg_product_population pp
               JOIN kg_populations pop ON pop.id = pp.population_id
               WHERE pp.product_id = $1 AND pp.relation = 'suitable'""",
            product_id,
        )
        suitable_for = [r["name"] for r in suitable_rows]

        # Contraindicated populations
        contra_rows = await self._fetch(
            """SELECT pop.name, pp.reason
               FROM kg_product_population pp
               JOIN kg_populations pop ON pop.id = pp.population_id
               WHERE pp.product_id = $1 AND pp.relation = 'contraindicated'""",
            product_id,
        )
        contraindicated_for = [{"name": r["name"], "reason": r.get("reason", "")} for r in contra_rows]

        # Scenarios
        scenario_rows = await self._fetch(
            """SELECT s.name
               FROM kg_product_scenario ps
               JOIN kg_scenarios s ON s.id = ps.scenario_id
               WHERE ps.product_id = $1""",
            product_id,
        )
        scenarios = [r["name"] for r in scenario_rows]

        # Related products
        related_rows = await self._fetch(
            """SELECT p.product_id AS id, p.name, COALESCE(p.price, 0) AS price
               FROM kg_related_products rp
               JOIN kg_products p ON p.product_id = rp.related_product_id
               WHERE rp.product_id = $1
               LIMIT 3""",
            product_id,
        )
        related_products = [dict(r) for r in related_rows]

        # FAQs
        faq_rows = await self._fetch(
            """SELECT question, answer
               FROM kg_faqs
               WHERE product_id = $1
               LIMIT 5""",
            product_id,
        )
        faqs = [dict(r) for r in faq_rows]

        return ProductGraph(
            product_id=product["product_id"],
            name=product["name"],
            description=product["description"],
            price=product["price"],
            suitable_for=suitable_for,
            contraindicated_for=contraindicated_for,
            scenarios=scenarios,
            related_products=related_products,
            faqs=faqs,
        )

    async def get_suitable_population(self, product_id: str) -> List[Population]:
        """获取商品适用人群。"""
        rows = await self._fetch(
            """SELECT pop.name, COALESCE(pop.description, '') AS description
               FROM kg_product_population pp
               JOIN kg_populations pop ON pop.id = pp.population_id
               WHERE pp.product_id = $1 AND pp.relation = 'suitable'""",
            product_id,
        )
        return [Population(**r) for r in rows]

    async def get_related_products(self, product_id: str, limit: int = 5) -> List[RelatedProduct]:
        """获取关联商品。"""
        rows = await self._fetch(
            """SELECT p.product_id, p.name, COALESCE(p.price, 0) AS price,
                      rp.relation
               FROM kg_related_products rp
               JOIN kg_products p ON p.product_id = rp.related_product_id
               WHERE rp.product_id = $1
               LIMIT $2""",
            product_id, limit,
        )
        return [RelatedProduct(**r) for r in rows]

    # ── 写入操作 ─────────────────────────────────────────────────────────

    async def add_product(
        self,
        product_id: str,
        name: str,
        description: str = "",
        price: float = 0.0,
        embedding: Optional[List[float]] = None,
        **extra: Any,
    ) -> bool:
        """添加/更新商品。"""
        if self._pool is None:
            return False
        embedding_str = None
        if embedding is not None:
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO kg_products (product_id, name, description, price, embedding)
                   VALUES ($1, $2, $3, $4, $5::vector)
                   ON CONFLICT (product_id) DO UPDATE
                   SET name = EXCLUDED.name, description = EXCLUDED.description,
                       price = EXCLUDED.price,
                       embedding = COALESCE(EXCLUDED.embedding, kg_products.embedding)""",
                product_id, name, description, price, embedding_str,
            )
        return True

    async def update_embedding(
        self,
        product_id: str,
        embedding: List[float],
    ) -> bool:
        """更新商品向量。"""
        if self._pool is None:
            return False
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE kg_products SET embedding = $1::vector WHERE product_id = $2",
                embedding_str, product_id,
            )
        return "UPDATE 1" in result
