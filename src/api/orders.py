"""Order analysis API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.db import postgres as pg

from .errors import NotFoundError
from .schemas import APIResponse, PaginatedResponse

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("/stats", response_model=APIResponse[dict])
async def order_stats(
    days: int = Query(30, ge=1, le=365),
) -> APIResponse[dict]:
    """Order statistics: total amount, average price, refund rate."""
    pool = pg.get_pool()
    row = await pool.fetchrow(
        """SELECT COUNT(*)::int AS total_orders,
                  COALESCE(SUM(total_amount), 0) AS total_amount,
                  COALESCE(AVG(total_amount), 0) AS avg_amount,
                  COUNT(*) FILTER (WHERE status = 'refunded')::int AS refunded_count
           FROM orders
           WHERE order_time >= CURRENT_DATE - make_interval(days => $1)""",
        days,
    )
    d = dict(row)
    d["refund_rate"] = round(d["refunded_count"] / max(d["total_orders"], 1), 4)
    return APIResponse(data=d)


@router.get("/trend", response_model=APIResponse[list[dict]])
async def order_trend(
    days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
) -> APIResponse[list[dict]]:
    """Order trend grouped by day/week/month."""
    pool = pg.get_pool()
    trunc = {"day": "day", "week": "week", "month": "month"}[granularity]
    rows = await pool.fetch(
        f"""SELECT date_trunc('{trunc}', order_time)::date AS period,
                   COUNT(*)::int AS order_count,
                   COALESCE(SUM(total_amount), 0) AS total_amount
            FROM orders
            WHERE order_time >= CURRENT_DATE - make_interval(days => $1)
            GROUP BY period ORDER BY period""",
        days,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/refunds", response_model=PaginatedResponse[dict])
async def list_refunds(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    total = await pool.fetchval(
        "SELECT COUNT(*) FROM orders WHERE status IN ('refunded', 'refund_pending')"
    )
    offset = (page - 1) * page_size
    rows = await pool.fetch(
        """SELECT * FROM orders WHERE status IN ('refunded', 'refund_pending')
           ORDER BY order_time DESC LIMIT $1 OFFSET $2""",
        page_size, offset,
    )
    return PaginatedResponse(data=[dict(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=APIResponse[dict])
async def get_order(order_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow("SELECT * FROM orders WHERE order_id = $1", order_id)
    if not row:
        raise NotFoundError("Order", order_id)
    data = dict(row)
    items = await pool.fetch(
        "SELECT * FROM order_items WHERE order_id = $1", order_id,
    )
    data["items"] = [dict(i) for i in items]
    return APIResponse(data=data)


@router.get("", response_model=PaginatedResponse[dict])
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
) -> PaginatedResponse[dict]:
    pool = pg.get_pool()
    conditions: list[str] = []
    params: list = []
    idx = 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if start_date:
        conditions.append(f"order_time >= ${idx}::date")
        params.append(start_date)
        idx += 1
    if end_date:
        conditions.append(f"order_time < ${idx}::date + 1")
        params.append(end_date)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    total = await pool.fetchval(f"SELECT COUNT(*) FROM orders{where}", *params)
    offset = (page - 1) * page_size
    rows = await pool.fetch(
        f"SELECT * FROM orders{where} ORDER BY order_time DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params, page_size, offset,
    )
    return PaginatedResponse(data=[dict(r) for r in rows], total=total, page=page, page_size=page_size)
