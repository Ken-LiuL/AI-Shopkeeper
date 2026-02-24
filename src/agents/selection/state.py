"""Selection Agent 状态定义"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _merge_lists(a: list, b: list) -> list:
    """合并两个列表（用于并行节点写入同一 key）"""
    return a + b


class SelectionState(TypedDict, total=False):
    """Selection Agent LangGraph 状态"""

    # 输入参数
    store_id: str
    categories: list[str]
    trigger_type: str  # scheduled / manual / event

    # Phase 1 并行采集的原始数据
    raw_keywords_data: str
    raw_products_data: str
    raw_competitor_stores: str
    raw_competitor_products: str
    raw_stockouts: str
    raw_our_products: str
    raw_sales_data: str
    raw_upcoming_events: str
    raw_weather_forecast: str
    raw_trending_events: str

    # Phase 1 各 Sub-Agent 的分析结果
    market_analysis: dict[str, Any]
    competitor_analysis: dict[str, Any]
    inventory_analysis: dict[str, Any]
    seasonal_factors: dict[str, Any]

    # Phase 2 缺品机会
    gap_opportunities: dict[str, Any]

    # Phase 3 供应链评估（列表，每个 keyword 一条）
    supplier_evaluations: list[dict[str, Any]]

    # Phase 3 原始搜索数据
    raw_alibaba_results: dict[str, str]  # keyword -> results json
    raw_pdd_results: dict[str, str]  # keyword -> results json

    # Phase 4 最终推荐
    recommendations: dict[str, Any]

    # 元数据 — errors 使用 Annotated 合并，因为并行节点可能同时写入
    errors: Annotated[list[str], _merge_lists]
    current_date: str
    current_season: str
