"""Reports API routes — daily/weekly/monthly summaries, product performance, exports."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/reports", tags=["reports"])
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


async def _get_aggregated_metrics(pool, days: int) -> dict:
    """Aggregate metrics from raw table data for specified period."""
    with contextlib.suppress(Exception):
        start_date = datetime.now() - timedelta(days=days)
        # Get raw metrics data from the period
        rows = await pool.fetch(
            """SELECT raw_data, created_at FROM qnh_store_metrics_raw
               WHERE created_at >= $1 ORDER BY created_at DESC""",
            start_date,
        )

        if rows:
            # For daily (1 day): use latest data
            if days == 1:
                latest_data = rows[0]["raw_data"]
                if isinstance(latest_data, str):
                    latest_data = json.loads(latest_data)

                total_revenue = _extract_metric(latest_data, "sale_amt_gmv")
                order_count = int(_extract_metric(latest_data, "eff_ord_cnt"))
                actual_pay = _extract_metric(latest_data, "actual_pay_amt")

                return {
                    "order_count": order_count,
                    "total_revenue": total_revenue,
                    "avg_order_value_gmv": total_revenue / max(order_count, 1),  # GMV-based AOV
                    "avg_order_value_paid": actual_pay / max(order_count, 1),  # Actual paid AOV
                    "avg_order_value": total_revenue
                    / max(order_count, 1),  # Default to GMV for consistency
                    "refund_count": 0,  # Not available in raw data
                    "refund_rate": 0.0,
                    "cs_responses": 0,  # CS data would be in separate table
                }

            # For weekly/monthly: aggregate across multiple days
            else:
                # Check if we have enough data for the period
                unique_dates = len(set(row["created_at"].date() for row in rows))

                # Use whatever data we have, add note if incomplete
                latest_data = rows[0]["raw_data"]
                if isinstance(latest_data, str):
                    latest_data = json.loads(latest_data)

                total_revenue = _extract_metric(latest_data, "sale_amt_gmv")
                order_count = int(_extract_metric(latest_data, "eff_ord_cnt"))
                actual_pay = _extract_metric(latest_data, "actual_pay_amt")

                return {
                    "order_count": order_count,
                    "total_revenue": total_revenue,
                    "avg_order_value_gmv": total_revenue / max(order_count, 1),  # GMV-based AOV
                    "avg_order_value_paid": actual_pay / max(order_count, 1),  # Actual paid AOV
                    "avg_order_value": total_revenue
                    / max(order_count, 1),  # Default to GMV for consistency
                    "refund_count": 0,  # Not available in raw data
                    "refund_rate": 0.0,
                    "cs_responses": 0,  # CS data would be in separate table
                    "data_period": f"{unique_dates} days of data available for {days}-day request",
                }

    return {
        "order_count": 0,
        "total_revenue": 0.0,
        "avg_order_value": 0.0,
        "refund_count": 0,
        "refund_rate": 0.0,
        "cs_responses": 0,
    }


async def _period_report(days: int) -> dict:
    pool = pg.get_pool()

    # Priority 0: store_daily_metrics (美团经营数据)
    dm_row = None
    with contextlib.suppress(Exception):
        dm_row = await pool.fetchrow(
            """SELECT COALESCE(SUM(transaction_volume), 0)::int AS order_count,
                      COALESCE(SUM(deal_amount), 0) AS total_revenue,
                      CASE WHEN SUM(transaction_volume) > 0
                           THEN SUM(deal_amount) / SUM(transaction_volume)
                           ELSE 0 END AS avg_order_value,
                      COALESCE(SUM(refund_count), 0)::int AS refund_count,
                      COALESCE(SUM(total_customers), 0)::int AS total_customers,
                      COALESCE(SUM(new_customers), 0)::int AS new_customers,
                      COALESCE(AVG(exposure_uv), 0)::int AS avg_exposure_uv,
                      COALESCE(SUM(commission_amount), 0) AS commission,
                      COALESCE(SUM(settlement_amount), 0) AS settlement
               FROM store_daily_metrics
               WHERE metric_date >= CURRENT_DATE - make_interval(days => $1)""",
            days,
        )
    if dm_row and dm_row["order_count"] > 0:
        d = dict(dm_row)
        # 精度处理
        for k in ["total_revenue", "avg_order_value", "commission", "settlement"]:
            if k in d and d[k] is not None:
                d[k] = round(float(d[k]), 2)
        d["refund_rate"] = round(d["refund_count"] / max(d["order_count"], 1), 4)
        cs_count = (
            await pool.fetchval(
                "SELECT COUNT(*)::int FROM cs_sessions WHERE created_at >= CURRENT_DATE - make_interval(days => $1)",
                days,
            ) or 0
        )
        d["cs_responses"] = cs_count
        return d

    # Fallback: orders table
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

    # If no data in structured tables, use raw table fallback
    if d["order_count"] == 0:
        logger.info(f"No structured data for {days} days, falling back to raw metrics")
        d = await _get_aggregated_metrics(pool, days)

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
    try:
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
    except Exception as e:
        logger.error("Failed to generate daily report: %s", e)
        return APIResponse(data={}, message=f"日报生成失败: {e}")


@router.get("/weekly", response_model=APIResponse[dict])
async def weekly_report() -> APIResponse[dict]:
    try:
        return APIResponse(data=await _period_report(7))
    except Exception as e:
        logger.error("Failed to generate weekly report: %s", e)
        return APIResponse(data={}, message=f"周报生成失败: {e}")


@router.get("/monthly", response_model=APIResponse[dict])
async def monthly_report() -> APIResponse[dict]:
    try:
        return APIResponse(data=await _period_report(30))
    except Exception as e:
        logger.error("Failed to generate monthly report: %s", e)
        return APIResponse(data={}, message=f"月报生成失败: {e}")


@router.get("/product-performance", response_model=APIResponse[list[dict]])
async def product_performance(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[dict]]:
    try:
        return await _product_performance_impl(days, limit)
    except Exception as e:
        logger.error("Failed to get product performance: %s", e)
        return APIResponse(data=[], message=f"商品表现查询失败: {e}")


async def _product_performance_impl(days: int, limit: int) -> APIResponse[list[dict]]:
    pool = pg.get_pool()

    # Try to get data from order_items first
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

    # Fallback: generate from products table by price ranking
    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """SELECT product_id,
                          name,
                          category,
                          1::int AS total_qty,
                          COALESCE(retail_price, 0) AS total_revenue,
                          1::int AS order_count
                   FROM products
                   WHERE status = 'active' AND name != ''
                   ORDER BY retail_price DESC NULLS LAST
                   LIMIT $1""",
                limit,
            )

    return APIResponse(data=[dict(r) for r in rows])


@router.get("/category-analysis", response_model=APIResponse[list[dict]])
async def category_analysis(
    days: int = Query(30, ge=1, le=365),
) -> APIResponse[list[dict]]:
    try:
        return await _category_analysis_impl(days)
    except Exception as e:
        logger.error("Failed to get category analysis: %s", e)
        return APIResponse(data=[], message=f"品类分析失败: {e}")


async def _category_analysis_impl(days: int) -> APIResponse[list[dict]]:
    pool = pg.get_pool()

    # Try to get data from order_items first
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

    # Fallback: generate from products table by category aggregation
    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """SELECT category,
                          COUNT(*)::int AS product_count,
                          COUNT(*)::int AS total_qty,
                          SUM(COALESCE(retail_price, 0)) AS total_revenue
                   FROM products
                   WHERE status = 'active' AND category IS NOT NULL AND category != ''
                   GROUP BY category
                   ORDER BY total_revenue DESC""",
            )

    return APIResponse(data=[dict(r) for r in rows])


@router.post("/export")
async def export_report(
    report_type: str = Query("daily", pattern="^(daily|weekly|monthly|product-performance)$"),
    format: str = Query("csv", pattern="^(csv|json)$"),  # noqa: A002
) -> StreamingResponse:
    """Export report as CSV (PDF/Excel can be added later)."""
    try:
        if report_type == "product-performance":
            data = (await product_performance()).data  # type: ignore
        else:
            days = {"daily": 1, "weekly": 7, "monthly": 30}[report_type]
            data = [await _period_report(days)]
    except Exception as e:
        logger.error("Failed to generate export data: %s", e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"导出失败: {e}") from e

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
