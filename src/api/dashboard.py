"""Dashboard API routes — reads from both structured and raw sync tables."""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse, DashboardOverview, SalesTrendPoint, TopProduct

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


def _extract_metric(raw_data: dict, key: str, use_reference: bool = True) -> float:
    """Extract metric value from complex goldengateway JSON.

    Structure: {key: {indicValue: {originValue: X}, reference: {lastPeriodValue: {originValue: Y}}}}
    If current value is 0 and use_reference=True, fall back to lastPeriodValue.
    """
    field = raw_data.get(key, {})
    if not isinstance(field, dict):
        # Simple flat value
        try:
            return float(field)
        except (TypeError, ValueError):
            return 0.0

    current = 0.0
    indic = field.get("indicValue", {})
    if isinstance(indic, dict):
        current = float(indic.get("originValue", 0) or 0)

    if current == 0 and use_reference:
        ref = field.get("reference", {})
        if isinstance(ref, dict):
            lp = ref.get("lastPeriodValue", {})
            if isinstance(lp, dict):
                current = float(lp.get("originValue", 0) or 0)

    return current


async def _get_latest_metrics(pool) -> dict:
    """Get the latest raw metrics record and parse it."""
    with contextlib.suppress(Exception):
        row = await pool.fetchrow(
            "SELECT raw_data FROM qnh_store_metrics_raw ORDER BY created_at DESC LIMIT 1"
        )
        if row and row["raw_data"]:
            data = row["raw_data"]
            if isinstance(data, str):
                data = json.loads(data)
            return data
    return {}


@router.get("/overview", response_model=APIResponse[DashboardOverview])
async def overview() -> APIResponse[DashboardOverview]:
    pool = pg.get_pool()
    total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0

    today_orders = 0
    with contextlib.suppress(Exception):
        today_orders = (
            await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE")
            or 0
        )

    # Fallback: extract from raw metrics
    if today_orders == 0:
        metrics = await _get_latest_metrics(pool)
        if metrics:
            today_orders = int(_extract_metric(metrics, "eff_ord_cnt"))

    pending_alerts = 0
    with contextlib.suppress(Exception):
        pending_alerts = (
            await pool.fetchval("SELECT COUNT(*) FROM alerts WHERE status = 'pending'") or 0
        )

    pending_tasks = 0
    for q in [
        "SELECT COUNT(*) FROM selection_runs WHERE status = 'running'",
        "SELECT COUNT(*) FROM bundle_tasks WHERE status = 'running'",
        "SELECT COUNT(*) FROM listings WHERE status = 'processing'",
    ]:
        with contextlib.suppress(Exception):
            pending_tasks += await pool.fetchval(q) or 0

    return APIResponse(
        data=DashboardOverview(
            total_products=total_products,
            today_orders=today_orders,
            pending_alerts=pending_alerts,
            pending_tasks=pending_tasks,
        )
    )


@router.get("/sales-trend", response_model=APIResponse[list[SalesTrendPoint]])
async def sales_trend() -> APIResponse[list[SalesTrendPoint]]:
    pool = pg.get_pool()

    # Try structured sales_history first
    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
               FROM sales_history
               WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY sale_date ORDER BY sale_date"""
        )

    # Fallback: aggregate from raw metrics per day
    if not rows:
        with contextlib.suppress(Exception):
            raw_rows = await pool.fetch("""
                SELECT created_at::date AS date, raw_data
                FROM qnh_store_metrics_raw
                WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY created_at::date
            """)
            # Group by date and extract metrics
            daily: dict = {}
            for r in raw_rows:
                d = str(r["date"])
                data = r["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                orders = _extract_metric(data, "eff_ord_cnt")
                revenue = _extract_metric(data, "sale_amt_gmv")
                if d not in daily:
                    daily[d] = {"quantity": 0, "revenue": 0.0}
                daily[d]["quantity"] += int(orders)
                daily[d]["revenue"] += revenue
            rows = [
                {"date": d, "quantity": v["quantity"], "revenue": v["revenue"]}
                for d, v in sorted(daily.items())
            ]

    return APIResponse(
        data=[
            SalesTrendPoint(
                date=str(r["date"]),
                quantity=r["quantity"],
                revenue=float(r["revenue"]),
            )
            for r in rows
        ]
    )


@router.get("/top-products", response_model=APIResponse[list[TopProduct]])
async def top_products() -> APIResponse[list[TopProduct]]:
    pool = pg.get_pool()

    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT ps.product_id, p.name, SUM(ps.quantity)::int AS total_sales,
                      SUM(ps.revenue) AS revenue
               FROM sales_history ps JOIN products p ON ps.product_id = p.product_id
               WHERE ps.sale_date >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY ps.product_id, p.name
               ORDER BY total_sales DESC LIMIT 10"""
        )

    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT spu_id AS product_id, name,
                       COALESCE(retail_price, 0)::numeric AS revenue,
                       1 AS total_sales
                FROM qnh_products
                WHERE status = '在售' AND name != '' AND retail_price IS NOT NULL
                ORDER BY retail_price DESC
                LIMIT 10
            """)

    return APIResponse(
        data=[
            TopProduct(
                product_id=str(r["product_id"]),
                name=r["name"],
                total_sales=int(r.get("total_sales", 0)),
                revenue=float(r.get("revenue", 0)),
            )
            for r in rows
        ]
    )


@router.get("/store-kpis")
async def store_kpis() -> dict:
    """Return parsed store KPIs from raw metrics."""
    pool = pg.get_pool()
    metrics = await _get_latest_metrics(pool)
    if not metrics:
        return {"error": "no metrics data"}

    kpis = {}
    for key in [
        "eff_ord_cnt",
        "sale_amt_gmv",
        "actual_pay_amt",
        "prod_sale_amt",
        "unit_price",
        "actual_unit_price",
        "net_profit",
        "user_cnt",
        "delivery_fee",
        "package_fee",
        "overtime_ord_rate",
        "stockout_refund_rate",
        "stockout_loss_amt",
    ]:
        val = _extract_metric(metrics, key)
        kpis[key] = val

    return {
        "orders": int(kpis["eff_ord_cnt"]),
        "gmv": kpis["sale_amt_gmv"],
        "actual_revenue": kpis["actual_pay_amt"],
        "product_sales": kpis["prod_sale_amt"],
        "avg_order_value": kpis["unit_price"],
        "actual_avg_order_value": kpis["actual_unit_price"],
        "net_profit": kpis["net_profit"],
        "customers": int(kpis["user_cnt"]),
        "delivery_fee": kpis["delivery_fee"],
        "package_fee": kpis["package_fee"],
        "stockout_loss": kpis["stockout_loss_amt"],
    }


@router.get("/raw-data-debug")
async def raw_data_debug() -> dict:
    """Debug endpoint: show what's in raw tables."""
    pool = pg.get_pool()
    result = {}
    for table in [
        "qnh_store_metrics_raw",
        "qnh_orders_raw",
        "qnh_traffic_raw",
        "qnh_customers_raw",
        "qnh_traffic_channels_raw",
    ]:
        with contextlib.suppress(Exception):
            count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
            sample = await pool.fetchrow(
                f"SELECT raw_data, synced_at FROM {table} ORDER BY id DESC LIMIT 1"
            )
            result[table] = {
                "count": count,
                "latest": dict(sample) if sample else None,
            }
    return result
