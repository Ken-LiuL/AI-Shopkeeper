"""Neo4j Skill — 图谱查询 + 向量检索 + GraphRAG。"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

# ── Pydantic Models ──────────────────────────────────────────────────────────


class VectorSearchResult(BaseModel):
    id: str
    name: str
    description: str = ""
    score: float


class KeywordSearchResult(BaseModel):
    id: str
    name: str
    description: str = ""
    score: float


class ProductGraph(BaseModel):
    product_id: str
    name: str
    description: str = ""
    price: float = 0.0
    suitable_for: list[str] = Field(default_factory=list)
    contraindicated_for: list[dict[str, str]] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    related_products: list[dict[str, Any]] = Field(default_factory=list)
    faqs: list[dict[str, str]] = Field(default_factory=list)


class RelatedProduct(BaseModel):
    product_id: str
    name: str
    price: float = 0.0
    relation: str = ""


class Population(BaseModel):
    name: str
    description: str = ""


class Neo4jSkill:
    """Neo4j 图谱 + 向量检索技能。"""

    def __init__(self, driver: Any = None):
        """
        Args:
            driver: neo4j.AsyncDriver instance (injected).
        """
        self._driver = driver

    # ── helpers ───────────────────────────────────────────────────────────

    async def _execute(self, query: str, **params: Any) -> list[dict[str, Any]]:
        if self._driver is None:
            return []
        async with self._driver.session() as session:
            result = await session.run(query, params)
            return [record.data() async for record in result]

    async def _execute_single(self, query: str, **params: Any) -> dict[str, Any] | None:
        rows = await self._execute(query, **params)
        return rows[0] if rows else None

    # ── 向量检索 ─────────────────────────────────────────────────────────

    async def vector_search(
        self,
        query_embedding: list[float],
        index_name: str = "product_embedding_index",
        limit: int = 10,
    ) -> list[VectorSearchResult]:
        """向量语义检索。"""
        query = """
        CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
        YIELD node, score
        RETURN node.product_id AS id, node.name AS name,
               node.description AS description, score
        """
        rows = await self._execute(
            query, index_name=index_name, embedding=query_embedding, limit=limit
        )
        return [VectorSearchResult(**r) for r in rows]

    # ── 关键词检索 ───────────────────────────────────────────────────────

    async def keyword_search(
        self,
        keywords: list[str],
        limit: int = 10,
    ) -> list[KeywordSearchResult]:
        """关键词全文检索。"""
        keyword_pattern = "|".join(keywords)
        query = """
        CALL db.index.fulltext.queryNodes('product_fulltext_index', $pattern)
        YIELD node, score
        RETURN node.product_id AS id, node.name AS name,
               node.description AS description, score
        LIMIT $limit
        """
        rows = await self._execute(query, pattern=keyword_pattern, limit=limit)
        return [KeywordSearchResult(**r) for r in rows]

    # ── RRF 融合 ─────────────────────────────────────────────────────────

    @staticmethod
    def _rrf_merge(
        vector_results: list[VectorSearchResult],
        keyword_results: list[KeywordSearchResult],
        k: int = 60,
    ) -> list[VectorSearchResult]:
        """Reciprocal Rank Fusion 合并两路检索结果。"""
        scores: dict[str, float] = {}
        items: dict[str, VectorSearchResult] = {}

        for rank, item in enumerate(vector_results, start=1):
            scores[item.id] = scores.get(item.id, 0) + 1.0 / (k + rank)
            items[item.id] = item

        for rank, item in enumerate(keyword_results, start=1):
            scores[item.id] = scores.get(item.id, 0) + 1.0 / (k + rank)
            if item.id not in items:
                items[item.id] = VectorSearchResult(
                    id=item.id,
                    name=item.name,
                    description=item.description,
                    score=item.score,
                )

        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        for sid in sorted_ids:
            items[sid].score = scores[sid]
        return [items[sid] for sid in sorted_ids]

    # ── 混合检索 ─────────────────────────────────────────────────────────

    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        keywords: list[str],
        limit: int = 10,
    ) -> list[VectorSearchResult]:
        """混合检索：向量 + 关键词 + RRF 融合。"""
        vector_results, keyword_results = await asyncio.gather(
            self.vector_search(query_embedding, limit=30),
            self.keyword_search(keywords, limit=30),
        )
        merged = self._rrf_merge(vector_results, keyword_results)
        return merged[:limit]

    # ── GraphRAG ─────────────────────────────────────────────────────────

    async def get_product_graph(self, product_id: str) -> ProductGraph | None:
        """GraphRAG：获取商品完整关联子图。"""
        query = """
        MATCH (p:Product {product_id: $product_id})
        OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(suitable:Population)
        OPTIONAL MATCH (p)-[contra_rel:CONTRAINDICATED_FOR]->(contra:Population)
        OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
        OPTIONAL MATCH (p)-[bought:OFTEN_BOUGHT_WITH]->(related:Product)
        OPTIONAL MATCH (faq:FAQ)-[:ANSWERS]->(p)

        RETURN p.product_id AS product_id,
               p.name AS name,
               p.description AS description,
               p.price AS price,
               collect(DISTINCT suitable.name) AS suitable_for,
               collect(DISTINCT {name: contra.name, reason: contra_rel.reason}) AS contraindicated_for,
               collect(DISTINCT scenario.name) AS scenarios,
               collect(DISTINCT {id: related.product_id, name: related.name, price: related.price})[0..3] AS related_products,
               collect(DISTINCT {question: faq.question, answer: faq.answer})[0..5] AS faqs
        """
        row = await self._execute_single(query, product_id=product_id)
        if not row:
            return None
        return ProductGraph(**row)

    async def get_suitable_population(self, product_id: str) -> list[Population]:
        """获取商品适用人群。"""
        query = """
        MATCH (p:Product {product_id: $product_id})-[:SUITABLE_FOR]->(pop:Population)
        RETURN pop.name AS name, pop.description AS description
        """
        rows = await self._execute(query, product_id=product_id)
        return [Population(**r) for r in rows]

    async def get_related_products(self, product_id: str, limit: int = 5) -> list[RelatedProduct]:
        """获取关联商品。"""
        query = """
        MATCH (p:Product {product_id: $product_id})-[r]->(related:Product)
        RETURN related.product_id AS product_id, related.name AS name,
               related.price AS price, type(r) AS relation
        LIMIT $limit
        """
        rows = await self._execute(query, product_id=product_id, limit=limit)
        return [RelatedProduct(**r) for r in rows]

    # ── 写入操作 ─────────────────────────────────────────────────────────

    async def add_product(
        self,
        product_id: str,
        name: str,
        description: str = "",
        price: float = 0.0,
        embedding: list[float] | None = None,
        **extra: Any,
    ) -> bool:
        """添加商品节点。"""
        props = {
            "product_id": product_id,
            "name": name,
            "description": description,
            "price": price,
            **extra,
        }
        if embedding is not None:
            props["embedding"] = embedding
        query = """
        MERGE (p:Product {product_id: $props.product_id})
        SET p += $props
        RETURN p.product_id AS id
        """
        rows = await self._execute(query, props=props)
        return len(rows) > 0

    async def add_relationship(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """添加两个节点间的关系。"""
        props = properties or {}
        query = f"""
        MATCH (a:Product {{product_id: $from_id}})
        MATCH (b:Product {{product_id: $to_id}})
        MERGE (a)-[r:{relation_type}]->(b)
        SET r += $props
        RETURN type(r) AS rel
        """
        rows = await self._execute(query, from_id=from_id, to_id=to_id, props=props)
        return len(rows) > 0

    async def update_embedding(
        self,
        product_id: str,
        embedding: list[float],
    ) -> bool:
        """更新商品向量。"""
        query = """
        MATCH (p:Product {product_id: $product_id})
        SET p.embedding = $embedding
        RETURN p.product_id AS id
        """
        rows = await self._execute(query, product_id=product_id, embedding=embedding)
        return len(rows) > 0


# asyncio imported at top for gather in hybrid_search
