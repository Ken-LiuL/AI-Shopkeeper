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

    # Matcher 数据驱动上下文
    category_mapping_candidates: list[dict[str, Any]]
    similar_products: list[dict[str, Any]]
    matched_category: str

    # Filler 结果
    listing_info: dict[str, Any]

    # Filler 输入
    competitor_prices: str
    market_avg_price: float

    # Filler 数据驱动上下文
    template_products: list[dict[str, Any]]
    store_category_hierarchy: list[dict[str, Any]]

    # Compliance 结果
    compliance_check: dict[str, Any]

    # Compliance 数据驱动上下文
    policy_documents_context: list[dict[str, Any]]

    # 元数据
    errors: list[str]
