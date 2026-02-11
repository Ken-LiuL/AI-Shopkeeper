"""Order data models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    """Single line item within an order."""

    id: int | None = None
    order_id: str
    product_id: str
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class Order(BaseModel):
    """Platform order entity."""

    order_id: str = Field(..., max_length=50)
    platform: str = "meituan"
    customer_phone_suffix: str | None = Field(None, max_length=4)
    total_amount: Decimal = Field(..., ge=0)
    status: str | None = None
    order_time: datetime | None = None
    delivery_address_type: str | None = None
    items: list[OrderItem] = Field(default_factory=list)
    created_at: datetime | None = None
