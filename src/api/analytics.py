"""Analytics API — 客服统计和转化追踪。"""

from __future__ import annotations

import contextlib
import logging
from datetime import date

from fastapi import APIRouter, Query

from src.db import postgres as pg
from src.services.cs_analytics import CSAnalyticsService

from .schemas import APIResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)


@router.get("/overview", response_model=APIResponse[dict])
async def get_overview() -> APIResponse:
    """返回店铺基本统计概览。"""
    pool = pg.get_pool()
    total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
    active_products = (
        await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE status = '在售'") or 0
    )
    total_orders = 0
    total_revenue = 0.0
    try:
        total_orders = await pool.fetchval("SELECT COUNT(*) FROM qnh_orders") or 0
        total_revenue = float(
            await pool.fetchval("SELECT COALESCE(SUM(total_amount), 0) FROM qnh_orders") or 0
        )
    except Exception:
        pass
    # Fallback: raw metrics with complex JSON structure
    if total_orders == 0:
        try:
            # Try to extract from complex JSON structure
            row = await pool.fetchrow("""
                SELECT raw_data FROM qnh_store_metrics_raw
                ORDER BY created_at DESC LIMIT 1
            """)
            if row and row["raw_data"]:
                data = row["raw_data"]
                if isinstance(data, str):
                    import json

                    data = json.loads(data)
                if isinstance(data, dict):
                    # Extract from current values or fallback to lastPeriodValue
                    eff_ord_cnt = data.get("eff_ord_cnt", {})
                    if eff_ord_cnt and isinstance(eff_ord_cnt, dict):
                        current_val = eff_ord_cnt.get("indicValue", {}).get("originValue", 0)
                        if current_val == 0:
                            # Use reference data as fallback
                            ref_val = (
                                eff_ord_cnt.get("reference", {})
                                .get("lastPeriodValue", {})
                                .get("originValue", 0)
                            )
                            total_orders = int(ref_val) if ref_val else 0
                        else:
                            total_orders = int(current_val)

                    # Extract revenue from sale_amt_gmv or actual_pay_amt
                    sale_amt = data.get("sale_amt_gmv", {})
                    if sale_amt and isinstance(sale_amt, dict):
                        current_val = sale_amt.get("indicValue", {}).get("originValue", 0)
                        if current_val == 0:
                            ref_val = (
                                sale_amt.get("reference", {})
                                .get("lastPeriodValue", {})
                                .get("originValue", 0)
                            )
                            total_revenue = float(ref_val) if ref_val else 0
                        else:
                            total_revenue = float(current_val)
        except Exception as e:
            logger.warning("Failed to parse complex raw metrics: %s", e)
    # Fallback: raw orders
    if total_orders == 0:
        with contextlib.suppress(Exception):
            total_orders = await pool.fetchval("SELECT COUNT(*) FROM qnh_orders_raw") or 0
    return APIResponse(
        data={
            "total_products": total_products,
            "active_products": active_products,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
        }
    )


@router.get("/customer-service", response_model=APIResponse[dict])
async def get_cs_stats(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
) -> APIResponse:
    svc = CSAnalyticsService()
    stats = await svc.get_cs_stats(start_date, end_date)
    return APIResponse(
        data={
            "total_inquiries": stats.total_inquiries,
            "ai_handled": stats.ai_handled,
            "human_transfer": stats.human_transfer,
            "avg_response_ms": stats.avg_response_ms,
            "ai_ratio": stats.ai_ratio,
            "intent_distribution": stats.intent_distribution,
            "satisfaction_score": stats.satisfaction_score,
        }
    )


@router.get("/trends", response_model=APIResponse[list[dict]])
async def get_trends(days: int = Query(7, ge=1, le=90)) -> APIResponse:
    """Sales and order trends over time."""
    import contextlib

    from src.db import postgres as pg

    pool = pg.get_pool()
    results: list[dict] = []

    # Try raw metrics grouped by date
    with contextlib.suppress(Exception):
        from .dashboard import _extract_metric

        rows = await pool.fetch(
            """SELECT DISTINCT ON (created_at::date)
                      created_at::date AS date, raw_data
               FROM qnh_store_metrics_raw
               WHERE created_at >= CURRENT_DATE - make_interval(days => $1)
               ORDER BY created_at::date DESC, created_at DESC""",
            days,
        )
        for row in rows:
            import json as _json

            data = row["raw_data"]
            if isinstance(data, str):
                data = _json.loads(data)
            results.append(
                {
                    "date": str(row["date"]),
                    "orders": int(_extract_metric(data, "eff_ord_cnt")),
                    "revenue": _extract_metric(data, "sale_amt_gmv"),
                    "customers": int(_extract_metric(data, "user_cnt")),
                    "avg_order_value": _extract_metric(data, "unit_price"),
                }
            )

    if not results:
        results = [
            {
                "date": str(__import__("datetime").date.today()),
                "orders": 0,
                "revenue": 0,
                "customers": 0,
                "avg_order_value": 0,
            }
        ]

    return APIResponse(data=results)


@router.get("/conversion", response_model=APIResponse[list])
async def get_conversion(days: int = Query(7, ge=1, le=90)) -> APIResponse:
    svc = CSAnalyticsService()
    records = await svc.get_conversion_tracking(days)
    return APIResponse(
        data=[
            {
                "session_id": r.session_id,
                "product_id": r.product_id,
                "product_name": r.product_name,
                "recommended_at": r.recommended_at,
                "purchased": r.purchased,
                "order_id": r.order_id,
            }
            for r in records
        ]
    )


@router.get("/sales-trend", response_model=APIResponse[list[dict]])
async def sales_trend(days: int = Query(30, ge=1, le=90)) -> APIResponse:
    """Sales trend analysis, reusing dashboard logic."""
    import contextlib

    from .dashboard import _extract_metric

    pool = pg.get_pool()
    results = []

    # Try structured sales_history first
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
               FROM sales_history
               WHERE sale_date >= CURRENT_DATE - INTERVAL '%s days'
               GROUP BY sale_date ORDER BY sale_date""",
            days,
        )
        if rows:
            results = [
                {
                    "date": str(r["date"]),
                    "quantity": r["quantity"],
                    "revenue": float(r["revenue"]),
                }
                for r in rows
            ]

    # Fallback: aggregate from raw metrics per day
    if not results:
        with contextlib.suppress(Exception):
            raw_rows = await pool.fetch(
                """SELECT DISTINCT ON (created_at::date)
                          created_at::date AS date, raw_data
                   FROM qnh_store_metrics_raw
                   WHERE created_at >= CURRENT_DATE - make_interval(days => $1)
                   ORDER BY created_at::date, created_at DESC""",
                days,
            )
            for r in raw_rows:
                import json

                d = str(r["date"])
                data = r["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                orders = int(_extract_metric(data, "eff_ord_cnt"))
                revenue = _extract_metric(data, "sale_amt_gmv")
                results.append({"date": d, "quantity": orders, "revenue": revenue})
            results = sorted(results, key=lambda x: x["date"])

    return APIResponse(data=results)


@router.get("/product-performance", response_model=APIResponse[list[dict]])
async def product_performance() -> APIResponse:
    """Product performance analysis from qnh_products."""
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT spu_id AS product_id, name, category, retail_price, channel_price, status
           FROM qnh_products
           WHERE name != '' AND retail_price IS NOT NULL
           ORDER BY retail_price DESC
           LIMIT 50"""
    )

    return APIResponse(
        data=[
            {
                "product_id": str(r["product_id"]),
                "name": r["name"],
                "category": r["category"],
                "retail_price": float(r["retail_price"]) if r["retail_price"] else 0.0,
                "channel_price": float(r["channel_price"]) if r["channel_price"] else 0.0,
                "status": r["status"],
                "performance_score": float(r["retail_price"])
                if r["retail_price"]
                else 0.0,  # Use price as proxy
            }
            for r in rows
        ]
    )


@router.get("/category-analysis", response_model=APIResponse[list[dict]])
async def category_analysis() -> APIResponse:
    """Category analysis aggregated from qnh_products."""
    pool = pg.get_pool()
    rows = await pool.fetch(
        """SELECT category,
                  COUNT(*)::int AS product_count,
                  AVG(retail_price) AS avg_price,
                  MIN(retail_price) AS min_price,
                  MAX(retail_price) AS max_price,
                  COUNT(CASE WHEN status = '在售' THEN 1 END)::int AS active_products
           FROM qnh_products
           WHERE category IS NOT NULL AND category != '' AND retail_price IS NOT NULL
           GROUP BY category
           ORDER BY product_count DESC"""
    )

    return APIResponse(
        data=[
            {
                "category": r["category"],
                "product_count": r["product_count"],
                "active_products": r["active_products"],
                "avg_price": float(r["avg_price"]) if r["avg_price"] else 0.0,
                "min_price": float(r["min_price"]) if r["min_price"] else 0.0,
                "max_price": float(r["max_price"]) if r["max_price"] else 0.0,
                "price_range": f"¥{float(r['min_price']) if r['min_price'] else 0:.1f} - ¥{float(r['max_price']) if r['max_price'] else 0:.1f}",
            }
            for r in rows
        ]
    )
