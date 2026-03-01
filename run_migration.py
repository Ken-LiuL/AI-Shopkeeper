#!/usr/bin/env python3

import asyncio
import sys
from pathlib import Path

from src.db.postgres import get_pool, init_pool


async def run_migration():
    """Run the competitor_keywords migration."""
    await init_pool()
    pool = get_pool()

    # Read migration file
    migration_file = Path("migrations/postgres/022_fix_competitor_keywords.sql")
    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        return 1

    migration_sql = migration_file.read_text()

    print("=== Running migration: 022_fix_competitor_keywords.sql ===")
    try:
        # Execute migration
        await pool.execute(migration_sql)
        print("✅ Migration completed successfully")

        # Verify the table was created
        tables = await pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = 'competitor_keywords';"
        )
        if tables:
            print("✅ competitor_keywords table verified")

            # Check data counts
            keyword_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_keywords")
            store_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_stores")
            product_count = await pool.fetchval("SELECT COUNT(*) FROM competitor_products")

            print("📊 Data counts:")
            print(f"  Keywords: {keyword_count}")
            print(f"  Stores: {store_count}")
            print(f"  Products: {product_count}")
        else:
            print("❌ competitor_keywords table not found after migration")
            return 1

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_migration()))
