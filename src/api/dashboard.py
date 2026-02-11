"""Dashboard API routes."""

from __future__ import annotations

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse, DashboardOverview, SalesTrendPoint, TopProduct

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=APIResponse[DashboardOverview])
async def overview() -> APIResponse[DashboardOverview]:
    pool = pg.get_pool()
    total_products = await pool.fetchval("SELECT COUNT(*) FROM products WHERE status = 'active'") or 0
    today_orders = await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE") or 0
    pending_alerts = await pool.fetchval("SELECT COUNT(*) FROM alerts WHERE status = 'pending'") or 0
    pending_tasks = await pool.fetchval(
        """SELECT COUNT(*) FROM (
             SELECT 1 FROM selection_runs WHERE status = 'running'
             UNION ALL SELECT 1 FROM bundle_tasks WHERE status = 'running'
             UNION ALL SELECT 1 FROM listings WHERE status = 'processing'
           ) t"""
    ) or 0
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
    rows = await pool.fetch(
        """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
           FROM product_sales
           WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
           GROUP BY sale_date ORDER BY sale_date"""
    )
    return APIResponse(data=[SalesTrendPoint(date=str(r["date"]), quantity=r["quantity"], revenue=r["revenue"]) for r in rows])


@router.get("/top-products", response_model=APIResponse[list[TopProduct]])
async def top_products() -> APIResponse[list[TopProduct]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT ps.product_id, p.name, SUM(ps.quantity)::int AS total_sales, SUM(ps.revenue) AS revenue
           FROM product_sales ps JOIN products p ON ps.product_id = p.product_id
           WHERE ps.sale_date >= CURRENT_DATE - INTERVAL '30 days'
           GROUP BY ps.product_id, p.name
           ORDER BY total_sales DESC LIMIT 10"""
    )
    return APIResponse(
        data=[TopProduct(product_id=r["product_id"], name=r["name"], total_sales=r["total_sales"], revenue=r["revenue"]) for r in rows]
    )
