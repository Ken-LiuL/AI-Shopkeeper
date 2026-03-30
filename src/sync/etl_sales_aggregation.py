"""
ETL: 从 qnh_orders 订单数据聚合生成销售历史和日指标

目标表：
  - qnh_sales_history  : 每个商品每天的销量和收入（从 items JSONB 展开）
  - qnh_daily_metrics  : 每天的总 GMV、订单数、客单价等汇总指标

特性：
  - 纯 SQL 聚合，无外部 API 依赖
  - ON CONFLICT DO UPDATE 幂等执行
  - 支持全量回刷和增量（指定 since_date）
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ── SQL: qnh_sales_history ────────────────────────────────────────────────────
# 从 qnh_orders.items (JSONB array) 展开，按日期 + spu_id 聚合。
# items 格式: [{name, qty, price, sku_id}, ...]
_SQL_UPSERT_SALES_HISTORY = """
WITH exploded AS (
    SELECT
        DATE(o.order_time AT TIME ZONE 'Asia/Shanghai') AS sale_date,
        COALESCE(item->>'sku_id', 'unknown') AS spu_id,
        COALESCE(item->>'name', '未知商品')   AS product_name,
        COALESCE((item->>'qty')::NUMERIC, 0)  AS qty,
        COALESCE((item->>'price')::NUMERIC, 0) AS unit_price
    FROM qnh_orders o,
         LATERAL jsonb_array_elements(
             CASE
                 WHEN jsonb_typeof(o.items) = 'array' THEN o.items
                 ELSE '[]'::JSONB
             END
         ) AS item
    WHERE o.order_time IS NOT NULL
      AND o.order_time >= $1::DATE
      AND o.order_time <  $2::DATE + INTERVAL '1 day'
      AND COALESCE(o.status, '') NOT IN ('cancelled', 'refunded')
),
agg AS (
    SELECT
        sale_date,
        spu_id,
        MAX(product_name)    AS product_name,
        SUM(qty)::INTEGER    AS quantity_sold,
        SUM(qty * unit_price) AS revenue
    FROM exploded
    GROUP BY sale_date, spu_id
)
INSERT INTO qnh_sales_history (date, spu_id, product_name, quantity_sold, revenue, synced_at)
SELECT sale_date, spu_id, product_name, quantity_sold, revenue, NOW()
FROM agg
ON CONFLICT (date, spu_id) DO UPDATE SET
    product_name  = EXCLUDED.product_name,
    quantity_sold = EXCLUDED.quantity_sold,
    revenue       = EXCLUDED.revenue,
    synced_at     = NOW()
"""

# ── SQL: qnh_daily_metrics ────────────────────────────────────────────────────
# 按日期 + channel 聚合，channel=NULL 时表示全渠道汇总。
_SQL_UPSERT_DAILY_METRICS = """
WITH daily AS (
    SELECT
        DATE(order_time AT TIME ZONE 'Asia/Shanghai') AS metric_date,
        channel,
        COUNT(*)                              AS valid_order_count,
        SUM(COALESCE(total_amount, 0))        AS valid_order_amount,
        AVG(COALESCE(total_amount, 0))        AS avg_order_value,
        SUM(COALESCE(paid_amount, 0))         AS paid_amount_sum,
        AVG(COALESCE(paid_amount, 0))         AS paid_avg_order_value,
        SUM(COALESCE(delivery_fee, 0))        AS delivery_fee_sum,
        SUM(COALESCE(packaging_fee, 0))       AS packaging_fee_sum,
        COUNT(DISTINCT customer_phone_suffix) AS customer_count
    FROM qnh_orders
    WHERE order_time IS NOT NULL
      AND order_time >= $1::DATE
      AND order_time <  $2::DATE + INTERVAL '1 day'
      AND COALESCE(status, '') NOT IN ('cancelled', 'refunded')
    GROUP BY DATE(order_time AT TIME ZONE 'Asia/Shanghai'), channel
),
all_channel AS (
    SELECT
        DATE(order_time AT TIME ZONE 'Asia/Shanghai') AS metric_date,
        NULL::VARCHAR(32)                             AS channel,
        COUNT(*)                              AS valid_order_count,
        SUM(COALESCE(total_amount, 0))        AS valid_order_amount,
        AVG(COALESCE(total_amount, 0))        AS avg_order_value,
        SUM(COALESCE(paid_amount, 0))         AS paid_amount_sum,
        AVG(COALESCE(paid_amount, 0))         AS paid_avg_order_value,
        SUM(COALESCE(delivery_fee, 0))        AS delivery_fee_sum,
        SUM(COALESCE(packaging_fee, 0))       AS packaging_fee_sum,
        COUNT(DISTINCT customer_phone_suffix) AS customer_count
    FROM qnh_orders
    WHERE order_time IS NOT NULL
      AND order_time >= $1::DATE
      AND order_time <  $2::DATE + INTERVAL '1 day'
      AND COALESCE(status, '') NOT IN ('cancelled', 'refunded')
    GROUP BY DATE(order_time AT TIME ZONE 'Asia/Shanghai')
),
combined AS (
    SELECT * FROM daily
    UNION ALL
    SELECT * FROM all_channel
)
INSERT INTO qnh_daily_metrics (
    metric_date, channel,
    valid_order_count, valid_order_amount, avg_order_value,
    paid_amount, paid_avg_order_value,
    delivery_fee, packaging_fee,
    customer_count,
    synced_at
)
SELECT
    metric_date, channel,
    valid_order_count, valid_order_amount, ROUND(avg_order_value::NUMERIC, 2),
    paid_amount_sum, ROUND(paid_avg_order_value::NUMERIC, 2),
    delivery_fee_sum, packaging_fee_sum,
    customer_count,
    NOW()
FROM combined
ON CONFLICT (metric_date, channel, store_id) DO UPDATE SET
    valid_order_count    = EXCLUDED.valid_order_count,
    valid_order_amount   = EXCLUDED.valid_order_amount,
    avg_order_value      = EXCLUDED.avg_order_value,
    paid_amount          = EXCLUDED.paid_amount,
    paid_avg_order_value = EXCLUDED.paid_avg_order_value,
    delivery_fee         = EXCLUDED.delivery_fee,
    packaging_fee        = EXCLUDED.packaging_fee,
    customer_count       = EXCLUDED.customer_count,
    synced_at            = NOW()
"""

# store_id 字段是 NOT NULL UNIQUE 的一部分，需要提供 NULL 占位
_SQL_UPSERT_DAILY_METRICS_WITH_STORE = _SQL_UPSERT_DAILY_METRICS.replace(
    "INSERT INTO qnh_daily_metrics (",
    "INSERT INTO qnh_daily_metrics (store_id, ",
).replace(
    "SELECT\n    metric_date, channel,",
    "SELECT\n    NULL::VARCHAR(32) AS store_id, metric_date, channel,",
)


async def run_sales_aggregation_etl(
    pool: Any,
    *,
    since_date: date | None = None,
    until_date: date | None = None,
    days_back: int = 90,
) -> dict[str, Any]:
    """聚合订单数据，填充 qnh_sales_history 和 qnh_daily_metrics。

    Args:
        pool:        asyncpg 连接池
        since_date:  聚合起始日期（含），默认从今天往前 days_back 天
        until_date:  聚合截止日期（含），默认为今天
        days_back:   since_date 未指定时往前回溯的天数

    Returns:
        包含 sales_history_rows 和 daily_metrics_rows 的结果字典
    """
    today = date.today()
    if until_date is None:
        until_date = today
    if since_date is None:
        since_date = today - timedelta(days=days_back)

    logger.info(
        "Sales aggregation ETL: %s → %s", since_date.isoformat(), until_date.isoformat()
    )

    results: dict[str, Any] = {
        "since_date": since_date.isoformat(),
        "until_date": until_date.isoformat(),
        "sales_history_status": "skipped",
        "daily_metrics_status": "skipped",
        "errors": [],
    }

    async with pool.acquire() as conn:
        # ── 1. qnh_sales_history ──────────────────────────────────────
        try:
            status = await conn.execute(_SQL_UPSERT_SALES_HISTORY, since_date, until_date)
            rows = int(status.split()[-1]) if status else 0
            results["sales_history_status"] = "ok"
            results["sales_history_rows"] = rows
            logger.info("qnh_sales_history upserted: %s", status)
        except Exception as exc:
            msg = f"qnh_sales_history failed: {exc}"
            logger.error(msg)
            results["sales_history_status"] = "error"
            results["errors"].append(msg)

        # ── 2. qnh_daily_metrics ──────────────────────────────────────
        try:
            # 先检测 store_id 是否允许 NULL（有些环境 UNIQUE 含 store_id）
            # 直接尝试，让 DB 告诉我们约束情况
            status = await conn.execute(
                _SQL_UPSERT_DAILY_METRICS, since_date, until_date
            )
            rows = int(status.split()[-1]) if status else 0
            results["daily_metrics_status"] = "ok"
            results["daily_metrics_rows"] = rows
            logger.info("qnh_daily_metrics upserted: %s", status)
        except Exception as exc:
            msg = f"qnh_daily_metrics failed: {exc}"
            logger.error(msg)
            results["daily_metrics_status"] = "error"
            results["errors"].append(msg)

    success = not results["errors"]
    results["success"] = success
    if success:
        logger.info("Sales aggregation ETL completed successfully")
    else:
        logger.warning("Sales aggregation ETL completed with errors: %s", results["errors"])

    return results
