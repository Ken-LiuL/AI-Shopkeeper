"""Selection recommendation data model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    """Six-dimension scoring breakdown."""

    market_heat: float = Field(0, ge=0, le=100)
    competition_gap: float = Field(0, ge=0, le=100)
    supply_chain: float = Field(0, ge=0, le=100)
    profit_margin: float = Field(0, ge=0, le=100)
    category_synergy: float = Field(0, ge=0, le=100)
    seasonal_fit: float = Field(0, ge=0, le=100)


class Recommendation(BaseModel):
    """A single selection recommendation produced by the Scorer."""

    rank: int = Field(..., ge=1)
    keyword: str
    final_score: float = Field(..., ge=0, le=100)
    score_breakdown: ScoreBreakdown
    recommendation_reason: str
    key_strengths: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    purchase_channel: str | None = None  # "alibaba" | "pdd"
    purchase_url: str | None = None
    suggested_quantity: int | None = None
    suggested_price: float | None = None
    expected_margin: float | None = None
