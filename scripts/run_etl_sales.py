#!/usr/bin/env python3
"""
一键执行销售历史 & 日指标 ETL

用法：
    python scripts/run_etl_sales.py                  # 默认回溯 90 天
    python scripts/run_etl_sales.py --days 30        # 回溯 30 天
    python scripts/run_etl_sales.py --since 2026-01-01 --until 2026-03-30
    python scripts/run_etl_sales.py --full           # 回溯全部历史（365 天）

环境变量：
    DATABASE_URL  PostgreSQL 连接串（必须）
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime

# 将项目根目录加入 PYTHONPATH，使 src.* 可直接导入
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_etl_sales")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="销售历史 & 日指标 ETL")
    parser.add_argument(
        "--since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        metavar="YYYY-MM-DD",
        help="聚合起始日期（含），默认往前 --days 天",
    )
    parser.add_argument(
        "--until",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        metavar="YYYY-MM-DD",
        help="聚合截止日期（含），默认今天",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="since 未指定时往前回溯天数（默认 90）",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="回溯全部历史（等同于 --days 365）",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 环境变量未设置，退出")
        sys.exit(1)

    days_back = 365 if args.full else args.days

    import asyncpg
    from src.sync.etl_sales_aggregation import run_sales_aggregation_etl

    logger.info("连接数据库...")
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
    try:
        result = await run_sales_aggregation_etl(
            pool,
            since_date=args.since,
            until_date=args.until,
            days_back=days_back,
        )
    finally:
        await pool.close()

    # 汇报结果
    print("\n── ETL 执行结果 ──────────────────────────────────────")
    print(f"  区间         : {result['since_date']} → {result['until_date']}")
    print(f"  sales_history: {result.get('sales_history_status')} ({result.get('sales_history_rows', 0)} rows)")
    print(f"  daily_metrics: {result.get('daily_metrics_status')} ({result.get('daily_metrics_rows', 0)} rows)")
    if result.get("errors"):
        print(f"  错误         : {result['errors']}")
    print("──────────────────────────────────────────────────────\n")

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
