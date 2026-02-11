#!/usr/bin/env python3
"""手动测试美团 H5 采集器。

Usage:
    python scripts/test_h5_scraper.py
    python scripts/test_h5_scraper.py --keyword 体温计
    python scripts/test_h5_scraper.py --store 12345
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.skills.meituan_h5 import MeituanH5Scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def main():
    parser = argparse.ArgumentParser(description="测试美团 H5 采集器")
    parser.add_argument("--keyword", default="血压计", help="搜索关键词")
    parser.add_argument("--store", default="", help="店铺ID（测试店铺商品采集）")
    parser.add_argument("--hot", action="store_true", help="测试热搜词采集")
    parser.add_argument("--limit", type=int, default=10, help="最大结果数")
    args = parser.parse_args()

    scraper = MeituanH5Scraper()

    try:
        if args.hot:
            print(f"\n🔥 采集热搜词...")
            keywords = await scraper.search_hot_keywords(args.keyword)
            if keywords:
                print(f"  找到 {len(keywords)} 个热搜词:")
                for i, kw in enumerate(keywords, 1):
                    print(f"  {i}. {kw}")
            else:
                print("  ⚠️ 未采集到热搜词（可能需要登录或检查 Extension Bridge）")

        elif args.store:
            print(f"\n🏪 采集店铺 {args.store} 的商品...")
            products = await scraper.get_store_products(args.store)
            if products:
                print(f"  找到 {len(products)} 个商品:")
                for i, p in enumerate(products[:args.limit], 1):
                    print(f"  {i}. {p.name} | ¥{p.price} | 月销 {p.monthly_sales}")
            else:
                print("  ⚠️ 未采集到商品")

        else:
            print(f"\n🔍 搜索「{args.keyword}」...")
            products = await scraper.search_products(args.keyword, limit=args.limit)
            if products:
                print(f"  找到 {len(products)} 个结果:\n")
                print(f"  {'#':>3}  {'商品名':<30} {'价格':>8} {'月销':>6} {'店铺':<20}")
                print(f"  {'─'*3}  {'─'*30} {'─'*8} {'─'*6} {'─'*20}")
                for i, p in enumerate(products[:args.limit], 1):
                    name = p.name[:28] + ".." if len(p.name) > 30 else p.name
                    store = p.store_name[:18] + ".." if len(p.store_name) > 20 else p.store_name
                    print(f"  {i:>3}  {name:<30} ¥{p.price:>6.1f} {p.monthly_sales:>6} {store:<20}")
            else:
                print("  ⚠️ 未采集到结果")
                print("  检查：")
                print("  1. ActionBook Extension Bridge 是否启动？ (actionbook extension serve)")
                print("  2. Chrome 是否已登录美团？")
                print("  3. 查看日志获取详细错误信息")

    finally:
        await scraper.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
