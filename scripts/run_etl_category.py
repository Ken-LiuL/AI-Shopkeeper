#!/usr/bin/env python3
"""一键执行 etl_category_mapping：从 qnh_products 构建类目映射表。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from src.db import postgres as pg_db
    from src.sync.etl_category_mapping import run_category_mapping_etl

    logger.info("=== ETL: category_mapping 开始 ===")

    pool = await pg_db.init_pool()
    try:
        results = await run_category_mapping_etl(pool, qnh_client=None)
        logger.info("=== ETL 完成 ===")
        logger.info("  商品表类目:  %d", results.get("from_products", 0))
        logger.info("  竞品表类目:  %d", results.get("from_competitors", 0))
        logger.info("  店铺 API:    %d (无 client，已跳过)", results.get("from_store_api", 0))
        logger.info("  合计:        %d", results.get("total", 0))
    finally:
        await pg_db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
