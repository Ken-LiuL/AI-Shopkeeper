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
        try:
            async with self._driver.session() as session:
                result = await session.run(query, params)
                return [record.data() async for record in result]
        except Exception:
            return []

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

    # ── 向量索引写入 ──────────────────────────────────────────────────────

    async def index_product(
        self,
        product_id: str,
        name: str,
        description: str,
        embedding: list[float],
    ) -> bool:
        """将商品及其向量写入 Neo4j（MERGE 幂等）。"""
        query = """
        MERGE (p:Product {product_id: $product_id})
        SET p.name = $name,
            p.description = $description,
            p.embedding = $embedding
        RETURN p.product_id AS id
        """
        rows = await self._execute(
            query,
            product_id=product_id,
            name=name,
            description=description,
            embedding=embedding,
        )
        return len(rows) > 0

    # ── 向量检索（简化接口，返回 list[dict]）────────────────────────────

    async def search_similar(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        index_name: str = "product_embedding_index",
    ) -> list[dict]:
        """从 Neo4j 向量索引检索最相似的商品，返回 list[dict]。

        Returns:
            [{"id": ..., "name": ..., "description": ..., "score": ...}, ...]
        """
        results = await self.vector_search(
            query_embedding=query_embedding,
            index_name=index_name,
            limit=top_k,
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "score": r.score,
            }
            for r in results
        ]

    # ── GraphRAG Service 统一查询层 ──────────────────────────────────────

    async def get_impact_chain(self, product_id: str, depth: int = 2) -> list[dict]:
        """Alert Agent 调用：分析异常商品的影响传播链。"""
        safe_depth = max(1, min(int(depth), 5))
        query = f"""
        MATCH path = (source:Product {{product_id: $product_id}})-[:OFTEN_BOUGHT_WITH*1..{safe_depth}]-(affected:Product)
        WHERE affected.product_id <> $product_id
        RETURN affected.product_id AS product_id,
               affected.name AS name,
               affected.price AS price,
               affected.stock AS stock,
               length(path) AS distance,
               CASE WHEN affected.stock < 10 THEN 'high' ELSE 'medium' END AS risk_level
        ORDER BY distance, affected.stock
        """
        try:
            return await self._execute(query, product_id=product_id)
        except Exception:
            return []

    async def find_category_gaps(self) -> list[dict]:
        """Selection Agent 调用：发现竞品有但我方未覆盖的品类商品缺口。"""
        query = """
        MATCH (c:Competitor)
        WHERE NOT EXISTS {
            MATCH (p:Product) WHERE p.name CONTAINS c.product_name
        }
        RETURN c.product_name AS product_name,
               c.store_name AS store_name,
               c.price AS price
        ORDER BY c.price DESC
        """
        try:
            return await self._execute(query)
        except Exception:
            return []

    async def find_scenario_gaps(self) -> list[dict]:
        """Selection Agent 调用：发现商品未覆盖到的使用场景。"""
        query = """
        MATCH (s:Scenario)
        WHERE NOT EXISTS { MATCH (:Product)-[:USED_IN]->(s) }
        RETURN s.name AS name, s.description AS description
        """
        try:
            return await self._execute(query)
        except Exception:
            return []

    async def get_scenario_bundles(
        self, scenario_name: str | None = None, limit: int = 10
    ) -> list[dict]:
        """Bundle Agent 调用：基于场景和共购关系返回套餐候选组合。"""
        query = """
        MATCH (p1:Product)-[:USED_IN]->(s:Scenario)<-[:USED_IN]-(p2:Product)
        WHERE p1.product_id < p2.product_id
          AND ($scenario_name IS NULL OR s.name = $scenario_name)
        OPTIONAL MATCH (p1)-[bought:OFTEN_BOUGHT_WITH]-(p2)
        WITH p1, p2, s, bought
        WHERE bought IS NOT NULL OR s IS NOT NULL
        RETURN s.name AS scenario,
               p1.name AS product_1, p1.price AS price_1,
               p2.name AS product_2, p2.price AS price_2,
               bought.co_occurrence AS co_purchase_count
        ORDER BY co_purchase_count DESC NULLS LAST
        LIMIT $limit
        """
        try:
            return await self._execute(
                query, scenario_name=scenario_name, limit=limit
            )
        except Exception:
            return []

    async def suggest_category(self, product_name: str) -> list[dict]:
        """Listing Agent 调用：根据商品名称推荐最可能的类目。"""
        query = """
        CALL db.index.fulltext.queryNodes('product_fulltext_index', $name)
        YIELD node, score
        MATCH (node)-[:BELONGS_TO]->(c:Category)
        RETURN c.name AS category, count(*) AS freq, avg(score) AS relevance
        ORDER BY freq DESC, relevance DESC
        LIMIT 5
        """
        try:
            return await self._execute(query, name=product_name)
        except Exception:
            return []

    async def get_category_tree(self, category_name: str) -> dict:
        """Listing Agent 调用：获取类目及其子类目树（最多 3 层）。"""
        query = """
        MATCH path = (c:Category {name: $name})-[:PARENT_OF*0..3]->(child:Category)
        RETURN [node in nodes(path) | node.name] AS hierarchy
        """
        try:
            rows = await self._execute(query, name=category_name)
        except Exception:
            return {}
        if not rows:
            return {}
        return {
            "category": category_name,
            "hierarchies": [r.get("hierarchy", []) for r in rows],
        }

    async def get_deep_context(self, product_id: str) -> dict:
        """Customer Service Agent 调用：获取增强版 3 跳商品上下文与竞品信息。"""
        query = """
        MATCH (p:Product {product_id: $product_id})
        OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(pop:Population)
        OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
        OPTIONAL MATCH (p)-[:OFTEN_BOUGHT_WITH]-(related:Product)
        OPTIONAL MATCH (p)-[:COMPETES_WITH]->(comp:Competitor)
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
        OPTIONAL MATCH (p)-[:PEAKS_IN]->(season:Season)
        OPTIONAL MATCH (faq:FAQ)-[:ANSWERS]->(p)
        RETURN p { .* } AS product,
               collect(DISTINCT {name: pop.name, description: pop.description}) AS populations,
               collect(DISTINCT {name: scenario.name, description: scenario.description}) AS scenarios,
               collect(DISTINCT {name: related.name, price: related.price, stock: related.stock}) AS related,
               collect(DISTINCT {store: comp.store_name, name: comp.product_name, price: comp.price}) AS competitors,
               cat.name AS category,
               collect(DISTINCT season.name) AS seasons,
               collect(DISTINCT {q: faq.question, a: faq.answer}) AS faqs
        """
        try:
            row = await self._execute_single(query, product_id=product_id)
        except Exception:
            return {}
        if not row:
            return {}
        return row

    async def get_graph_stats(self) -> dict:
        """前端/API 调用：返回图谱节点和关系统计信息。"""
        query = """
        MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count
        UNION ALL
        MATCH ()-[r]->() RETURN type(r) AS label, count(r) AS count
        """
        try:
            rows = await self._execute(query)
        except Exception:
            return {}
        if not rows:
            return {}
        return {
            "stats": rows,
            "total": sum(int(item.get("count", 0) or 0) for item in rows),
        }


# asyncio imported at top for gather in hybrid_search
