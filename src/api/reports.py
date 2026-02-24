"""Reports API routes — daily/weekly/monthly summaries, product performance, exports."""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/reports", tags=["reports"])
logger = logging.getLogger(__name__)


async def _period_report(days: int) -> dict:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        """SELECT COUNT(*)::int AS order_count,
                  COALESCE(SUM(total_amount), 0) AS total_revenue,
                  COALESCE(AVG(total_amount), 0) AS avg_order_value,
                  COUNT(*) FILTER (WHERE status = 'refunded')::int AS refund_count
           FROM orders
           WHERE order_time >= CURRENT_DATE - make_interval(days => $1)""",
        days,
    )
    d = dict(row)
    d["refund_rate"] = round(d["refund_count"] / max(d["order_count"], 1), 4)
    # cs responses
    cs_count = (
        await pool.fetchval(
            """SELECT COUNT(*)::int FROM cs_sessions
           WHERE created_at >= CURRENT_DATE - make_interval(days => $1)""",
            days,
        )
        or 0
    )
    d["cs_responses"] = cs_count
    return d


@router.get("/daily", response_model=APIResponse[dict])
async def daily_report(date: str | None = None) -> APIResponse[dict]:
    """日报 — 支持 ?date=2026-02-12 查询指定日期的智能日报"""
    if date:
        from datetime import date as date_type

        from src.services.daily_report import DailyReportService

        try:
            d = date_type.fromisoformat(date)
            svc = DailyReportService()
            report = await svc.generate_daily_report(d)
            return APIResponse(
                data={
                    "date": report.date,
                    "revenue": report.revenue,
                    "order_count": report.order_count,
                    "avg_order_value": report.avg_order_value,
                    "revenue_vs_yesterday": report.revenue_vs_yesterday,
                    "revenue_vs_last_week": report.revenue_vs_last_week,
                    "order_vs_yesterday": report.order_vs_yesterday,
                    "order_vs_last_week": report.order_vs_last_week,
                    "top_products": report.top_products,
                    "slow_products": report.slow_products,
                    "cs_total": report.cs_total,
                    "cs_ai_ratio": report.cs_ai_ratio,
                    "cs_human_transfer": report.cs_human_transfer,
                    "alerts_triggered": report.alerts_triggered,
                    "alerts_pending": report.alerts_pending,
                    "alerts_resolved": report.alerts_resolved,
                    "todo_items": report.todo_items,
                    "competitor_changes": report.competitor_changes,
                }
            )
        except ValueError:
            pass
    return APIResponse(data=await _period_report(1))


@router.get("/weekly", response_model=APIResponse[dict])
async def weekly_report() -> APIResponse[dict]:
    return APIResponse(data=await _period_report(7))


@router.get("/monthly", response_model=APIResponse[dict])
async def monthly_report() -> APIResponse[dict]:
    return APIResponse(data=await _period_report(30))


@router.get("/product-performance", response_model=APIResponse[list[dict]])
async def product_performance(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT oi.product_id, p.name, p.category,
                  SUM(oi.quantity)::int AS total_qty,
                  SUM(oi.unit_price * oi.quantity) AS total_revenue,
                  COUNT(DISTINCT oi.order_id)::int AS order_count
           FROM order_items oi
           JOIN products p ON oi.product_id = p.product_id
           JOIN orders o ON oi.order_id = o.order_id
           WHERE o.order_time >= CURRENT_DATE - make_interval(days => $1)
           GROUP BY oi.product_id, p.name, p.category
           ORDER BY total_revenue DESC LIMIT $2""",
        days,
        limit,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.get("/category-analysis", response_model=APIResponse[list[dict]])
async def category_analysis(
    days: int = Query(30, ge=1, le=365),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT p.category,
                  COUNT(DISTINCT oi.product_id)::int AS product_count,
                  SUM(oi.quantity)::int AS total_qty,
                  SUM(oi.unit_price * oi.quantity) AS total_revenue
           FROM order_items oi
           JOIN products p ON oi.product_id = p.product_id
           JOIN orders o ON oi.order_id = o.order_id
           WHERE o.order_time >= CURRENT_DATE - make_interval(days => $1)
           GROUP BY p.category ORDER BY total_revenue DESC""",
        days,
    )
    return APIResponse(data=[dict(r) for r in rows])


@router.post("/export")
async def export_report(
    report_type: str = Query("daily", pattern="^(daily|weekly|monthly|product-performance)$"),
    format: str = Query("csv", pattern="^(csv|json)$"),  # noqa: A002
) -> StreamingResponse:
    """Export report as CSV (PDF/Excel can be added later)."""
    if report_type == "product-performance":
        data = (await product_performance()).data  # type: ignore
    else:
        days = {"daily": 1, "weekly": 7, "monthly": 30}[report_type]
        data = [await _period_report(days)]

    if format == "csv" and data:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
        writer.writeheader()
        for row in data:
            writer.writerow({k: str(v) for k, v in row.items()})
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={report_type}_report.csv"},
        )

    import json

    return StreamingResponse(
        io.BytesIO(json.dumps(data, default=str).encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={report_type}_report.json"},
    )
