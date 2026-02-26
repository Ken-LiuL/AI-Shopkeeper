"""全量商品同步脚本 — 从 QNH 抓取所有 SPU 数据写入 Fly Postgres。

Usage: python3 scripts/sync_all_products.py
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import nodriver
import nodriver.cdp.network

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COOKIE_FILE = Path(__file__).parent.parent / "config" / "qnh_cookies.json"
PAGE_SIZE = 20
API_PATH = "/qnh-gw3/api/product/tenant/page-query"
# Fly Postgres — connect via flycast or external
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://ai_shopkeeper_kk:8c6qWp4phD6K2dt@ai-shopkeeper-kk-db.flycast:5432/ai_shopkeeper_kk?sslmode=disable",
)


async def init_browser():
    """Start Chrome, load cookies, wait for h5guard init."""
    with open(COOKIE_FILE) as f:
        cookies = json.load(f)

    browser = await nodriver.start(
        headless=False,
        browser_args=["--no-first-run", "--no-default-browser-check"],
    )
    page = await browser.get("https://qnh.meituan.com")

    for name, value in cookies.items():
        await page.send(
            nodriver.cdp.network.set_cookie(
                name=str(name), value=str(value), domain=".meituan.com", path="/"
            )
        )
    logger.info("Loaded %d cookies", len(cookies))

    page = await browser.get("https://qnh.meituan.com/home.html")
    logger.info("Waiting for h5guard init (10s)...")
    await page.sleep(10)

    # Navigate to product page to ensure h5guard is fully loaded for qnh-gw3
    page = await browser.get("https://qnh.meituan.com/#/unifiedGoods/tenant/spu-list")
    logger.info("Navigating to product page, waiting 8s...")
    await page.sleep(8)
    logger.info("Browser ready ✓")
    return browser, page


async def fetch_page(page, page_no: int) -> dict:
    """Fetch one page of SPU data via browser fetch."""
    key = f"__spu_{int(time.time() * 1000)}_{page_no}"
    body = json.dumps({"page": page_no, "pageSize": PAGE_SIZE, "current": page_no})

    js = f"""
        window.{key} = 'pending';
        fetch('{API_PATH}?yodaReady=h5&csecplatform=4&csecversion=4.2.0', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            credentials: 'include',
            body: {body}
        }}).then(r => r.json())
          .then(d => {{ window.{key} = JSON.stringify(d); }})
          .catch(e => {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
    """
    await page.evaluate(js)
    await page.sleep(3)

    result_str = await page.evaluate(f"window.{key}")
    if result_str == "pending":
        await page.sleep(3)
        result_str = await page.evaluate(f"window.{key}")

    if not result_str or result_str == "pending":
        raise RuntimeError(f"Timeout fetching page {page_no}")

    data = json.loads(result_str)
    if data.get("_error"):
        raise RuntimeError(f"API error: {data.get('message')}")
    if data.get("code") != 0:
        raise RuntimeError(f"API code {data.get('code')}: {data.get('msg')}")

    return data["data"]


async def fetch_all_products(page) -> list[dict]:
    """Fetch all SPU pages."""
    first = await fetch_page(page, 1)
    total = first.get("total", 0)
    products = first.get("list", [])
    logger.info("Total products: %d, fetched page 1 (%d items)", total, len(products))

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    for p in range(2, total_pages + 1):
        data = await fetch_page(page, p)
        items = data.get("list", [])
        products.extend(items)
        logger.info(
            "Fetched page %d/%d (%d items, total so far: %d)",
            p,
            total_pages,
            len(items),
            len(products),
        )
        await page.sleep(1)  # rate limit

    logger.info("Fetched all %d products", len(products))
    return products


async def save_to_db(products: list[dict]):
    """Upsert products into Fly Postgres."""
    try:
        import asyncpg
    except ImportError:
        logger.error("asyncpg not installed, saving to local JSON instead")
        out = Path(__file__).parent.parent / "data" / "all_products.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(products, ensure_ascii=False, indent=2))
        logger.info("Saved %d products to %s", len(products), out)
        return

    pool = await asyncpg.create_pool(DATABASE_URL)

    # Ensure table exists
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS qnh_products (
            spu_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            spec TEXT DEFAULT '',
            retail_price NUMERIC,
            image_url TEXT DEFAULT '',
            status TEXT DEFAULT '在售',
            pic_urls JSONB DEFAULT '[]',
            skus JSONB DEFAULT '[]',
            weight_type TEXT DEFAULT '',
            extra JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    count = 0
    for p in products:
        spu_id = str(p.get("spuId", ""))
        name = p.get("spuName") or p.get("goodsName") or ""
        brand = p.get("brand", {}).get("brandName", "") if isinstance(p.get("brand"), dict) else ""
        pic_urls = p.get("picUrlList", [])
        image_url = pic_urls[0] if pic_urls else ""
        weight_type = p.get("weightTypeDesc", "")
        skus = p.get("skus", [])

        # Extract price from first SKU
        retail_price = None
        spec = ""
        if skus:
            first_sku = skus[0]
            spec = first_sku.get("specName", "")
            suggest = first_sku.get("suggestPrice", {})
            if isinstance(suggest, dict):
                tenant_suggest = suggest.get("tenantSuggestPrice", {})
                if isinstance(tenant_suggest, dict):
                    price_str = tenant_suggest.get("unifiedSuggestPrice")
                    if price_str:
                        try:
                            retail_price = float(price_str)
                        except (ValueError, TypeError):
                            pass

        status = "在售" if p.get("onlineStatus") == 1 else "停售"

        await pool.execute(
            """
            INSERT INTO qnh_products (spu_id, name, brand, spec, retail_price, image_url, status, pic_urls, skus, weight_type, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, NOW())
            ON CONFLICT (spu_id) DO UPDATE SET
                name = EXCLUDED.name,
                brand = EXCLUDED.brand,
                spec = EXCLUDED.spec,
                retail_price = EXCLUDED.retail_price,
                image_url = EXCLUDED.image_url,
                status = EXCLUDED.status,
                pic_urls = EXCLUDED.pic_urls,
                skus = EXCLUDED.skus,
                weight_type = EXCLUDED.weight_type,
                updated_at = NOW()
            """,
            spu_id,
            name,
            brand,
            spec,
            retail_price,
            image_url,
            status,
            json.dumps(pic_urls, ensure_ascii=False),
            json.dumps(skus, ensure_ascii=False),
            weight_type,
        )
        count += 1

    total = await pool.fetchval("SELECT COUNT(*) FROM qnh_products")
    logger.info("Upserted %d products. Total in DB: %d", count, total)
    await pool.close()


async def main():
    browser, page = await init_browser()
    try:
        products = await fetch_all_products(page)

        # Save local backup first
        out = Path(__file__).parent.parent / "data" / "all_products.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(products, ensure_ascii=False, indent=2))
        logger.info("Local backup: %s (%d products)", out, len(products))

        # Save to DB
        await save_to_db(products)
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
