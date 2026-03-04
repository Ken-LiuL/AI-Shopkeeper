#!/usr/bin/env python3
"""ETL qnh_* data into business tables (products/orders/sales/etc)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg

NUMBER_CLEAN = re.compile(r"[^0-9.\-]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load qnh_ source tables into structured business tables "
            "(products, sales_history, qnh_daily_metrics, alerts, price_history)."
        )
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL connection string (falls back to $DATABASE_URL)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for bulk upserts (default: 200)",
    )
    return parser.parse_args()


def chunked(seq: Sequence[Any] | list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _unwrap_value(field: Any) -> Any:
    if field is None:
        return None
    if isinstance(field, int | float | Decimal):
        return field
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        for key in ("dataValue", "value", "originValue", "dataName"):
            if key in field and field[key] not in (None, ""):
                return field[key]
        for nested_key in ("indicValue", "reference", "lastPeriodValue"):
            nested = field.get(nested_key)
            if isinstance(nested, dict):
                unwrapped = _unwrap_value(nested)
                if unwrapped not in (None, ""):
                    return unwrapped
    return field


def parse_number(field: Any) -> float:
    raw = _unwrap_value(field)
    if raw in (None, "", "--"):
        return 0.0
    if isinstance(raw, int | float | Decimal):
        return float(raw)
    cleaned = NUMBER_CLEAN.sub("", str(raw))
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_str(field: Any) -> str:
    raw = _unwrap_value(field)
    if raw in (None, ""):
        return ""
    return str(raw).strip()


def normalize_status(value: str | None) -> str:
    if not value:
        return "inactive"
    norm = value.strip().lower()
    mapping = {
        "在售": "active",
        "上架": "active",
        "active": "active",
        "下架": "delisted",
        "已下架": "delisted",
        "停售": "inactive",
        "停用": "inactive",
        "inactive": "inactive",
    }
    return mapping.get(norm, "active" if "售" in norm else "inactive")


async def executemany(conn: asyncpg.Connection, sql: str, rows: list[tuple], batch: int) -> None:
    for chunk in chunked(rows, batch):
        await conn.executemany(sql, chunk)


async def sync_products(pool: asyncpg.Pool, batch_size: int) -> dict[str, int]:
    rows = await pool.fetch("SELECT * FROM qnh_products")
    if not rows:
        logging.warning("qnh_products table is empty — nothing to sync")
        return {"upserts": 0, "active": 0}

    upserts: list[tuple[Any, ...]] = []
    active_count = 0
    for record in rows:
        row = dict(record)
        product_id = row.get("spu_id") or row.get("sku_id")
        name = row.get("name")
        if not product_id or not name:
            continue

        status = normalize_status(row.get("status"))
        if status == "active":
            active_count += 1

        stock = row.get("stock_num")
        if stock in (None, 0):
            stock = row.get("stock")
        if stock in (None, 0):
            stock = row.get("available_stock")
        stock = int(stock or 0)

        monthly_sales = row.get("monthly_sales")
        if monthly_sales is None:
            monthly_sales = row.get("sale_month")
        monthly_sales = int(monthly_sales or 0)

        description = row.get("spec") or row.get("unit")

        upserts.append(
            (
                str(product_id),
                name,
                row.get("barcode"),
                row.get("category"),
                row.get("brand"),
                description,
                row.get("cost_price"),
                row.get("retail_price"),
                stock,
                monthly_sales,
                status,
            )
        )

    sql = """
        INSERT INTO products (product_id, name, barcode, category, brand, description,
                              cost_price, retail_price, stock, monthly_sales, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (product_id) DO UPDATE SET
            name = EXCLUDED.name,
            barcode = EXCLUDED.barcode,
            category = EXCLUDED.category,
            brand = EXCLUDED.brand,
            description = EXCLUDED.description,
            cost_price = EXCLUDED.cost_price,
            retail_price = EXCLUDED.retail_price,
            stock = EXCLUDED.stock,
            monthly_sales = EXCLUDED.monthly_sales,
            status = EXCLUDED.status,
            updated_at = NOW()
    """

    async with pool.acquire() as conn:
        await executemany(conn, sql, upserts, batch_size)

    logging.info("Products upserted: %d (active=%d)", len(upserts), active_count)
    return {"upserts": len(upserts), "active": active_count}


async def build_product_index(pool: asyncpg.Pool) -> dict[str, str]:
    rows = await pool.fetch("SELECT product_id, name FROM products")
    index: dict[str, str] = {}
    for record in rows:
        name = (record["name"] or "").strip().lower()
        if not name:
            continue
        index.setdefault(name, record["product_id"])
    logging.info("Product name index loaded (%d entries)", len(index))
    return index


async def sync_sales_history(
    pool: asyncpg.Pool, product_index: dict[str, str], batch_size: int
) -> dict[str, int]:
    rows = await pool.fetch(
        """SELECT record_key, payload, synced_at
            FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"""
    )
    if not rows:
        logging.warning("No hotsale_goods dataset rows found")
        return {"upserts": 0, "unmatched": 0}

    aggregated: dict[tuple[str, datetime], dict[str, float]] = defaultdict(
        lambda: {"quantity": 0.0, "revenue": 0.0}
    )
    unmatched = 0

    for record in rows:
        payload = record["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        elif payload is None:
            payload = {}

        if not isinstance(payload, dict):
            continue

        name = parse_str(payload.get("product_name"))
        if not name:
            continue
        product_id = product_index.get(name.lower())
        if not product_id:
            unmatched += 1
            continue

        qty = int(round(parse_number(payload.get("prod_sale_num_gmv"))))
        revenue = parse_number(payload.get("prod_actual_pay_amt")) or parse_number(
            payload.get("prod_sale_amt")
        )
        sale_date = (record["synced_at"] or datetime.now(UTC)).date()
        key = (product_id, sale_date)
        aggregated[key]["quantity"] += qty
        aggregated[key]["revenue"] += revenue

    upserts: list[tuple[Any, ...]] = []
    for (product_id, sale_date), metrics in aggregated.items():
        upserts.append(
            (
                product_id,
                sale_date,
                int(metrics["quantity"]),
                round(metrics["revenue"], 2),
            )
        )

    if not upserts:
        return {"upserts": 0, "unmatched": unmatched}

    sql = """
        INSERT INTO sales_history (product_id, sale_date, quantity, revenue)
        VALUES ($1,$2,$3,$4)
        ON CONFLICT (product_id, sale_date)
        DO UPDATE SET quantity = EXCLUDED.quantity, revenue = EXCLUDED.revenue
    """

    async with pool.acquire() as conn:
        await executemany(conn, sql, upserts, batch_size)

    logging.info(
        "Sales history upserts: %d (unmatched hotsale records=%d)", len(upserts), unmatched
    )
    return {"upserts": len(upserts), "unmatched": unmatched}


async def sync_store_metrics(pool: asyncpg.Pool, batch_size: int) -> dict[str, int]:
    rows = await pool.fetch(
        """SELECT record_key, payload, synced_at
            FROM qnh_dataset_records WHERE dataset = 'store_rank'"""
    )
    if not rows:
        logging.warning("No store_rank dataset rows found")
        return {"upserts": 0}

    upserts: list[tuple[Any, ...]] = []
    for record in rows:
        payload = record["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            continue

        store_name = parse_str(payload.get("poi_name")) or parse_str(payload.get("store_name"))
        # Try to extract a proper store ID; fallback to a hash of store_name or rank
        store_id = (
            parse_str(payload.get("poi_id"))
            or parse_str(payload.get("poiId"))
            or parse_str(payload.get("store_id"))
            or parse_str(payload.get("poiCode"))
            or parse_str(payload.get("storeId"))
        )
        if not store_id:
            # Generate stable short ID from store name or rank
            rank_val = parse_str(payload.get("rank")) or "0"
            store_id = f"store_{abs(hash(store_name or rank_val)) % 1_000_000:06d}"
        # Truncate to fit varchar(32)
        store_id = store_id[:32]
        if not store_id:
            continue

        metric_date = (record["synced_at"] or datetime.now(UTC)).date()
        channel = parse_str(payload.get("channel")) or ""

        upserts.append(
            (
                "1011766",
                metric_date,
                channel,
                str(store_id),
                parse_number(payload.get("sale_amt_gmv")),
                int(round(parse_number(payload.get("eff_ord_cnt")))),
                parse_number(payload.get("unit_price"))
                or parse_number(payload.get("actual_unit_price")),
                parse_number(payload.get("net_profit")),
                parse_number(payload.get("ord_net_profit_online")),
                parse_number(payload.get("actual_pay_amt")),
                parse_number(payload.get("actual_unit_price")),
                parse_number(payload.get("prod_sale_amt")),
                parse_number(payload.get("package_fee")),
                parse_number(payload.get("delivery_fee")),
                int(round(parse_number(payload.get("user_cnt")))),
                parse_number(payload.get("txn_sku_rate")),
                parse_number(payload.get("overtime_ord_rate")),
                parse_number(payload.get("stockout_refund_rate")),
                parse_number(payload.get("turnover_days_by_quantity"))
                or parse_number(payload.get("turnover_days_by_amount")),
                parse_number(payload.get("stockout_loss_amt")),
                json.dumps(None),
                json.dumps(
                    {
                        "store_name": store_name,
                        "rank": int(round(parse_number(payload.get("rank")))),
                    }
                ),
                record["synced_at"].replace(tzinfo=None)
                if hasattr(record["synced_at"], "replace") and record["synced_at"]
                else datetime.now(),
            )
        )

    sql = """
        INSERT INTO qnh_daily_metrics (
            tenant_id, metric_date, channel, store_id,
            valid_order_amount, valid_order_count, avg_order_value,
            net_profit, online_gross_profit, paid_amount, paid_avg_order_value,
            product_sales_amount, packaging_fee, delivery_fee, customer_count,
            product_sell_through_rate, overtime_rate, stockout_refund_rate,
            turnover_days, stockout_loss, channel_distribution, extra, synced_at
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
            $12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23
        )
        ON CONFLICT (metric_date, channel, store_id) DO UPDATE SET
            valid_order_amount = EXCLUDED.valid_order_amount,
            valid_order_count = EXCLUDED.valid_order_count,
            avg_order_value = EXCLUDED.avg_order_value,
            net_profit = EXCLUDED.net_profit,
            online_gross_profit = EXCLUDED.online_gross_profit,
            paid_amount = EXCLUDED.paid_amount,
            paid_avg_order_value = EXCLUDED.paid_avg_order_value,
            product_sales_amount = EXCLUDED.product_sales_amount,
            packaging_fee = EXCLUDED.packaging_fee,
            delivery_fee = EXCLUDED.delivery_fee,
            customer_count = EXCLUDED.customer_count,
            product_sell_through_rate = EXCLUDED.product_sell_through_rate,
            overtime_rate = EXCLUDED.overtime_rate,
            stockout_refund_rate = EXCLUDED.stockout_refund_rate,
            turnover_days = EXCLUDED.turnover_days,
            stockout_loss = EXCLUDED.stockout_loss,
            channel_distribution = EXCLUDED.channel_distribution,
            extra = EXCLUDED.extra,
            synced_at = EXCLUDED.synced_at
    """

    async with pool.acquire() as conn:
        await executemany(conn, sql, upserts, batch_size)

    logging.info("Store metrics upserts: %d", len(upserts))
    return {"upserts": len(upserts)}


async def generate_alerts(pool: asyncpg.Pool, batch_size: int) -> dict[str, int]:
    # Low stock alerts
    # stock_num may not exist on all deployments; fall back gracefully
    try:
        product_rows = await pool.fetch(
            """SELECT spu_id, name, COALESCE(stock_num, stock, 0) AS stock,
                       COALESCE(safety_stock, 15) AS safety_stock
                   FROM qnh_products WHERE status = '在售'"""
        )
    except asyncpg.exceptions.UndefinedColumnError:
        product_rows = await pool.fetch(
            """SELECT spu_id, name, COALESCE(stock, 0) AS stock,
                       15 AS safety_stock
                   FROM qnh_products WHERE status = '在售'"""
        )
    low_stock_alerts: list[tuple[Any, ...]] = []
    for row in product_rows[:200]:  # cap to avoid flooding UI
        stock = int(row["stock"] or 0)
        safety_stock = max(int(row["safety_stock"] or 0), 10)
        if stock >= safety_stock:
            continue
        severity = "critical" if stock <= max(3, int(0.3 * safety_stock)) else "warning"
        gap = safety_stock - stock
        low_stock_alerts.append(
            (
                f"low_stock:{row['spu_id']}",
                row["spu_id"],
                "low_stock",
                severity,
                "etl_qnh_to_business",
                json.dumps(
                    {
                        "current_stock": stock,
                        "safety_stock": safety_stock,
                        "product_name": row["name"],
                    }
                ),
                "库存低于安全线",
                f"建议立即补货至少 {gap} 件",
            )
        )

    alert_sql = """
        INSERT INTO alerts (alert_id, product_id, alert_type, severity,
                            detection_method, metrics, root_cause, recommended_action)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (alert_id) DO UPDATE SET
            severity = EXCLUDED.severity,
            detection_method = EXCLUDED.detection_method,
            metrics = EXCLUDED.metrics,
            root_cause = EXCLUDED.root_cause,
            recommended_action = EXCLUDED.recommended_action,
            product_id = EXCLUDED.product_id
    """

    async with pool.acquire() as conn:
        if low_stock_alerts:
            await executemany(conn, alert_sql, low_stock_alerts, batch_size)

    # Store level alerts from metrics table
    store_alerts: list[tuple[Any, ...]] = []
    metric_rows = await pool.fetch(
        """SELECT store_id, metric_date, overtime_rate, stockout_loss
            FROM qnh_daily_metrics WHERE metric_date >= CURRENT_DATE - INTERVAL '7 days'"""
    )
    for row in metric_rows:
        overtime = float(row["overtime_rate"] or 0)
        if overtime >= 10:
            store_alerts.append(
                (
                    f"overtime:{row['store_id']}:{row['metric_date']}",
                    None,
                    "overtime_risk",
                    "warning" if overtime < 20 else "critical",
                    "etl_qnh_to_business",
                    json.dumps({"overtime_rate": overtime, "store_id": row["store_id"]}),
                    "门店超时率偏高",
                    "检查骑手与备货效率，优化履约时长",
                )
            )

        stockout_loss = float(row["stockout_loss"] or 0)
        if stockout_loss >= 100:
            store_alerts.append(
                (
                    f"stockout:{row['store_id']}:{row['metric_date']}",
                    None,
                    "stockout_loss",
                    "warning" if stockout_loss < 300 else "critical",
                    "etl_qnh_to_business",
                    json.dumps({"stockout_loss": stockout_loss, "store_id": row["store_id"]}),
                    "缺货导致销售损失",
                    "补足热销库存并复盘动销",
                )
            )

    async with pool.acquire() as conn:
        if store_alerts:
            await executemany(conn, alert_sql, store_alerts, batch_size)

    logging.info(
        "Alerts generated: %d low-stock, %d store-level",
        len(low_stock_alerts),
        len(store_alerts),
    )
    return {"low_stock": len(low_stock_alerts), "store": len(store_alerts)}


async def snapshot_price_history(pool: asyncpg.Pool) -> int:
    sql = """
        WITH inserted AS (
            INSERT INTO price_history (product_id, old_price, new_price, reason, changed_at)
            SELECT p.product_id, COALESCE(p.retail_price, 0), COALESCE(p.retail_price, 0),
                   'baseline_snapshot', NOW()
            FROM products p
            WHERE p.retail_price IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1 FROM price_history ph
                    WHERE ph.product_id = p.product_id AND ph.reason = 'baseline_snapshot'
              )
            RETURNING 1
        )
        SELECT COUNT(*) FROM inserted
    """
    count = await pool.fetchval(sql)
    logging.info("Price history baseline rows inserted: %d", count)
    return int(count or 0)


async def main() -> dict[str, Any]:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.database_url:
        raise SystemExit("--database-url is required or set DATABASE_URL env")

    pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=4)
    try:
        product_stats = await sync_products(pool, args.batch_size)
        product_index = await build_product_index(pool)
        sales_stats = await sync_sales_history(pool, product_index, args.batch_size)
        metrics_stats = await sync_store_metrics(pool, args.batch_size)
        alert_stats = await generate_alerts(pool, args.batch_size)
        price_count = await snapshot_price_history(pool)

        summary = {
            "products": product_stats,
            "sales_history": sales_stats,
            "qnh_daily_metrics": metrics_stats,
            "alerts": alert_stats,
            "price_history": price_count,
        }
        logging.info("ETL completed: %s", summary)
        return summary
    finally:
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
