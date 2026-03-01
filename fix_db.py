#!/usr/bin/env python3

import asyncio
import sys

from src.db.postgres import get_pool, init_pool


async def main():
    # Initialize the database pool
    await init_pool()
    pool = get_pool()

    print("=== Checking competitor tables ===")
    try:
        result = await pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'competitor%' ORDER BY tablename;"
        )
        print("Existing competitor tables:")
        for row in result:
            print(f"  - {row['tablename']}")

        # Check if competitor_keywords exists
        keywords_exists = any(row["tablename"] == "competitor_keywords" for row in result)
        if not keywords_exists:
            print("\n❌ competitor_keywords table missing, creating...")
            await pool.execute("""
                CREATE TABLE IF NOT EXISTS competitor_keywords (
                    keyword      TEXT PRIMARY KEY,
                    search_volume INTEGER DEFAULT 0,
                    result_count INTEGER DEFAULT 0,
                    avg_price    REAL DEFAULT 0,
                    last_synced  TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_competitor_keywords_volume ON competitor_keywords(search_volume DESC);
                CREATE INDEX IF NOT EXISTS idx_competitor_keywords_synced ON competitor_keywords(last_synced);
            """)
            print("✅ competitor_keywords table created")
        else:
            print("✅ competitor_keywords table exists")

        # Add some sample data for testing
        print("\n=== Adding sample competitor data ===")
        await pool.execute("""
            INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price)
            VALUES
                ('感冒药', 1200, 45, 25.5),
                ('维生素', 800, 32, 15.8),
                ('创可贴', 600, 28, 8.9)
            ON CONFLICT (keyword) DO NOTHING;
        """)

        await pool.execute("""
            INSERT INTO competitor_stores (store_id, name, rating, monthly_sales, category)
            VALUES
                ('test_store_1', '测试药店A', 4.5, 1500, 'pharmacy'),
                ('test_store_2', '测试药店B', 4.2, 1200, 'pharmacy')
            ON CONFLICT (store_id) DO NOTHING;
        """)

        await pool.execute("""
            INSERT INTO competitor_products (product_id, store_id, name, price, monthly_sales, rating, category)
            VALUES
                ('cp_1', 'test_store_1', '感冒灵颗粒', 18.5, 200, 4.3, 'cold_medicine'),
                ('cp_2', 'test_store_2', '维生素C片', 12.8, 150, 4.1, 'vitamins')
            ON CONFLICT (product_id) DO NOTHING;
        """)

        print("✅ Sample competitor data added")

        # Verify data exists
        keyword_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_keywords")
        store_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_stores")
        product_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_products")

        print("\n=== Data counts ===")
        print(f"Keywords: {keyword_count}")
        print(f"Stores: {store_count}")
        print(f"Products: {product_count}")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
