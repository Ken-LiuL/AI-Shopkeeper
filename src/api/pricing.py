"""Pricing API — 定价分析和调价管理。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from src.services.pricing import PricingService

from .schemas import APIResponse

router = APIRouter(prefix="/api/pricing", tags=["pricing"])
logger = logging.getLogger(__name__)


@router.get("/suggestions", response_model=APIResponse[list])
async def get_suggestions() -> APIResponse:
    svc = PricingService()
    items = await svc.get_pricing_suggestions()
    return APIResponse(
        data=[
            {
                "product_id": s.product_id,
                "product_name": s.product_name,
                "current_price": s.current_price,
                "suggested_price": s.suggested_price,
                "reason": s.reason,
                "current_margin": s.current_margin,
                "projected_margin": s.projected_margin,
                "competitor_ref": s.competitor_ref,
            }
            for s in items
        ]
    )


@router.get("/analysis/{product_id}", response_model=APIResponse[dict])
async def get_analysis(product_id: str) -> APIResponse:
    svc = PricingService()
    a = await svc.analyze_pricing(product_id)
    return APIResponse(
        data={
            "product_id": a.product_id,
            "product_name": a.product_name,
            "current_price": a.current_price,
            "cost_price": a.cost_price,
            "gross_margin": a.gross_margin,
            "competitor_avg": a.competitor_avg,
            "competitor_min": a.competitor_min,
            "competitor_max": a.competitor_max,
            "competitor_count": a.competitor_count,
            "price_elasticity": a.price_elasticity,
            "recommendation": a.recommendation,
        }
    )


class ApplyPriceRequest(BaseModel):
    changes: list[dict]


@router.post("/apply", response_model=APIResponse[list])
async def apply_prices(req: ApplyPriceRequest) -> APIResponse:
    svc = PricingService()
    results = await svc.apply_price_changes(req.changes)
    return APIResponse(data=results)
