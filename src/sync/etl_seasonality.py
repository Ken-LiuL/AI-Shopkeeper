from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

_SEASONALITY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS product_seasonality (
    id SERIAL PRIMARY KEY,
    product_name TEXT,
    peak_months INT[],
    seasonal_tag TEXT,
    avg_monthly_sales NUMERIC,
    peak_ratio NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_name)
);
"""

_SEASON_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("感冒", "流感", "退烧", "咳嗽", "止咳"), "冬季"),
    (("防晒", "晒后", "驱蚊", "清凉", "中暑"), "夏季"),
    (("过敏", "鼻炎", "花粉", "抗敏"), "春季"),
]


def _infer_seasonal_tag(product_name: str, peak_months: list[int]) -> str:
    lowered = (product_name or "").lower()
    for keywords, tag in _SEASON_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return tag

    season_votes = {"春季": 0, "夏季": 0, "秋季": 0, "冬季": 0}
    for month in peak_months:
        if month in (3, 4, 5):
            season_votes["春季"] += 1
        elif month in (6, 7, 8):
            season_votes["夏季"] += 1
        elif month in (9, 10, 11):
            season_votes["秋季"] += 1
        else:
            season_votes["冬季"] += 1

    winner = max(season_votes, key=season_votes.get)
    return winner if season_votes[winner] > 0 else "全年"


async def run_seasonality_etl(pool) -> None:
    """聚合商品月销量并打季节性标签。"""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_SEASONALITY_TABLE_SQL)
            rows = await conn.fetch(
                """
                SELECT
                    product_name,
                    EXTRACT(MONTH FROM date)::INT AS month_no,
                    SUM(COALESCE(quantity_sold, 0))::NUMERIC AS total_qty
                FROM qnh_sales_history
                WHERE product_name IS NOT NULL
                  AND product_name <> ''
                GROUP BY product_name, month_no
                """
            )

            monthly_map: dict[str, dict[int, float]] = defaultdict(dict)
            for row in rows:
                product_name = str(row["product_name"]).strip()
                if not product_name:
                    continue
                month_no = int(row["month_no"])
                qty = float(row["total_qty"] or 0)
                monthly_map[product_name][month_no] = qty

            if not monthly_map:
                logger.info("Seasonality ETL done: no sales history rows")
                return

            upserts: list[tuple[str, list[int], str, float, float]] = []
            for product_name, month_values in monthly_map.items():
                if not month_values:
                    continue
                total_sales = float(sum(month_values.values()))
                if total_sales <= 0:
                    continue

                peak_value = max(month_values.values())
                peak_months = sorted(
                    month for month, value in month_values.items() if value == peak_value
                )
                peak_ratio = float(peak_value / total_sales) if total_sales > 0 else 0.0
                avg_monthly_sales = float(total_sales / 12.0)
                seasonal_tag = _infer_seasonal_tag(product_name, peak_months)
                upserts.append(
                    (
                        product_name,
                        peak_months,
                        seasonal_tag,
                        avg_monthly_sales,
                        peak_ratio,
                    )
                )

            if not upserts:
                logger.info("Seasonality ETL done: no valid products after aggregation")
                return

            await conn.executemany(
                """
                INSERT INTO product_seasonality (
                    product_name,
                    peak_months,
                    seasonal_tag,
                    avg_monthly_sales,
                    peak_ratio,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (product_name) DO UPDATE SET
                    peak_months = EXCLUDED.peak_months,
                    seasonal_tag = EXCLUDED.seasonal_tag,
                    avg_monthly_sales = EXCLUDED.avg_monthly_sales,
                    peak_ratio = EXCLUDED.peak_ratio,
                    updated_at = NOW()
                """,
                upserts,
            )
            logger.info("Seasonality ETL done: upserted=%d", len(upserts))
    except Exception:
        logger.exception("Seasonality ETL failed")
