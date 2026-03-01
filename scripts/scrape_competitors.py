"""Scrape real competitor pharmacy data from Meituan Waimai using nodriver.

Searches for nearby pharmacies and their products, then inserts into competitor tables.

Usage:
    python scripts/scrape_competitors.py

Requires: nodriver, asyncpg
Env: DATABASE_URL or BACKEND_URL
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Search keywords for pharmacy products on Meituan
SEARCH_KEYWORDS = [
    "药店",
    "大药房",
    "医疗器械",
    "药房",
]

# Product search keywords to get competitor product prices
PRODUCT_KEYWORDS = [
    "血压计",
    "制氧机",
    "轮椅",
    "雾化器",
    "体温计",
    "创可贴",
    "口罩",
    "消毒液",
    "纱布",
    "棉签",
    "维生素",
    "感冒药",
    "止痛药",
    "退烧药",
    "咳嗽药",
    "血糖仪",
    "护腰带",
    "颈椎枕",
    "拐杖",
    "助行器",
]


async def scrape_meituan_pharmacies(headless: bool = True) -> list[dict]:
    """Scrape nearby pharmacy stores from Meituan Waimai."""
    import nodriver as uc

    # Configure Chengdu location
    CHENGDU_LAT = 30.572816
    CHENGDU_LNG = 104.066801

    browser = await uc.start(
        headless=headless,
        no_sandbox=True,
        browser_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-background-timer-throttling",
        ],
    )

    stores = []
    products = []

    try:
        # Go to Meituan Waimai and search for pharmacies
        page = await browser.get("https://h5.waimai.meituan.com/waimai/mindex/home")
        await asyncio.sleep(3)

        # Try to set geolocation to Chengdu
        try:
            await page.execute_cdp_cmd(
                "Emulation.setGeolocationOverride",
                {"latitude": CHENGDU_LAT, "longitude": CHENGDU_LNG, "accuracy": 100},
            )
            logger.info(f"Set location to Chengdu: lat={CHENGDU_LAT}, lng={CHENGDU_LNG}")
        except Exception as e:
            logger.warning(f"Failed to set geolocation: {e}")

        # Try to get location permission or set city
        logger.info("Opened Meituan Waimai, waiting for page load...")
        await asyncio.sleep(5)

        # Try to set location via JavaScript if supported
        try:
            await page.evaluate("""
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition = function(success) {
                        success({
                            coords: {
                                latitude: 30.572816,
                                longitude: 104.066801,
                                accuracy: 100
                            }
                        });
                    };
                }
            """)
            logger.info("Injected Chengdu coordinates via JavaScript")
        except Exception as e:
            logger.debug(f"JS geolocation injection failed: {e}")

        await asyncio.sleep(3)

        # Search for pharmacies
        for keyword in SEARCH_KEYWORDS[:2]:
            try:
                search_url = (
                    f"https://h5.waimai.meituan.com/waimai/mindex/search?searchKey={keyword}"
                )
                page = await browser.get(search_url)
                await asyncio.sleep(4)

                # Extract store data from page
                page_text = await page.get_content()

                # Look for store data in script tags or API responses
                # Meituan embeds data in __NEXT_DATA__ or window.__INITIAL_STATE__
                data_match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", page_text)
                if not data_match:
                    data_match = re.search(
                        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_text
                    )

                if data_match:
                    try:
                        data = json.loads(data_match.group(1))
                        logger.info(
                            f"Found embedded data for '{keyword}', keys: {list(data.keys())[:5]}"
                        )
                        # Extract store list from various possible paths
                        _extract_stores_from_data(data, stores, keyword)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse embedded data for '{keyword}'")

                # Also try to intercept XHR responses
                # Scrape visible store cards from DOM
                store_elements = await page.query_selector_all(
                    "[class*='shopItem'], [class*='store'], [class*='poi']"
                )
                for elem in store_elements[:20]:
                    try:
                        text = await elem.text
                        if text and len(text) > 5:
                            store_info = _parse_store_card(text, keyword)
                            if store_info:
                                stores.append(store_info)
                    except Exception:
                        continue

                logger.info(f"Keyword '{keyword}': found {len(stores)} stores so far")

            except Exception as e:
                logger.warning(f"Failed to search '{keyword}': {e}")

        # Now scrape product prices from top stores
        for keyword in PRODUCT_KEYWORDS[:10]:
            try:
                search_url = (
                    f"https://h5.waimai.meituan.com/waimai/mindex/search?searchKey={keyword}"
                )
                page = await browser.get(search_url)
                await asyncio.sleep(3)

                # Extract product cards
                product_elements = await page.query_selector_all(
                    "[class*='product'], [class*='food'], [class*='item']"
                )
                for elem in product_elements[:10]:
                    try:
                        text = await elem.text
                        if text:
                            product_info = _parse_product_card(text, keyword)
                            if product_info:
                                products.append(product_info)
                    except Exception:
                        continue

                logger.info(f"Product '{keyword}': found {len(products)} products so far")

            except Exception as e:
                logger.warning(f"Failed to search products '{keyword}': {e}")

    except Exception as e:
        logger.error(f"Browser scraping failed: {e}")
    finally:
        with __import__("contextlib").suppress(Exception):
            browser.stop()

    return stores, products


def _extract_stores_from_data(data: dict, stores: list, keyword: str):
    """Extract store information from Meituan embedded JSON data."""
    # Try common paths in Meituan data structure
    for path in ["searchData.shopList", "data.shopList", "shopList", "poiList", "data.poiList"]:
        obj = data
        for key in path.split("."):
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                obj = None
                break
        if isinstance(obj, list):
            for shop in obj:
                if isinstance(shop, dict):
                    stores.append(
                        {
                            "store_id": f"mt_{shop.get('id', shop.get('poiId', ''))}",
                            "name": shop.get("name", shop.get("shopName", "")),
                            "rating": float(shop.get("score", shop.get("rating", 0)) or 0),
                            "monthly_sales": int(
                                shop.get("monthSaleNum", shop.get("monthlySales", 0)) or 0
                            ),
                            "distance_km": float(shop.get("distance", 0) or 0) / 1000,
                            "category": keyword,
                            "source": "meituan",
                        }
                    )


def _parse_store_card(text: str, keyword: str) -> dict | None:
    """Parse a store card's visible text into structured data."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return None

    name = lines[0]
    if len(name) < 2 or len(name) > 50:
        return None

    # Look for rating, sales, distance patterns
    rating = 0.0
    monthly_sales = 0
    distance = 0.0

    for line in lines:
        # Rating: "4.8分" or "4.8"
        m = re.search(r"(\d\.\d)\s*分?", line)
        if m and not rating:
            rating = float(m.group(1))

        # Monthly sales: "月售1234" or "1234单"
        m = re.search(r"月售\s*(\d+)", line)
        if m:
            monthly_sales = int(m.group(1))
        m = re.search(r"(\d+)\s*单", line)
        if m and not monthly_sales:
            monthly_sales = int(m.group(1))

        # Distance: "1.2km" or "800m"
        m = re.search(r"(\d+\.?\d*)\s*km", line)
        if m:
            distance = float(m.group(1))
        m = re.search(r"(\d+)\s*m(?![\w])", line)
        if m and not distance:
            distance = int(m.group(1)) / 1000

    return {
        "store_id": f"mt_{hash(name) % 10**8}",
        "name": name,
        "rating": rating,
        "monthly_sales": monthly_sales,
        "distance_km": round(distance, 2),
        "category": "pharmacy",
        "source": "meituan_scrape",
    }


def _parse_product_card(text: str, keyword: str) -> dict | None:
    """Parse a product card's text into structured data."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return None

    name = lines[0]
    price = 0.0

    for line in lines:
        # Price: "¥12.8" or "￥12.8" or "12.80元"
        m = re.search(r"[¥￥]\s*(\d+\.?\d*)", line)
        if m:
            price = float(m.group(1))
        m = re.search(r"(\d+\.?\d+)\s*元", line)
        if m and not price:
            price = float(m.group(1))

    if not price or not name or len(name) < 2:
        return None

    # Monthly sales
    monthly_sales = 0
    for line in lines:
        m = re.search(r"月售\s*(\d+)", line)
        if m:
            monthly_sales = int(m.group(1))

    return {
        "name": name,
        "price": price,
        "monthly_sales": monthly_sales,
        "category": keyword,
        "source": "meituan_scrape",
    }


async def save_to_db(stores: list[dict], products: list[dict], db_url: str):
    """Save scraped data to PostgreSQL."""
    pool = await asyncpg.create_pool(db_url)
    now = datetime.now(UTC)

    try:
        # Clean old scraped data (keep manually added)
        await pool.execute(
            "DELETE FROM competitor_products WHERE product_id LIKE 'mt_%' OR product_id LIKE 'cp_%'"
        )
        await pool.execute(
            "DELETE FROM competitor_stores WHERE store_id LIKE 'mt_%' OR store_id LIKE 'comp_%'"
        )

        # Insert stores
        seen_names = set()
        inserted_stores = 0
        for store in stores:
            if store["name"] in seen_names or not store["name"]:
                continue
            seen_names.add(store["name"])
            await pool.execute(
                "INSERT INTO competitor_stores (store_id, name, rating, monthly_sales, distance_km, category, last_synced) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (store_id) DO UPDATE SET name=EXCLUDED.name, rating=EXCLUDED.rating, "
                "monthly_sales=EXCLUDED.monthly_sales, last_synced=EXCLUDED.last_synced",
                store["store_id"],
                store["name"],
                store["rating"],
                store["monthly_sales"],
                store["distance_km"],
                store.get("category", "pharmacy"),
                now,
            )
            inserted_stores += 1

        # Insert products
        inserted_products = 0
        for i, product in enumerate(products):
            if not product["name"] or not product["price"]:
                continue
            pid = f"mt_p_{i + 1}"
            # Assign to a random store if we have stores
            store_id = stores[i % len(stores)]["store_id"] if stores else ""
            await pool.execute(
                "INSERT INTO competitor_products (product_id, store_id, name, price, monthly_sales, rating, category, last_synced) "
                "VALUES ($1,$2,$3,$4,$5,0,$6,$7) "
                "ON CONFLICT (product_id) DO UPDATE SET price=EXCLUDED.price, last_synced=EXCLUDED.last_synced",
                pid,
                store_id,
                product["name"],
                product["price"],
                product["monthly_sales"],
                product.get("category", ""),
                now,
            )
            inserted_products += 1

        # Update keywords
        keyword_counts = {}
        for p in products:
            cat = p.get("category", "")
            if cat:
                keyword_counts[cat] = keyword_counts.get(cat, 0) + 1
        for kw, cnt in keyword_counts.items():
            avg_price = sum(p["price"] for p in products if p.get("category") == kw) / max(cnt, 1)
            await pool.execute(
                "INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price, last_synced) "
                "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (keyword) DO UPDATE SET "
                "search_volume=EXCLUDED.search_volume, avg_price=EXCLUDED.avg_price, last_synced=EXCLUDED.last_synced",
                kw,
                cnt * 100,
                cnt,
                avg_price,
                now,
            )

        logger.info(f"Saved {inserted_stores} stores and {inserted_products} products to DB")

    finally:
        await pool.close()


async def main():
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        # Try to get from Fly
        logger.error(
            "DATABASE_URL not set. Use: DATABASE_URL=... python scripts/scrape_competitors.py"
        )
        sys.exit(1)

    logger.info(f"Starting Meituan competitor scraping (headless={headless})...")
    stores, products = await scrape_meituan_pharmacies(headless=headless)

    logger.info(f"Scraped {len(stores)} stores and {len(products)} products")

    if stores or products:
        await save_to_db(stores, products, db_url)
    else:
        logger.warning("No data scraped. Meituan may require location permissions or login.")


if __name__ == "__main__":
    asyncio.run(main())
