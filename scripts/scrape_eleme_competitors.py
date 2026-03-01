"""Scrape real competitor pharmacy data from Ele.me (饿了么) using nodriver.

Ele.me has weaker anti-bot protection than Meituan.
Searches for nearby pharmacies and their products, then inserts into competitor tables.

Usage:
    python scripts/scrape_eleme_competitors.py

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

# Search keywords for pharmacy stores
STORE_KEYWORDS = [
    "药店",
    "大药房",
    "医疗器械",
    "药房",
    "连锁药店",
]

# Product search keywords
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


async def scrape_eleme_pharmacies(headless: bool = True) -> tuple[list[dict], list[dict]]:
    """Scrape nearby pharmacy stores from Ele.me H5."""
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
            "--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
        ],
    )

    stores = []
    products = []

    try:
        # Go to Ele.me H5
        page = await browser.get("https://h5.ele.me/")
        await asyncio.sleep(3)

        # Set location to Chengdu via JavaScript
        try:
            await page.evaluate(f"""
                // Override geolocation
                navigator.geolocation.getCurrentPosition = function(success, error) {{
                    success({{
                        coords: {{
                            latitude: {CHENGDU_LAT},
                            longitude: {CHENGDU_LNG},
                            accuracy: 100
                        }}
                    }});
                }};

                // Set localStorage location if needed
                if (window.localStorage) {{
                    localStorage.setItem('location', JSON.stringify({{
                        lat: {CHENGDU_LAT},
                        lng: {CHENGDU_LNG},
                        address: '成都市春熙路'
                    }}));
                }}
            """)
            logger.info(f"Set location to Chengdu: lat={CHENGDU_LAT}, lng={CHENGDU_LNG}")
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to set location: {e}")

        # Search for pharmacies
        for keyword in STORE_KEYWORDS:
            try:
                logger.info(f"Searching for stores with keyword: '{keyword}'")

                # Navigate to search page
                search_url = f"https://h5.ele.me/search/?keyword={keyword}"
                await page.get(search_url)
                await asyncio.sleep(5)  # Wait for page load

                # Look for store results
                try:
                    # Try different selectors for store cards
                    store_selectors = [
                        '[class*="shop"]',
                        '[class*="store"]',
                        '[class*="restaurant"]',
                        '[class*="item"]',
                        '[data-testid*="shop"]',
                        ".shop-item",
                        ".store-card",
                    ]

                    store_elements = []
                    for selector in store_selectors:
                        try:
                            elements = await page.query_selector_all(selector)
                            if elements:
                                store_elements.extend(elements[:10])  # Take up to 10 per selector
                                logger.info(
                                    f"Found {len(elements)} elements with selector: {selector}"
                                )
                                break
                        except Exception:
                            continue

                    # Parse store cards
                    for elem in store_elements[:20]:
                        try:
                            text = await elem.text
                            if text and len(text.strip()) > 10:
                                store_info = _parse_store_card(text, keyword)
                                if store_info:
                                    stores.append(store_info)
                                    logger.info(f"Extracted store: {store_info['name']}")
                        except Exception as e:
                            logger.debug(f"Error parsing store element: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Failed to find store elements for '{keyword}': {e}")

                # Also try to extract data from page source
                try:
                    content = await page.get_content()
                    _extract_stores_from_page_content(content, stores, keyword)
                except Exception as e:
                    logger.debug(f"Failed to extract from page content: {e}")

                logger.info(
                    f"Keyword '{keyword}': found {len([s for s in stores if s.get('category') == keyword])} stores"
                )

            except Exception as e:
                logger.warning(f"Failed to search stores for '{keyword}': {e}")

        # Search for products
        for keyword in PRODUCT_KEYWORDS[:10]:  # Limit to avoid rate limits
            try:
                logger.info(f"Searching for products with keyword: '{keyword}'")

                search_url = f"https://h5.ele.me/search/?keyword={keyword}"
                await page.get(search_url)
                await asyncio.sleep(4)

                # Look for product/food items
                try:
                    product_selectors = [
                        '[class*="food"]',
                        '[class*="product"]',
                        '[class*="item"]',
                        '[class*="goods"]',
                        ".food-item",
                        ".product-card",
                    ]

                    product_elements = []
                    for selector in product_selectors:
                        try:
                            elements = await page.query_selector_all(selector)
                            if elements:
                                product_elements.extend(elements[:15])
                                logger.info(
                                    f"Found {len(elements)} product elements with selector: {selector}"
                                )
                                break
                        except Exception:
                            continue

                    # Parse product cards
                    for elem in product_elements:
                        try:
                            text = await elem.text
                            if text and len(text.strip()) > 5:
                                product_info = _parse_product_card(text, keyword)
                                if product_info:
                                    products.append(product_info)
                                    logger.info(
                                        f"Extracted product: {product_info['name']} - ¥{product_info['price']}"
                                    )
                        except Exception as e:
                            logger.debug(f"Error parsing product element: {e}")
                            continue

                except Exception as e:
                    logger.warning(f"Failed to find product elements for '{keyword}': {e}")

                logger.info(
                    f"Product '{keyword}': found {len([p for p in products if p.get('category') == keyword])} products"
                )

            except Exception as e:
                logger.warning(f"Failed to search products for '{keyword}': {e}")

    except Exception as e:
        logger.error(f"Browser scraping failed: {e}")
    finally:
        try:
            await browser.stop()
        except Exception:
            pass

    return stores, products


def _extract_stores_from_page_content(content: str, stores: list, keyword: str):
    """Extract store data from page HTML content."""
    # Look for JSON data in script tags
    patterns = [
        r"window\.__INITIAL_STATE__\s*=\s*({.*?});",
        r"window\.__ELE_CONFIG__\s*=\s*({.*?});",
        r'"shops":\s*(\[.*?\])',
        r'"restaurants":\s*(\[.*?\])',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            try:
                if match.startswith("["):
                    data = json.loads(match)
                elif match.startswith("{"):
                    data = json.loads(match)
                    # Look for shop lists in various paths
                    for path in ["shops", "restaurants", "data.shops", "searchResult.shops"]:
                        obj = data
                        for key in path.split("."):
                            if isinstance(obj, dict) and key in obj:
                                obj = obj[key]
                            else:
                                obj = None
                                break
                        if isinstance(obj, list):
                            data = obj
                            break

                if isinstance(data, list):
                    for shop in data[:20]:  # Limit results
                        if isinstance(shop, dict) and shop.get("name"):
                            stores.append(
                                {
                                    "store_id": f"el_{shop.get('id', hash(shop['name']) % 10**8)}",
                                    "name": shop.get("name", ""),
                                    "rating": float(shop.get("rating", shop.get("score", 0)) or 0),
                                    "monthly_sales": int(
                                        shop.get("recent_order_num", shop.get("sales", 0)) or 0
                                    ),
                                    "distance_km": float(shop.get("distance", 0) or 0) / 1000,
                                    "category": keyword,
                                    "source": "eleme",
                                }
                            )
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Failed to parse JSON data: {e}")
                continue


def _parse_store_card(text: str, keyword: str) -> dict | None:
    """Parse a store card's visible text into structured data."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return None

    name = lines[0]
    if len(name) < 2 or len(name) > 60:
        return None

    # Skip if doesn't look like a pharmacy
    if keyword in ["药店", "药房", "大药房"]:
        if not any(x in name for x in ["药", "医疗", "健康", "康"]):
            return None

    rating = 0.0
    monthly_sales = 0
    distance = 0.0

    for line in lines:
        # Rating patterns
        m = re.search(r"(\d\.\d+)\s*分", line)
        if m and not rating:
            rating = float(m.group(1))

        # Sales patterns
        m = re.search(r"月售\s*(\d+)", line)
        if m:
            monthly_sales = int(m.group(1))
        m = re.search(r"(\d+)\s*单", line)
        if m and not monthly_sales:
            monthly_sales = int(m.group(1))

        # Distance patterns
        m = re.search(r"(\d+\.?\d*)\s*km", line)
        if m:
            distance = float(m.group(1))
        m = re.search(r"(\d+)\s*m(?![a-z])", line)
        if m and not distance:
            distance = int(m.group(1)) / 1000

    return {
        "store_id": f"el_{abs(hash(name)) % 10**8}",
        "name": name,
        "rating": rating,
        "monthly_sales": monthly_sales,
        "distance_km": round(distance, 2),
        "category": "pharmacy",
        "source": "eleme_scrape",
    }


def _parse_product_card(text: str, keyword: str) -> dict | None:
    """Parse a product card's text into structured data."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return None

    name = lines[0]
    if len(name) < 2 or len(name) > 100:
        return None

    price = 0.0
    monthly_sales = 0

    for line in lines:
        # Price patterns
        m = re.search(r"[¥￥]\s*(\d+\.?\d*)", line)
        if m:
            price = float(m.group(1))
        m = re.search(r"(\d+\.?\d+)\s*元", line)
        if m and not price:
            price = float(m.group(1))

        # Sales patterns
        m = re.search(r"月售\s*(\d+)", line)
        if m:
            monthly_sales = int(m.group(1))
        m = re.search(r"售\s*(\d+)", line)
        if m and not monthly_sales:
            monthly_sales = int(m.group(1))

    if not price or price > 10000:  # Sanity check
        return None

    return {
        "name": name,
        "price": price,
        "monthly_sales": monthly_sales,
        "category": keyword,
        "source": "eleme_scrape",
    }


async def save_to_db(stores: list[dict], products: list[dict], db_url: str):
    """Save scraped data to PostgreSQL."""
    pool = await asyncpg.create_pool(db_url)
    now = datetime.now(UTC)

    try:
        # Clean old scraped data (keep manually added)
        await pool.execute(
            "DELETE FROM competitor_products WHERE product_id LIKE 'el_%' OR source LIKE '%eleme%'"
        )
        await pool.execute(
            "DELETE FROM competitor_stores WHERE store_id LIKE 'el_%' OR source LIKE '%eleme%'"
        )

        # Insert stores
        seen_names = set()
        inserted_stores = 0
        for store in stores:
            if not store.get("name") or store["name"] in seen_names:
                continue
            seen_names.add(store["name"])

            try:
                await pool.execute(
                    "INSERT INTO competitor_stores (store_id, name, rating, monthly_sales, distance_km, category, source, last_synced) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
                    "ON CONFLICT (store_id) DO UPDATE SET name=EXCLUDED.name, rating=EXCLUDED.rating, "
                    "monthly_sales=EXCLUDED.monthly_sales, last_synced=EXCLUDED.last_synced",
                    store["store_id"],
                    store["name"],
                    store["rating"],
                    store["monthly_sales"],
                    store["distance_km"],
                    store.get("category", "pharmacy"),
                    store.get("source", "eleme_scrape"),
                    now,
                )
                inserted_stores += 1
            except Exception as e:
                logger.warning(f"Failed to insert store {store['name']}: {e}")

        # Insert products
        inserted_products = 0
        for i, product in enumerate(products):
            if not product.get("name") or not product.get("price"):
                continue

            pid = f"el_p_{i + 1}"
            # Assign to a random store if we have stores
            store_id = stores[i % len(stores)]["store_id"] if stores else ""

            try:
                await pool.execute(
                    "INSERT INTO competitor_products (product_id, store_id, name, price, monthly_sales, rating, category, source, last_synced) "
                    "VALUES ($1,$2,$3,$4,$5,0,$6,$7,$8) "
                    "ON CONFLICT (product_id) DO UPDATE SET price=EXCLUDED.price, last_synced=EXCLUDED.last_synced",
                    pid,
                    store_id,
                    product["name"],
                    product["price"],
                    product["monthly_sales"],
                    product.get("category", ""),
                    product.get("source", "eleme_scrape"),
                    now,
                )
                inserted_products += 1
            except Exception as e:
                logger.warning(f"Failed to insert product {product['name']}: {e}")

        # Update keywords
        keyword_counts = {}
        for p in products:
            cat = p.get("category", "")
            if cat:
                keyword_counts[cat] = keyword_counts.get(cat, 0) + 1

        for kw, cnt in keyword_counts.items():
            if cnt > 0:
                avg_price = sum(p["price"] for p in products if p.get("category") == kw) / cnt
                try:
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
                except Exception as e:
                    logger.warning(f"Failed to update keyword {kw}: {e}")

        logger.info(f"✅ Saved {inserted_stores} stores and {inserted_products} products to DB")

    finally:
        await pool.close()


async def main():
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        logger.error(
            "DATABASE_URL not set. Use: DATABASE_URL=... python scripts/scrape_eleme_competitors.py"
        )
        sys.exit(1)

    logger.info(f"🚀 Starting Ele.me competitor scraping (headless={headless})...")
    stores, products = await scrape_eleme_pharmacies(headless=headless)

    logger.info(f"📊 Scraped {len(stores)} stores and {len(products)} products")

    if stores or products:
        await save_to_db(stores, products, db_url)
        logger.info("✅ Data saved to database successfully")
    else:
        logger.warning(
            "⚠️ No data scraped. May need to adjust selectors or handle anti-bot measures."
        )

    # Print summary
    if stores:
        logger.info("🏪 Sample stores:")
        for store in stores[:3]:
            logger.info(
                f"  - {store['name']} (rating: {store['rating']}, sales: {store['monthly_sales']})"
            )

    if products:
        logger.info("🛍️ Sample products:")
        for product in products[:3]:
            logger.info(
                f"  - {product['name']} - ¥{product['price']} (sales: {product['monthly_sales']})"
            )


if __name__ == "__main__":
    asyncio.run(main())
