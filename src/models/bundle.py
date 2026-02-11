"""Bundle data model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BundleItem(BaseModel):
    """A product within a bundle."""

    product_id: str
    name: str
    unit_price: Decimal = Field(..., ge=0)
    role: str | None = None  # e.g. "主品", "配件", "耗材"


class Bundle(BaseModel):
    """Product bundle / combo entity."""

    bundle_id: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    tagline: str | None = Field(None, max_length=100)
    products: list[BundleItem] = Field(default_factory=list)
    original_price: Decimal = Field(..., ge=0)
    bundle_price: Decimal = Field(..., ge=0)
    discount_percent: float = Field(0, ge=0, le=100)
    confidence: float = Field(0, ge=0, le=1)
    lift: float = Field(0, ge=0)
    status: str = "active"
    created_at: datetime | None = None

    @property
    def savings(self) -> Decimal:
        return self.original_price - self.bundle_price
