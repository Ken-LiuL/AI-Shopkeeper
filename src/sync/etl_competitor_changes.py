from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_COMPETITOR_CHANGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS competitor_price_changes (
    id SERIAL PRIMARY KEY,
    product_name TEXT,
    store_name TEXT,
    old_price NUMERIC,
    new_price NUMERIC,
    change_pct NUMERIC,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


async def _pick_existing_column(conn, table: str, candidates: list[str]) -> str | None:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        """,
        table,
    )
    available = {row["column_name"] for row in rows}
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


async def run_competitor_changes_etl(pool) -> None:
    """检测竞品价格变化并写入 competitor_price_changes。"""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_COMPETITOR_CHANGE_TABLE_SQL)

            product_col = await _pick_existing_column(
                conn,
                "competitor_products",
                ["product_name", "name"],
            )
            store_col = await _pick_existing_column(
                conn,
                "competitor_products",
                ["store_name", "competitor_name", "store_id"],
            )
            price_col = await _pick_existing_column(conn, "competitor_products", ["price"])
            time_col = await _pick_existing_column(
                conn,
                "competitor_products",
                ["updated_at", "last_synced", "created_at", "synced_at"],
            )

            if not product_col or not store_col or not price_col or not time_col:
                logger.warning(
                    "Skip competitor change ETL: missing columns product=%s store=%s price=%s time=%s",
                    product_col,
                    store_col,
                    price_col,
                    time_col,
                )
                return

            product_ident = _quote_ident(product_col)
            store_ident = _quote_ident(store_col)
            price_ident = _quote_ident(price_col)
            time_ident = _quote_ident(time_col)

            result = await conn.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        {product_ident}::text AS product_name,
                        {store_ident}::text AS store_name,
                        {price_ident}::numeric AS price,
                        COALESCE({time_ident}::timestamptz, NOW()) AS ts,
                        ROW_NUMBER() OVER (
                            PARTITION BY {product_ident}::text, {store_ident}::text
                            ORDER BY COALESCE({time_ident}::timestamptz, NOW()) DESC
                        ) AS rn
                    FROM competitor_products
                    WHERE {product_ident} IS NOT NULL
                      AND {store_ident} IS NOT NULL
                      AND {price_ident} IS NOT NULL
                ),
                latest AS (
                    SELECT product_name, store_name, price
                    FROM ranked
                    WHERE rn = 1
                ),
                previous AS (
                    SELECT product_name, store_name, price
                    FROM ranked
                    WHERE rn = 2
                )
                INSERT INTO competitor_price_changes (
                    product_name,
                    store_name,
                    old_price,
                    new_price,
                    change_pct
                )
                SELECT
                    l.product_name,
                    l.store_name,
                    p.price AS old_price,
                    l.price AS new_price,
                    CASE
                        WHEN p.price = 0 THEN NULL
                        ELSE ROUND(((l.price - p.price) / p.price) * 100, 4)
                    END AS change_pct
                FROM latest l
                JOIN previous p
                  ON l.product_name = p.product_name
                 AND l.store_name = p.store_name
                WHERE
                    ABS(l.price - p.price) > 5
                    OR (
                        p.price <> 0
                        AND ABS(((l.price - p.price) / p.price) * 100) > 5
                    )
                """
            )
            logger.info("Competitor change ETL done: %s", result)
    except Exception:
        logger.exception("Competitor change ETL failed")
