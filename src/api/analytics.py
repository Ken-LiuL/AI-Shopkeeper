"""Analytics API — 客服统计和转化追踪。"""

from __future__ import annotations

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
    total_revenue = 0
    try:
        total_orders = await pool.fetchval("SELECT COUNT(*) FROM qnh_orders") or 0
        total_revenue = float(
            await pool.fetchval("SELECT COALESCE(SUM(total_amount), 0) FROM qnh_orders") or 0
        )
    except Exception:
        pass
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
