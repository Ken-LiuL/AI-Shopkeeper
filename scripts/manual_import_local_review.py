"""Run manual-import migrations and sample imports against a local PostgreSQL instance."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.db import postgres as pg
from src.services.manual_import import ManualImportService


SAMPLES = [
    ("products", Path("sample/主档商品销售规格导出_10117665691570720260326.xlsx")),
    ("orders", Path("sample/导出订单列表+明细20260326_183806.xlsx")),
    ("inventory", Path("sample/库存查询导出_20260326.xls")),
]


async def main() -> None:
    await pg.init_pool()
    pool = pg.get_pool()
    await _reset_and_prepare_schema(pool)

    service = ManualImportService(pool)
    results = []

    for import_type, path in SAMPLES:
        result = await service.import_file(
            filename=path.name,
            content=path.read_bytes(),
            import_type=import_type,
        )
        results.append(
            {
                "import_type": result.import_type,
                "filename": result.filename,
                "rows": result.total_rows,
                "imported_rows": result.imported_rows,
                "skipped_rows": result.skipped_rows,
                "score": result.quality_report.get("score"),
                "summary": result.import_summary,
            }
        )

    summary = {
        "products": await pool.fetchval("SELECT COUNT(*) FROM products"),
        "orders": await pool.fetchval("SELECT COUNT(*) FROM orders"),
        "order_items": await pool.fetchval("SELECT COUNT(*) FROM order_items"),
        "inventory_rows": await pool.fetchval("SELECT COUNT(*) FROM qnh_inventory"),
        "qnh_products": await pool.fetchval("SELECT COUNT(*) FROM qnh_products"),
        "qnh_products_distinct_sku": await pool.fetchval(
            "SELECT COUNT(DISTINCT sku_id) FROM qnh_products"
        ),
        "qnh_products_duplicate_skus": await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM (
                SELECT sku_id
                FROM qnh_products
                GROUP BY sku_id
                HAVING COUNT(*) > 1
            ) t
            """
        ),
        "product_knowledge": await pool.fetchval("SELECT COUNT(*) FROM product_knowledge"),
        "import_runs": await pool.fetchval("SELECT COUNT(*) FROM manual_import_runs"),
        "hotsale_goods": await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
        ),
        "products_with_sales": await pool.fetchval(
            "SELECT COUNT(*) FROM products WHERE COALESCE(monthly_sales, 0) > 0"
        ),
        "products_with_stock": await pool.fetchval(
            "SELECT COUNT(*) FROM products WHERE COALESCE(stock, 0) > 0"
        ),
        "products_missing_price": await pool.fetchval(
            "SELECT COUNT(*) FROM products WHERE retail_price IS NULL OR retail_price = 0"
        ),
        "stockout_but_selling": await pool.fetchval(
            """
            SELECT COUNT(*)
            FROM products
            WHERE COALESCE(stock, 0) = 0
              AND COALESCE(monthly_sales, 0) > 0
            """
        ),
    }

    review = {
        "top_sales_products": [
            dict(row)
            for row in await pool.fetch(
                """
                SELECT product_id, name, monthly_sales, stock
                FROM products
                ORDER BY monthly_sales DESC, stock DESC
                LIMIT 10
                """
            )
        ],
        "low_stock_examples": [
            dict(row)
            for row in await pool.fetch(
                """
                SELECT product_id, name, stock, monthly_sales
                FROM products
                WHERE COALESCE(stock, 0) <= 5
                ORDER BY stock ASC, monthly_sales DESC
                LIMIT 10
                """
            )
        ],
        "recent_import_runs": [
            dict(row)
            for row in await pool.fetch(
                """
                SELECT import_type, filename, total_rows, imported_rows, skipped_rows, quality_score
                FROM manual_import_runs
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ],
    }

    print("IMPORT_RESULTS")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print("SUMMARY")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print("REVIEW")
    print(json.dumps(review, ensure_ascii=False, indent=2, default=str))

    await pg.close_pool()

async def _reset_and_prepare_schema(pool) -> None:
    statements = [
        "DROP SCHEMA public CASCADE",
        "CREATE SCHEMA public",
        """
        CREATE TABLE products (
            product_id VARCHAR(64) PRIMARY KEY,
            spu_id VARCHAR(64),
            sku_id VARCHAR(64),
            name VARCHAR(200) NOT NULL,
            barcode VARCHAR(64),
            upc_code VARCHAR(64),
            category VARCHAR(200),
            brand VARCHAR(200),
            description TEXT,
            cost_price DECIMAL(10, 2),
            retail_price DECIMAL(10, 2),
            stock INTEGER DEFAULT 0,
            monthly_sales INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'active',
            store_id VARCHAR(32),
            image_url TEXT,
            source VARCHAR(32) DEFAULT 'manual_import',
            extra JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE orders (
            order_id VARCHAR(64) PRIMARY KEY,
            platform VARCHAR(32) DEFAULT 'meituan',
            customer_phone_suffix VARCHAR(8),
            total_amount DECIMAL(10, 2),
            status VARCHAR(32),
            order_time TIMESTAMPTZ,
            delivery_address_type VARCHAR(50),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            store_id VARCHAR(32),
            customer_name VARCHAR(128),
            customer_paid DECIMAL(10, 2),
            order_date DATE,
            commission DECIMAL(10, 2) DEFAULT 0,
            delivery_fee DECIMAL(10, 2) DEFAULT 0,
            merchant_discount DECIMAL(10, 2) DEFAULT 0,
            day_seq INTEGER,
            items JSONB DEFAULT '{"products": []}'::jsonb,
            source VARCHAR(32) DEFAULT 'manual_import'
        )
        """,
        """
        CREATE TABLE order_items (
            id SERIAL PRIMARY KEY,
            order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id),
            product_id VARCHAR(64) NOT NULL REFERENCES products(product_id),
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE product_sales (
            id SERIAL PRIMARY KEY,
            product_id VARCHAR(64) NOT NULL REFERENCES products(product_id),
            sale_date DATE NOT NULL,
            quantity INTEGER DEFAULT 0,
            revenue DECIMAL(10, 2) DEFAULT 0,
            UNIQUE(product_id, sale_date)
        )
        """,
        """
        CREATE TABLE qnh_products (
            id SERIAL PRIMARY KEY,
            spu_id VARCHAR(64) NOT NULL,
            sku_id VARCHAR(64),
            name VARCHAR(500) NOT NULL,
            barcode VARCHAR(64),
            category VARCHAR(200),
            brand VARCHAR(200),
            spec VARCHAR(500),
            unit VARCHAR(32),
            cost_price DECIMAL(10, 2),
            retail_price DECIMAL(10, 2),
            status VARCHAR(32),
            extra JSONB DEFAULT '{}'::jsonb,
            synced_at TIMESTAMPTZ DEFAULT NOW(),
            stock INTEGER DEFAULT 0,
            stock_num INTEGER DEFAULT 0,
            monthly_sales INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(spu_id, sku_id)
        )
        """,
        """
        CREATE TABLE qnh_orders (
            id SERIAL PRIMARY KEY,
            order_id VARCHAR(64) NOT NULL UNIQUE,
            channel VARCHAR(32),
            store_name VARCHAR(200),
            total_amount DECIMAL(10, 2),
            paid_amount DECIMAL(10, 2),
            status VARCHAR(32),
            order_time TIMESTAMPTZ,
            delivery_fee DECIMAL(10, 2),
            packaging_fee DECIMAL(10, 2),
            customer_phone_suffix VARCHAR(8),
            items JSONB DEFAULT '[]'::jsonb,
            extra JSONB DEFAULT '{}'::jsonb,
            synced_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE qnh_inventory (
            id SERIAL PRIMARY KEY,
            store_id VARCHAR(32),
            store_name VARCHAR(200),
            sku_id VARCHAR(64),
            barcode VARCHAR(64),
            product_name VARCHAR(500),
            current_stock INTEGER,
            available_stock INTEGER,
            locked_stock INTEGER,
            cost_price DECIMAL(10, 2),
            stock_value DECIMAL(12, 2),
            warehouse VARCHAR(100),
            snapshot_time TIMESTAMPTZ DEFAULT NOW(),
            extra JSONB DEFAULT '{}'::jsonb,
            synced_at TIMESTAMPTZ DEFAULT NOW(),
            stock INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE qnh_dataset_records (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            metric_name VARCHAR(100) NOT NULL,
            metric_value NUMERIC(12, 2),
            source VARCHAR(50) DEFAULT 'manual_import',
            synced_at TIMESTAMPTZ DEFAULT NOW(),
            dataset VARCHAR(100),
            payload JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(date, metric_name)
        )
        """,
        """
        CREATE TABLE product_knowledge (
            id SERIAL PRIMARY KEY,
            spu_id TEXT NOT NULL,
            sku_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            category TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            spec TEXT DEFAULT '',
            description TEXT DEFAULT '',
            image_text TEXT DEFAULT '',
            combined_text TEXT NOT NULL,
            image_urls TEXT[] DEFAULT '{}',
            price NUMERIC(10, 2),
            status TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(spu_id, sku_id)
        )
        """,
        """
        CREATE TABLE manual_import_runs (
            run_id VARCHAR(64) PRIMARY KEY,
            import_type VARCHAR(32) NOT NULL,
            filename TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            dry_run BOOLEAN NOT NULL DEFAULT FALSE,
            detected_sheets TEXT[] DEFAULT '{}',
            total_rows INTEGER DEFAULT 0,
            imported_rows INTEGER DEFAULT 0,
            skipped_rows INTEGER DEFAULT 0,
            quality_score NUMERIC(5, 2) DEFAULT 0,
            quality_report JSONB DEFAULT '{}'::jsonb,
            import_summary JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ]
    async with pool.acquire() as conn:
        async with conn.transaction():
            for statement in statements:
                await conn.execute(statement)


if __name__ == "__main__":
    asyncio.run(main())
