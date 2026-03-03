"""从京东健康公开页面抓取竞品价格。

无需登录，使用公开搜索 API。
结果写入本地 PG 的 competitor_products 表。

Usage:
    python scripts/scrape_jd_prices.py [--database-url URL]
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import UTC, datetime

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 从热销商品中提取关键词搜索竞品价格
SEARCH_KEYWORDS = [
    "验孕棒",
    "HIV检测试纸",
    "避孕套",
    "血氧仪",
    "血压计",
    "体温计",
    "创可贴",
    "酒精消毒",
    "医用口罩",
    "血糖试纸",
    "排卵试纸",
    "早孕试纸",
    "雾化器",
    "制氧机",
]

# 竞品来源
COMPETITOR_SOURCES = [
    {"name": "京东健康", "platform": "jd_health", "base_url": "https://search.jd.com/Search"},
    {"name": "阿里健康", "platform": "ali_health", "base_url": "https://s.taobao.com/search"},
]


async def search_jd_prices(keyword: str) -> list[dict]:
    """Search JD for product prices (public API, no auth needed)."""
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        try:
            # JD search API
            resp = await client.get(
                "https://search.jd.com/Search",
                params={"keyword": keyword, "enc": "utf-8", "wq": keyword},
                headers=headers,
            )
            if resp.status_code != 200:
                logger.warning(f"JD search failed for {keyword}: {resp.status_code}")
                return []

            html = resp.text
            # Extract product data from JD search results
            # JD embeds product info in data attributes
            products = re.findall(
                r'data-sku="(\d+)".*?class="p-name".*?<em>(.*?)</em>.*?class="p-price".*?<i>([\d.]+)</i>',
                html,
                re.DOTALL,
            )

            for sku, name, price in products[:5]:  # Top 5 per keyword
                clean_name = re.sub(r"<[^>]+>", "", name).strip()
                results.append(
                    {
                        "name": clean_name[:100],
                        "price": float(price),
                        "source": "jd_health",
                        "source_url": f"https://item.jd.com/{sku}.html",
                        "keyword": keyword,
                    }
                )
        except Exception as e:
            logger.warning(f"JD search error for {keyword}: {e}")

    return results


async def upsert_competitor_products(pool: asyncpg.Pool, products: list[dict]) -> int:
    """Upsert competitor products into database."""
    count = 0
    for p in products:
        try:
            await pool.execute(
                """
                INSERT INTO competitor_products (name, retail_price, source, source_url, category, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (name, source) DO UPDATE SET
                    retail_price = EXCLUDED.retail_price,
                    source_url = EXCLUDED.source_url,
                    updated_at = EXCLUDED.updated_at
                """,
                p["name"],
                p["price"],
                p["source"],
                p.get("source_url", ""),
                p.get("keyword", ""),
                datetime.now(UTC),
            )
            count += 1
        except Exception as e:
            logger.warning(f"Upsert failed for {p['name']}: {e}")
    return count


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql://pengkun@localhost:5432/ai_store")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=3)

    # Check if competitor_products table has the right columns
    with contextlib.suppress(Exception):
        await pool.execute(
            """
            CREATE TABLE IF NOT EXISTS competitor_products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                retail_price FLOAT,
                source TEXT NOT NULL DEFAULT '',
                source_url TEXT DEFAULT '',
                category TEXT DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(name, source)
            )
            """
        )

    total = 0
    for keyword in SEARCH_KEYWORDS:
        logger.info(f"Searching JD for: {keyword}")
        products = await search_jd_prices(keyword)
        if products:
            count = await upsert_competitor_products(pool, products)
            total += count
            logger.info(f"  Found {len(products)} products, upserted {count}")
        else:
            logger.info("  No results")
        await asyncio.sleep(2)  # Rate limit

    logger.info(f"Total: {total} competitor products updated")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
