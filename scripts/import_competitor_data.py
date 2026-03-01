"""Import competitor data from JSON files to database.

Usage:
    python scripts/import_competitor_data.py
"""

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def import_json_data():
    """Import competitor data from JSON files."""
    # Get database URL
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return False

    # Check JSON files exist
    stores_file = Path("data/competitors/scraped_stores.json")
    products_file = Path("data/competitors/scraped_products.json")

    if not stores_file.exists() or not products_file.exists():
        logger.error(f"JSON files not found: {stores_file}, {products_file}")
        return False

    # Load JSON data
    with open(stores_file, encoding="utf-8") as f:
        stores = json.load(f)

    with open(products_file, encoding="utf-8") as f:
        products = json.load(f)

    logger.info(f"Loaded {len(stores)} stores and {len(products)} products from JSON")

    # Connect to database
    try:
        pool = await asyncpg.create_pool(db_url)
        logger.info("Connected to database successfully")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False

    try:
        now = datetime.now(UTC)

        # Clean old scraped data
        await pool.execute(
            "DELETE FROM competitor_products WHERE source IN ('manual', 'simulated', 'amap', 'web_search')"
        )
        await pool.execute("DELETE FROM competitor_stores WHERE source IN ('manual', 'amap')")
        logger.info("Cleaned old competitor data")

        # Insert stores
        inserted_stores = 0
        for store in stores:
            try:
                await pool.execute(
                    """
                    INSERT INTO competitor_stores
                    (store_id, name, rating, monthly_sales, distance_km, category, source, last_synced)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (store_id) DO UPDATE SET
                    name=EXCLUDED.name, rating=EXCLUDED.rating,
                    monthly_sales=EXCLUDED.monthly_sales, last_synced=EXCLUDED.last_synced
                """,
                    store["store_id"],
                    store["name"],
                    store["rating"],
                    store["monthly_sales"],
                    store["distance_km"],
                    store.get("category", "pharmacy"),
                    store.get("source", "manual"),
                    now,
                )
                inserted_stores += 1
            except Exception as e:
                logger.warning(f"Failed to insert store {store.get('name')}: {e}")

        # Insert products
        inserted_products = 0
        for product in products:
            try:
                await pool.execute(
                    """
                    INSERT INTO competitor_products
                    (product_id, store_id, name, price, monthly_sales, rating, category, source, last_synced)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (product_id) DO UPDATE SET
                    price=EXCLUDED.price, monthly_sales=EXCLUDED.monthly_sales, last_synced=EXCLUDED.last_synced
                """,
                    product["product_id"],
                    product.get("store_id", ""),
                    product["name"],
                    product["price"],
                    product["monthly_sales"],
                    product.get("rating", 4.0),
                    product.get("category", ""),
                    product.get("source", "simulated"),
                    now,
                )
                inserted_products += 1
            except Exception as e:
                logger.warning(f"Failed to insert product {product.get('name')}: {e}")

        # Update keywords with average prices
        keyword_stats = {}
        for p in products:
            cat = p.get("category", "")
            if cat:
                if cat not in keyword_stats:
                    keyword_stats[cat] = {"count": 0, "total_price": 0}
                keyword_stats[cat]["count"] += 1
                keyword_stats[cat]["total_price"] += p.get("price", 0)

        for keyword, stats in keyword_stats.items():
            if stats["count"] > 0:
                avg_price = stats["total_price"] / stats["count"]
                try:
                    await pool.execute(
                        """
                        INSERT INTO competitor_keywords
                        (keyword, search_volume, result_count, avg_price, last_synced)
                        VALUES ($1,$2,$3,$4,$5)
                        ON CONFLICT (keyword) DO UPDATE SET
                        search_volume=EXCLUDED.search_volume, avg_price=EXCLUDED.avg_price,
                        last_synced=EXCLUDED.last_synced
                    """,
                        keyword,
                        stats["count"] * 100,  # Simulated search volume
                        stats["count"],
                        avg_price,
                        now,
                    )
                except Exception as e:
                    logger.warning(f"Failed to update keyword {keyword}: {e}")

        logger.info(
            f"✅ Successfully imported {inserted_stores} stores and {inserted_products} products"
        )

        # Print summary by category
        category_summary = {}
        for p in products:
            cat = p.get("category", "Unknown")
            if cat not in category_summary:
                category_summary[cat] = {"count": 0, "avg_price": 0, "total_price": 0}
            category_summary[cat]["count"] += 1
            category_summary[cat]["total_price"] += p.get("price", 0)

        logger.info("📊 Product categories imported:")
        for cat, stats in category_summary.items():
            avg_price = stats["total_price"] / stats["count"]
            logger.info(f"  {cat}: {stats['count']} products, avg price: ¥{avg_price:.2f}")

        return True

    finally:
        await pool.close()


async def verify_import():
    """Verify the imported data."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return

    try:
        pool = await asyncpg.create_pool(db_url)

        # Count imported data
        store_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_stores")
        product_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_products")
        keyword_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_keywords")

        logger.info("🔍 Database verification:")
        logger.info(f"  Stores: {store_count}")
        logger.info(f"  Products: {product_count}")
        logger.info(f"  Keywords: {keyword_count}")

        # Sample stores
        stores = await pool.fetch(
            "SELECT name, rating, monthly_sales FROM competitor_stores LIMIT 5"
        )
        logger.info("📋 Sample stores in DB:")
        for store in stores:
            logger.info(
                f"  - {store['name']} (rating: {store['rating']}, sales: {store['monthly_sales']})"
            )

        await pool.close()
    except Exception as e:
        logger.warning(f"Verification failed: {e}")


async def main():
    logger.info("🚀 Starting competitor data import...")

    success = await import_json_data()
    if success:
        logger.info("✅ Import completed successfully")
        await verify_import()
    else:
        logger.error("❌ Import failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
