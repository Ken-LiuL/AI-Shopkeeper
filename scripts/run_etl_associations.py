#!/usr/bin/env python3
"""一键执行 etl_product_associations：从订单数据挖掘商品共现关联。

数据源优先级：
  1. qnh_orders_raw（raw JSONB 表）
  2. qnh_orders（结构化表，items JSONB 列）— 自动降级
"""

from __future__ import annotations

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


async def main() -> None:
    from src.db import postgres as pg_db
    from src.sync.etl_product_associations import run_product_associations_etl

    logger.info("=== ETL: product_associations 开始 ===")

    pool = await pg_db.init_pool()
    try:
        await run_product_associations_etl(pool)
        logger.info("=== ETL 完成 ===")
    finally:
        await pg_db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
