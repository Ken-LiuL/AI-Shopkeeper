"""Shared Pydantic request/response schemas for the API layer."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Generic wrappers ─────────────────────────────────────────


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str = ""


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    data: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    message: str = ""


class TaskCreatedResponse(BaseModel):
    success: bool = True
    task_id: str
    message: str = "Task started"


# ── Selection ────────────────────────────────────────────────


class SelectionRunRequest(BaseModel):
    keywords: list[str] | None = None
    categories: list[str] | None = None


class SelectionRunSummary(BaseModel):
    run_id: str
    status: str
    keywords: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    result_count: int = 0
    created_at: datetime | None = None


class SelectionRunDetail(SelectionRunSummary):
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    raw_state: dict[str, Any] = Field(default_factory=dict)


# ── Customer Service ─────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    customer_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    message_id: str | None = None
    images: list[str] = Field(default_factory=list, description="Base64 encoded images")
    customer_info: dict[str, Any] = Field(default_factory=dict)
    order_context: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    ai_reply_id: str | None = None
    intent: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    needs_human: bool = False
    error_code: str | None = None
    error_detail: str | None = None
    context_trace: dict[str, Any] = Field(default_factory=dict)


class SessionListItem(BaseModel):
    session_id: str
    customer_id: str | None = None
    last_message: str = ""
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class SessionHistory(BaseModel):
    session_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str | None = None
    ai_reply_id: str | None = None
    rating: str = Field(..., pattern="^(good|bad)$")
    comment: str | None = None
    action: str | None = Field(None, pattern="^(adopted|edited|ignored)$")
    original_reply: str | None = None
    edited_reply: str | None = None
    actual_reply: str | None = None
    correction_text: str | None = None


class LogChatRequest(BaseModel):
    session_id: str = ""
    message_id: str = ""
    role: str = "agent"
    content: str = ""
    timestamp: str = ""


# ── Alerts ───────────────────────────────────────────────────


class AlertUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(acknowledged|resolved|ignored)$")


class AlertScanResponse(BaseModel):
    task_id: str
    message: str = "Alert scan started"


class IssueActionLookupItem(BaseModel):
    issue_type: str = Field(..., min_length=1, max_length=100)
    issue_key: str = Field(..., min_length=1, max_length=500)


class IssueActionLookupRequest(BaseModel):
    issues: list[IssueActionLookupItem] = Field(default_factory=list)


class IssueActionRequest(BaseModel):
    issue_type: str = Field(..., min_length=1, max_length=100)
    issue_key: str = Field(..., min_length=1, max_length=500)
    title: str | None = None
    status: str = Field(..., pattern="^(acknowledged|resolved|ignored)$")
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Bundles ──────────────────────────────────────────────────


class BundleGenerateRequest(BaseModel):
    min_support: float | None = None
    min_confidence: float | None = None
    max_bundles: int | None = None


class BundleUpdateRequest(BaseModel):
    status: str | None = None
    name: str | None = None
    bundle_price: Decimal | None = None


# ── Listing ──────────────────────────────────────────────────


class ListingParseRequest(BaseModel):
    url: str
    platform: str = "alibaba"  # "alibaba" | "pdd"


class ListingCreateRequest(BaseModel):
    source_url: str
    platform: str = "alibaba"
    raw_product_data: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)


class ListingDetail(BaseModel):
    listing_id: str
    status: str
    current_step: str | None = None
    step_detail: str | None = None
    parsed_product: dict[str, Any] | None = None
    matched_standard: dict[str, Any] | None = None
    match_confidence: float | None = None
    listing_info: dict[str, Any] | None = None
    compliance_check: dict[str, Any] | None = None
    errors: list[Any] | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class ListingStatusResponse(BaseModel):
    listing_id: str
    status: str
    current_step: str | None = None
    step_detail: str | None = None
    created_at: datetime | None = None


class BatchListingItem(BaseModel):
    platform: str = "alibaba"
    raw_product_data: str = ""
    source_url: str = ""


class BatchListingRequest(BaseModel):
    items: list[BatchListingItem] = Field(default_factory=list)


class BatchListingResponse(BaseModel):
    success: bool = True
    task_ids: list[str] = Field(default_factory=list)
    message: str = ""


# ── Products ─────────────────────────────────────────────────


class ProductCreateRequest(BaseModel):
    name: str = Field(..., max_length=200)
    barcode: str | None = None
    category: str | None = None
    brand: str | None = None
    description: str | None = None
    cost_price: Decimal | None = Field(None, ge=0)
    retail_price: Decimal | None = Field(None, ge=0)
    stock: int = 0
    status: str = "active"


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    barcode: str | None = None
    category: str | None = None
    brand: str | None = None
    description: str | None = None
    cost_price: Decimal | None = None
    retail_price: Decimal | None = None
    stock: int | None = None
    status: str | None = None


class SalesRecord(BaseModel):
    date: str
    quantity: int
    revenue: Decimal


# ── Dashboard ────────────────────────────────────────────────


class ActionItem(BaseModel):
    priority: str = Field(..., pattern="^(high|medium|low)$")
    action: str
    detail: str
    link: str


class ActionOutcome(BaseModel):
    title: str
    detail: str
    category: str
    link: str
    happened_at: str
    next_check: str = ""


class TopAction(BaseModel):
    type: str = Field(..., pattern="^(low_stock|price_risk|customer_risk|alert_pending)$")
    title: str
    reason: str
    expected_impact_amount: Decimal = Decimal("0")
    action_url: str
    priority: str = Field(..., pattern="^(high|medium|low)$")


class DashboardOverview(BaseModel):
    total_products: int = 0
    today_orders: int = 0
    today_gmv: Decimal = Decimal("0")
    yesterday_orders: int = 0
    yesterday_gmv: Decimal = Decimal("0")
    avg_rating: float = 0.0
    avg_order_value: Decimal = Decimal("0")
    total_customers: int = 0
    conversion_rate: float = 0.0
    pending_alerts: int = 0
    pending_tasks: int = 0
    low_stock_count: int = 0
    recent_sync_state: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    top_actions: list[TopAction] = Field(default_factory=list)
    recent_outcomes: list[ActionOutcome] = Field(default_factory=list)


class SalesTrendPoint(BaseModel):
    date: str
    quantity: int
    revenue: Decimal
    simulated: bool = False
    growth_rate: float | None = None


class TopProduct(BaseModel):
    product_id: str
    name: str
    total_sales: int
    revenue: Decimal
