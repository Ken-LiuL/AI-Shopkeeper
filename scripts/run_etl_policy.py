#!/usr/bin/env python3
"""一键执行 etl_policy_crawler：爬取美团医疗器械政策文档并写入 policy_documents 表。"""

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
    from src.sync.etl_policy_crawler import run_policy_crawler_etl

    logger.info("=== ETL: policy_crawler 开始 ===")

    pool = await pg_db.init_pool()
    try:
        await run_policy_crawler_etl(pool)
        logger.info("=== ETL 完成 ===")
    finally:
        await pg_db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
