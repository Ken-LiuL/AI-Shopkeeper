"""Competitor analysis API routes."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .schemas import APIResponse, PaginatedResponse

router = APIRouter(prefix="/api/competitors", tags=["competitors"])


@router.get("/stores", response_model=PaginatedResponse[dict])
async def list_stores(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        # Filter out test data stores
        total = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM competitor_stores WHERE name NOT LIKE '测试药店%'"
            )
            or 0
        )
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            """SELECT * FROM competitor_stores
               WHERE name NOT LIKE '测试药店%'
               ORDER BY last_synced DESC LIMIT $1 OFFSET $2""",
            page_size,
            offset,
        )

        # If no real competitor data, provide helpful message
        if total == 0:
            return PaginatedResponse(
                data=[],
                total=0,
                page=page,
                page_size=page_size,
                message="暂无竞品数据，需配置竞品店铺",
            )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/stores/{store_id}/products", response_model=PaginatedResponse[dict])
async def store_products(
    store_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        total = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM competitor_products WHERE store_id = $1",
                store_id,
            )
            or 0
        )
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            "SELECT * FROM competitor_products WHERE store_id = $1 ORDER BY last_synced DESC LIMIT $2 OFFSET $3",
            store_id,
            page_size,
            offset,
        )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/products", response_model=PaginatedResponse[dict])
async def search_competitor_products(
    q: str | None = Query(None),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = 0
    rows = []
    with contextlib.suppress(Exception):
        conditions: list[str] = []
        params: list = []
        idx = 1
        if q:
            conditions.append(f"name ILIKE ${idx}")
            params.append(f"%{q}%")
            idx += 1
        if category:
            conditions.append(f"category = ${idx}")
            params.append(category)
            idx += 1
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        # Note: total is approximate for price-comparison since it's a join
        total = (
            await pool.fetchval(f"SELECT COUNT(*) FROM competitor_products{where}", *params) or 0
        )
        offset = (page - 1) * page_size
        rows = await pool.fetch(
            f"SELECT * FROM competitor_products{where} ORDER BY last_synced DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            page_size,
            offset,
        )
    return PaginatedResponse(
        data=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/keywords", response_model=APIResponse[list[dict]])
async def hot_keywords(
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT keyword, search_volume, result_count, avg_price, last_synced
               FROM competitor_keywords ORDER BY search_volume DESC LIMIT $1""",
            limit,
        )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/price-comparison", response_model=APIResponse[list[dict]])
async def price_comparison(
    product_id: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = []
    with contextlib.suppress(Exception):
        conditions: list[str] = []
        params: list = []
        idx = 1
        if product_id:
            conditions.append(f"p.spu_id = ${idx}")
            params.append(product_id)
            idx += 1
        if category:
            conditions.append(f"p.category = ${idx}")
            params.append(category)
            idx += 1
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await pool.fetch(
            f"""SELECT p.spu_id AS product_id, p.name, p.retail_price AS our_price,
                       cp.name AS competitor_name, cp.price AS competitor_price,
                       cs.name AS competitor_store,
                       ROUND(((p.retail_price - cp.price) / NULLIF(cp.price, 0) * 100)::numeric, 2) AS price_diff_pct
                FROM qnh_products p
                JOIN competitor_products cp ON (
                    -- Better matching: same category AND reasonable price range
                    cp.category = p.category 
                    AND cp.price > 0 AND p.retail_price > 0
                    AND (
                        -- Only allow price differences within 10x bounds
                        cp.price <= p.retail_price * 10 
                        AND cp.price >= p.retail_price * 0.1
                    )
                )
                LEFT JOIN competitor_stores cs ON cp.store_id = cs.store_id
                {where}
                ORDER BY 
                    -- Prioritize similar price ranges
                    ABS(p.retail_price - cp.price) ASC
                LIMIT ${idx}""",
            *params,
        )
    return APIResponse(data=[dict(r) for r in rows])


@router.post("/fix-schema")
async def fix_competitor_schema() -> APIResponse[dict]:
    """Manually apply competitor table schema fixes."""
    pool = pg.get_pool()

    migration_sql = """
    -- Drop old tables if they have wrong schema
    DROP TABLE IF EXISTS competitor_products CASCADE;
    DROP TABLE IF EXISTS competitor_stores CASCADE;
    DROP TABLE IF EXISTS competitor_keywords CASCADE;

    -- Recreate with correct schema
    CREATE TABLE IF NOT EXISTS competitor_stores (
        store_id    TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        rating      REAL DEFAULT 0,
        monthly_sales INTEGER DEFAULT 0,
        distance_km REAL DEFAULT 0,
        lat         REAL DEFAULT 0,
        lng         REAL DEFAULT 0,
        category    TEXT DEFAULT '',
        last_synced TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_competitor_stores_category ON competitor_stores(category);
    CREATE INDEX IF NOT EXISTS idx_competitor_stores_distance ON competitor_stores(distance_km);
    CREATE INDEX IF NOT EXISTS idx_competitor_stores_synced ON competitor_stores(last_synced);

    -- Recreate competitor_products with correct schema
    CREATE TABLE IF NOT EXISTS competitor_products (
        product_id  TEXT PRIMARY KEY,
        store_id    TEXT DEFAULT '' REFERENCES competitor_stores(store_id) ON DELETE SET DEFAULT,
        name        TEXT NOT NULL,
        price       REAL DEFAULT 0,
        monthly_sales INTEGER DEFAULT 0,
        rating      REAL DEFAULT 0,
        category    TEXT DEFAULT '',
        last_synced TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_competitor_products_store ON competitor_products(store_id);
    CREATE INDEX IF NOT EXISTS idx_competitor_products_category ON competitor_products(category);
    CREATE INDEX IF NOT EXISTS idx_competitor_products_sales ON competitor_products(monthly_sales DESC);
    CREATE INDEX IF NOT EXISTS idx_competitor_products_synced ON competitor_products(last_synced);

    -- Create competitor_keywords table
    CREATE TABLE IF NOT EXISTS competitor_keywords (
        keyword      TEXT PRIMARY KEY,
        search_volume INTEGER DEFAULT 0,
        result_count INTEGER DEFAULT 0,
        avg_price    REAL DEFAULT 0,
        last_synced  TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_competitor_keywords_volume ON competitor_keywords(search_volume DESC);
    CREATE INDEX IF NOT EXISTS idx_competitor_keywords_synced ON competitor_keywords(last_synced);

    -- Add sample data for testing
    INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price)
    VALUES
        ('感冒药', 1200, 45, 25.5),
        ('维生素', 800, 32, 15.8),
        ('创可贴', 600, 28, 8.9)
    ON CONFLICT (keyword) DO NOTHING;

    -- Add sample competitor stores if they don't exist
    INSERT INTO competitor_stores (store_id, name, rating, monthly_sales, category)
    VALUES
        ('test_store_1', '测试药店A', 4.5, 1500, 'pharmacy'),
        ('test_store_2', '测试药店B', 4.2, 1200, 'pharmacy')
    ON CONFLICT (store_id) DO NOTHING;

    -- Add sample competitor products if they don't exist
    INSERT INTO competitor_products (product_id, store_id, name, price, monthly_sales, rating, category)
    VALUES
        ('cp_1', 'test_store_1', '感冒灵颗粒', 18.5, 200, 4.3, 'cold_medicine'),
        ('cp_2', 'test_store_2', '维生素C片', 12.8, 150, 4.1, 'vitamins')
    ON CONFLICT (product_id) DO NOTHING;
    """

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Split and execute statements
                statements = [s.strip() for s in migration_sql.split(";") if s.strip()]
                for stmt in statements:
                    if stmt:
                        await conn.execute(stmt)

        # Mark migration as applied
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO _migrations (filename) VALUES ($1) ON CONFLICT (filename) DO NOTHING",
                "022_fix_competitor_keywords.sql",
            )

        return APIResponse(
            data={
                "message": "Schema fixed successfully",
                "tables_created": [
                    "competitor_stores",
                    "competitor_products",
                    "competitor_keywords",
                ],
            }
        )
    except Exception as e:
        return APIResponse(data={"error": f"Migration failed: {str(e)}"}, success=False)


# deploy 1772344622
