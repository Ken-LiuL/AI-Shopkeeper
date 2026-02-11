"""Product data model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELISTED = "delisted"


class Product(BaseModel):
    """Core product entity."""

    product_id: str = Field(..., max_length=32)
    name: str = Field(..., max_length=200)
    barcode: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    brand: str | None = Field(None, max_length=100)
    description: str | None = None
    cost_price: Decimal | None = Field(None, ge=0)
    retail_price: Decimal | None = Field(None, ge=0)
    stock: int = Field(0, ge=0)
    monthly_sales: int = Field(0, ge=0)
    status: ProductStatus = ProductStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def gross_margin(self) -> float | None:
        """Calculate gross margin percentage."""
        if self.retail_price and self.cost_price and self.retail_price > 0:
            return float((self.retail_price - self.cost_price) / self.retail_price)
        return None

    @property
    def turnover_days(self) -> float | None:
        """Estimate stock turnover in days."""
        if self.monthly_sales and self.monthly_sales > 0:
            return float(self.stock / self.monthly_sales * 30)
        return None
