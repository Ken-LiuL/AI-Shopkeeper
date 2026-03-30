#!/usr/bin/env python3
"""一键重建 Neo4j 图谱。

默认行为：
1) 清空 Neo4j 现有图谱
2) 从 PostgreSQL 执行 Graph Builder ETL

用法：
    python scripts/run_etl_graph.py
    python scripts/run_etl_graph.py --no-reset
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _reset_graph(neo4j_driver) -> None:
    logger.info("[1/3] 清空 Neo4j 图谱...")
    async with neo4j_driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="重建 Neo4j GraphRAG 图谱")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="不清空现有图谱，直接增量写入",
    )
    args = parser.parse_args()

    from src.db import neo4j as neo4j_db
    from src.db import postgres as pg_db
    from src.sync.etl_graph_builder import run_graph_builder_etl

    logger.info("=== ETL: graph_builder 开始 ===")

    pool = await pg_db.init_pool()
    neo4j_driver = await neo4j_db.init_driver()

    try:
        if not args.no_reset:
            await _reset_graph(neo4j_driver)
        else:
            logger.info("[1/3] 跳过图谱清空（--no-reset）")

        logger.info("[2/3] 执行图谱构建 ETL...")
        result = await run_graph_builder_etl(pool, neo4j_driver)

        logger.info("[3/3] ETL 完成")
        logger.info("nodes_created=%s", result.get("nodes_created", 0))
        logger.info("relationships_created=%s", result.get("relationships_created", 0))

        errors = result.get("errors", []) or []
        if errors:
            logger.warning("errors=%d", len(errors))
            for err in errors[:20]:
                logger.warning("- %s", err)
        else:
            logger.info("errors=0")

    finally:
        await pg_db.close_pool()
        await neo4j_db.close_driver()


if __name__ == "__main__":
    asyncio.run(main())
