#!/usr/bin/env python3
"""Quick debug script to create the missing table via direct SQL."""

import asyncio
import os

import asyncpg


async def create_table():
    # Use the production database URL
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:password@localhost/ai_store_manager"
    )

    print("Connecting to database...")
    try:
        conn = await asyncpg.connect(database_url)
        print("✅ Connected to database")

        # Create the missing table
        await conn.execute("""
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

        # Add sample data
        await conn.execute("""
            INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price)
            VALUES
                ('感冒药', 1200, 45, 25.5),
                ('维生素', 800, 32, 15.8),
                ('创可贴', 600, 28, 8.9)
            ON CONFLICT (keyword) DO NOTHING;
        """)

        print("✅ Sample data added")

        # Verify
        count = await conn.fetchval("SELECT COUNT(*) FROM competitor_keywords")
        print(f"✅ competitor_keywords table has {count} rows")

        await conn.close()
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(create_table())
    if success:
        print("✅ All done!")
    else:
        print("❌ Failed!")
