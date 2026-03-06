"""Neo4j 启动时自动创建 Product 向量索引（如果不存在）。"""

from __future__ import annotations

import logging

from src.db import neo4j as neo4j_db

logger = logging.getLogger(__name__)

# Neo4j 5 native vector index 参数
_VECTOR_INDEX_NAME = "product_embedding_index"
_VECTOR_DIMENSIONS = 1536
_SIMILARITY_FUNCTION = "cosine"

# Neo4j 5 全文索引（用于关键词 fallback）
_FULLTEXT_INDEX_NAME = "product_fulltext_index"


async def ensure_neo4j_indexes() -> None:
    """确保 Neo4j 中已存在 Product 向量索引和全文索引（幂等）。"""
    driver = neo4j_db.get_driver()

    async with driver.session() as session:
        # ── 检查并创建向量索引 ────────────────────────────────────────
        existing = await session.run(
            "SHOW INDEXES YIELD name WHERE name = $name RETURN name",
            {"name": _VECTOR_INDEX_NAME},
        )
        existing_records = await existing.data()

        if not existing_records:
            logger.info(
                "Creating Neo4j vector index '%s' (dim=%d, similarity=%s) …",
                _VECTOR_INDEX_NAME,
                _VECTOR_DIMENSIONS,
                _SIMILARITY_FUNCTION,
            )
            await session.run(
                f"""
                CREATE VECTOR INDEX {_VECTOR_INDEX_NAME} IF NOT EXISTS
                FOR (n:Product) ON (n.embedding)
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: {_VECTOR_DIMENSIONS},
                        `vector.similarity_function`: '{_SIMILARITY_FUNCTION}'
                    }}
                }}
                """
            )
            logger.info("Neo4j vector index '%s' created ✓", _VECTOR_INDEX_NAME)
        else:
            logger.info("Neo4j vector index '%s' already exists ✓", _VECTOR_INDEX_NAME)

        # ── 检查并创建全文索引 ────────────────────────────────────────
        existing_ft = await session.run(
            "SHOW INDEXES YIELD name WHERE name = $name RETURN name",
            {"name": _FULLTEXT_INDEX_NAME},
        )
        existing_ft_records = await existing_ft.data()

        if not existing_ft_records:
            logger.info("Creating Neo4j fulltext index '%s' …", _FULLTEXT_INDEX_NAME)
            await session.run(
                f"""
                CREATE FULLTEXT INDEX {_FULLTEXT_INDEX_NAME} IF NOT EXISTS
                FOR (n:Product) ON EACH [n.name, n.description]
                """
            )
            logger.info("Neo4j fulltext index '%s' created ✓", _FULLTEXT_INDEX_NAME)
        else:
            logger.info("Neo4j fulltext index '%s' already exists ✓", _FULLTEXT_INDEX_NAME)
