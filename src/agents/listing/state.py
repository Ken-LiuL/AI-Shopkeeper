"""Listing Agent 状态定义"""

from __future__ import annotations

from typing import Any, TypedDict


class ListingState(TypedDict, total=False):
    """Listing Agent LangGraph 状态"""

    # 输入
    source_url: str
    source_platform: str  # "alibaba" | "pdd"
    raw_product_data: str

    # Parser 结果
    parsed_product: dict[str, Any]

    # Matcher 结果
    matched_standard: dict[str, Any] | None
    match_confidence: float

    # Matcher 输入（美团标品库候选）
    meituan_candidates: str

    # Filler 结果
    listing_info: dict[str, Any]

    # Filler 输入
    competitor_prices: str
    market_avg_price: float

    # Compliance 结果
    compliance_check: dict[str, Any]

    # 元数据
    errors: list[str]
