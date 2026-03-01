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
