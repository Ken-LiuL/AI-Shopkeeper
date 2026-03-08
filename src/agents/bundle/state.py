"""Bundle Agent 状态定义"""

from __future__ import annotations

from typing import Any, TypedDict


class BundleState(TypedDict, total=False):
    """Bundle Agent LangGraph 状态"""

    # 输入
    orders_summary: str
    product_details: str
    product_costs: str
    db_pool: Any

    # FP-Growth 配置
    fp_growth_config: str

    # DB 上下文（真实数据）
    db_association_pairs: list[dict[str, Any]]
    db_product_catalog: dict[str, dict[str, Any]]
    db_seasonality: list[dict[str, Any]]

    # OrderMining 结果
    association_rules: dict[str, Any]

    # Scene 结果
    bundle_proposals: dict[str, Any]

    # Pricing 结果（列表，每个套餐一条）
    bundle_pricing: list[dict[str, Any]]

    # 元数据
    errors: list[str]
