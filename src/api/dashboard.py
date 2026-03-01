"""Dashboard API routes — reads from both structured and raw sync tables."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse, DashboardOverview, SalesTrendPoint, TopProduct

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


@router.get("/overview", response_model=APIResponse[DashboardOverview])
async def overview() -> APIResponse[DashboardOverview]:
    pool = pg.get_pool()
    total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0

    # Try structured orders table first, fallback to raw metrics
    today_orders = 0
    with contextlib.suppress(Exception):
        today_orders = (
            await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE")
            or 0
        )

    # If no structured orders, try extracting from raw metrics
    if today_orders == 0:
        with contextlib.suppress(Exception):
            # qnh_store_metrics_raw contains store-level KPIs from goldengateway
            row = await pool.fetchval("""
                SELECT COALESCE(
                    SUM((raw_data->>'orderCount')::int),
                    SUM((raw_data->>'payOrderCount')::int),
                    SUM((raw_data->>'completedOrderCount')::int),
                    0
                )
                FROM qnh_store_metrics_raw
                WHERE created_at::date = CURRENT_DATE
            """)
            today_orders = row or 0

    # Also try raw orders
    if today_orders == 0:
        with contextlib.suppress(Exception):
            today_orders = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM qnh_orders_raw WHERE created_at::date = CURRENT_DATE"
                )
                or 0
            )

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

    # Fallback: extract from raw traffic/metrics data
    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT created_at::date AS date,
                       COUNT(*)::int AS quantity,
                       COALESCE(SUM((raw_data->>'revenue')::numeric), 0) AS revenue
                FROM qnh_store_metrics_raw
                WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY created_at::date
                ORDER BY date
            """)

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

    # Try structured table first
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

    # Fallback: use qnh_products with any available sales data
    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT spu_id AS product_id, name,
                       COALESCE(retail_price, 0)::numeric AS revenue,
                       1 AS total_sales
                FROM qnh_products
                WHERE status = '在售' AND name != ''
                ORDER BY synced_at DESC
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
