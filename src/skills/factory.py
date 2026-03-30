"""
Skills 工厂：统一创建和注入 skills 实例
支持 mock 模式和 production 模式
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .calculator import CalculatorSkill
from .database import DatabaseSkill

# ── Mock Skills for Customer Service ─────────────────────────────────────────


class MockEmbeddingSkill:
    """Mock embedding skill — returns fixed-dimension zero vectors."""

    def __init__(self, dimension: int = 1024):
        self._dimension = dimension

    def embed(self, text: str) -> list[float]:
        # Simple deterministic pseudo-embedding based on text hash
        import hashlib

        h = hashlib.md5(text.encode()).hexdigest()
        base = [int(c, 16) / 15.0 for c in h]
        # Repeat to fill dimension
        vec = (base * (self._dimension // len(base) + 1))[: self._dimension]
        return vec

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    @property
    def dimension(self) -> int:
        return self._dimension


class MockRerankerSkill:
    """Mock reranker — returns documents in original order."""

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        text_field: str = "description",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return documents[:top_k]


class MockNeo4jSkill:
    """Mock Neo4j skill with in-memory product graph data."""

    def __init__(self, products: list[dict[str, Any]] | None = None):
        self._products = products or self._default_products()

    @staticmethod
    def _default_products() -> list[dict[str, Any]]:
        return [
            {
                "product_id": "P001",
                "name": "鱼跃电子血压计YE680A",
                "description": "上臂式电子血压计，大屏显示，语音播报，适合中老年人使用。双人记忆，智能加压。",
                "price": 199.0,
                "suitable_for": ["中老年人", "高血压患者", "家庭健康监测"],
                "contraindicated_for": [
                    {"name": "严重心律不齐患者", "reason": "电子血压计测量可能不准确"}
                ],
                "scenarios": ["家庭日常监测", "送礼"],
                "related_products": [
                    {"id": "P002", "name": "欧姆龙体温计MC-246", "price": 39.9},
                    {"id": "P005", "name": "三诺血糖仪GA-3", "price": 89.0},
                ],
                "faqs": [
                    {
                        "question": "血压计怎么使用？",
                        "answer": "1.静坐5分钟 2.将袖带绑在左上臂，距肘关节2cm 3.按开始键即可自动测量 4.建议早晚各测一次",
                    },
                    {
                        "question": "老人用哪种血压计好？",
                        "answer": "推荐上臂式电子血压计，带语音播报功能，大屏显示，操作简单，测量准确",
                    },
                ],
            },
            {
                "product_id": "P002",
                "name": "欧姆龙体温计MC-246",
                "description": "电子体温计，60秒快速测温，防水设计，蜂鸣提醒。",
                "price": 39.9,
                "suitable_for": ["全家适用", "婴幼儿"],
                "contraindicated_for": [],
                "scenarios": ["家庭测温", "婴儿护理"],
                "related_products": [
                    {"id": "P001", "name": "鱼跃电子血压计YE680A", "price": 199.0},
                ],
                "faqs": [
                    {
                        "question": "体温计怎么用？",
                        "answer": "将探头放在腋下夹紧，听到蜂鸣声后取出读数",
                    },
                ],
            },
            {
                "product_id": "P003",
                "name": "鱼跃雾化器403AI",
                "description": "医用压缩式雾化器，静音设计，0.2ml残留量，适合儿童和老人。",
                "price": 269.0,
                "suitable_for": ["儿童", "老人", "哮喘患者", "支气管炎患者"],
                "contraindicated_for": [],
                "scenarios": ["家庭雾化治疗", "儿童呼吸道护理"],
                "related_products": [
                    {"id": "P004", "name": "一次性雾化面罩", "price": 5.0},
                ],
                "faqs": [
                    {
                        "question": "雾化器怎么使用？",
                        "answer": "1.将药液倒入雾化杯 2.连接面罩和主机 3.开机后均匀呼吸即可",
                    },
                ],
            },
            {
                "product_id": "P005",
                "name": "三诺血糖仪GA-3",
                "description": "微量采血，5秒出结果，大屏显示，含50片试纸。",
                "price": 89.0,
                "suitable_for": ["糖尿病患者", "血糖监测人群"],
                "contraindicated_for": [],
                "scenarios": ["家庭血糖监测"],
                "related_products": [
                    {"id": "P001", "name": "鱼跃电子血压计YE680A", "price": 199.0},
                ],
                "faqs": [
                    {
                        "question": "血糖仪怎么用？",
                        "answer": "1.插入试纸 2.用采血针采指尖血 3.将血样触碰试纸吸血口 4.等待5秒出结果",
                    },
                ],
            },
        ]

    async def vector_search(self, query_embedding, index_name="", limit=10):
        # Return all products as mock vector results
        from .neo4j_skill import VectorSearchResult

        return [
            VectorSearchResult(
                id=p["product_id"],
                name=p["name"],
                description=p["description"],
                score=0.9 - i * 0.05,
            )
            for i, p in enumerate(self._products[:limit])
        ]

    async def keyword_search(self, keywords, limit=10):
        from .neo4j_skill import KeywordSearchResult

        results = []
        for p in self._products:
            for kw in keywords:
                if kw in p["name"] or kw in p["description"]:
                    results.append(
                        KeywordSearchResult(
                            id=p["product_id"],
                            name=p["name"],
                            description=p["description"],
                            score=0.8,
                        )
                    )
                    break
        return results[:limit]

    async def hybrid_search(self, query, query_embedding, keywords, limit=10):
        vec = await self.vector_search(query_embedding, limit=30)
        kw = await self.keyword_search(keywords, limit=30)
        # simple merge
        seen = set()
        merged = []
        for item in vec + kw:
            if item.id not in seen:
                seen.add(item.id)
                merged.append(item)
        return merged[:limit]

    async def get_product_graph(self, product_id):
        from .neo4j_skill import ProductGraph

        for p in self._products:
            if p["product_id"] == product_id:
                return ProductGraph(**p)
        return None


# ── Skills Container ─────────────────────────────────────────────────────────


@dataclass
class SkillsContainer:
    """所有 skills 的统一容器。"""

    calculator: CalculatorSkill
    database: DatabaseSkill
    neo4j: Any  # Neo4jSkill or MockNeo4jSkill
    embedding: Any  # EmbeddingSkill or MockEmbeddingSkill
    reranker: Any  # RerankerSkill or MockRerankerSkill


def create_skills(mode: str = "mock") -> SkillsContainer:
    """
    创建 skills 实例。

    Args:
        mode: "mock" — 使用 mock 数据，无需外部服务
              "production" — 连接真实数据库和模型
    """
    calculator = CalculatorSkill()

    if mode == "mock":
        database = DatabaseSkill(pool=None)  # no DB connection
        neo4j = MockNeo4jSkill()
        embedding = MockEmbeddingSkill()
        reranker = MockRerankerSkill()
    elif mode == "production":
        # Production mode — caller should set up connections before using
        import os

        vector_backend = os.environ.get("VECTOR_STORE", "postgres").lower()
        database = DatabaseSkill(pool=None)  # pool injected later
        if vector_backend == "neo4j":
            try:
                from .neo4j_skill import Neo4jSkill

                neo4j = Neo4jSkill(driver=None)  # driver injected later
            except Exception:
                neo4j = MockNeo4jSkill()
        else:
            try:
                from .pgvector_skill import PgVectorSkill

                neo4j = PgVectorSkill(pool=None)  # pool injected later
            except Exception:
                neo4j = MockNeo4jSkill()
        try:
            from .embedding import EmbeddingSkill

            embedding = EmbeddingSkill()
        except Exception:
            embedding = MockEmbeddingSkill()
        try:
            from .reranker import RerankerSkill

            reranker = RerankerSkill()
        except Exception:
            reranker = MockRerankerSkill()
    else:
        raise ValueError(f"Unknown mode: {mode}")

    return SkillsContainer(
        calculator=calculator,
        database=database,
        neo4j=neo4j,
        embedding=embedding,
        reranker=reranker,
    )
