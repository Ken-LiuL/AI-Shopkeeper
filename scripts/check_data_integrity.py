"""Check DB data integrity for expected AI-Shopkeeper tables."""

from __future__ import annotations

import asyncio
import os
from typing import Final


EXPECTED_TABLES: Final[list[str]] = [
    "qnh_products",
    "qnh_orders_raw",
    "qnh_reviews_raw",
    "qnh_store_metrics_raw",
    "qnh_refunds",
    "qnh_daily_metrics",
    "qnh_sales_history",
    "qnh_review_analysis",
    "qnh_promotions",
    "qnh_dataset_records",
    "qnh_traffic",
    "qnh_inventory",
    "qnh_customers",
    "qnh_traffic_channels",
    "competitor_products",
    "product_associations",
    "product_seasonality",
    "auto_faq",
    "delivery_timeouts",
    "platform_penalties",
    "policy_documents",
    "category_mapping",
    "store_category_tree",
    "sync_state",
    "merchant_sync_cookies",
]

KEY_COLUMNS: Final[dict[str, list[str]]] = {
    "qnh_products": ["spu_id", "sku_id", "name"],
    "qnh_orders_raw": ["record_id", "content", "synced_at"],
    "qnh_reviews_raw": ["record_id", "content", "synced_at"],
    "qnh_store_metrics_raw": ["record_id", "content", "synced_at"],
    "qnh_refunds": ["id", "refund_id", "created_at"],
    "qnh_daily_metrics": ["id", "metric_date", "created_at"],
    "qnh_sales_history": ["id", "sale_date", "created_at"],
    "qnh_review_analysis": ["id", "review_id", "created_at"],
    "qnh_promotions": ["id", "promotion_id", "created_at"],
    "qnh_dataset_records": ["id", "dataset_type", "created_at"],
    "qnh_traffic": ["id", "stat_date", "created_at"],
    "qnh_inventory": ["id", "sku_id", "updated_at"],
    "qnh_customers": ["id", "customer_id", "created_at"],
    "qnh_traffic_channels": ["id", "channel", "created_at"],
    "competitor_products": ["id", "product_name", "created_at"],
    "product_associations": ["id", "product_a", "product_b"],
    "product_seasonality": ["id", "product_id", "season"],
    "auto_faq": ["id", "question", "answer"],
    "delivery_timeouts": ["id", "order_id", "timeout_minutes"],
    "platform_penalties": ["id", "penalty_type", "occurred_at"],
    "policy_documents": ["id", "source_url", "updated_at"],
    "category_mapping": ["id", "source_category", "target_category"],
    "store_category_tree": ["id", "store_id", "category_id"],
    "sync_state": ["id", "syncer_name", "updated_at"],
    "merchant_sync_cookies": ["id", "cookie_json", "updated_at"],
}


async def _table_exists(conn, table_name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table_name,
        )
    )


async def _record_count(conn, table_name: str) -> int:
    return int(await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"'))


async def _columns(conn, table_name: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        table_name,
    )
    return [str(r["column_name"]) for r in rows]


def _format_cols(cols: list[str], limit: int = 8) -> str:
    if len(cols) <= limit:
        return ", ".join(cols)
    return f"{', '.join(cols[:limit])}, ..."


async def main() -> int:
    try:
        import asyncpg
    except ModuleNotFoundError:
        print("❌ missing dependency: asyncpg")
        return 2

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL not set")
        return 2

    conn = await asyncpg.connect(database_url)
    ok = 0
    warn = 0
    fail = 0

    try:
        print("== AI-Shopkeeper Data Integrity Check ==")
        for table in EXPECTED_TABLES:
            if not await _table_exists(conn, table):
                print(f"❌ {table} (missing table)")
                fail += 1
                continue

            cols = await _columns(conn, table)
            count = await _record_count(conn, table)
            required = KEY_COLUMNS.get(table, [])
            missing_cols = [c for c in required if c not in cols]

            if missing_cols:
                print(
                    f"❌ {table} ({count} records) "
                    f"[missing cols: {', '.join(missing_cols)}] "
                    f"[列: {_format_cols(cols)}]"
                )
                fail += 1
                continue

            if count == 0:
                print(f"⚠️  {table} (0 records) [列: {_format_cols(cols)}]")
                warn += 1
            else:
                print(f"✅ {table} ({count} records) [列: {_format_cols(cols)}]")
                ok += 1

        print("\n== Summary ==")
        print(f"✅ ok: {ok}")
        print(f"⚠️  empty: {warn}")
        print(f"❌ failed: {fail}")
        return 1 if fail else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
