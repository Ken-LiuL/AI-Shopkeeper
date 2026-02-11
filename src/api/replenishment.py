"""Replenishment API — 补货建议和采购单管理。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.services.replenishment import ReplenishmentService

from .schemas import APIResponse

router = APIRouter(prefix="/api/replenishment", tags=["replenishment"])
logger = logging.getLogger(__name__)


@router.get("/suggestions", response_model=APIResponse[list])
async def get_suggestions() -> APIResponse:
    svc = ReplenishmentService()
    items = await svc.get_replenishment_suggestions()
    return APIResponse(data=[
        {
            "product_id": i.product_id,
            "product_name": i.product_name,
            "current_stock": i.current_stock,
            "safety_stock": i.safety_stock,
            "suggested_qty": i.suggested_qty,
            "cost_price": i.cost_price,
            "estimated_cost": i.estimated_cost,
            "supplier_link": i.supplier_link,
        }
        for i in items
    ])


@router.post("/purchase-order", response_model=APIResponse[dict])
async def create_purchase_order(items: list[dict]) -> APIResponse:
    svc = ReplenishmentService()
    po = await svc.generate_purchase_order(items)
    return APIResponse(data={
        "order_id": po.order_id,
        "items": po.items,
        "total_cost": po.total_cost,
        "status": po.status,
        "created_at": po.created_at,
    })


@router.get("/safety-stock", response_model=APIResponse[list])
async def get_safety_stock() -> APIResponse:
    svc = ReplenishmentService()
    data = await svc.get_safety_stock_list()
    return APIResponse(data=data)
