"""Alert Agent 状态定义"""

from __future__ import annotations

from typing import Any, TypedDict


class AlertState(TypedDict, total=False):
    """Alert Agent LangGraph 状态"""

    # 输入
    products_data: str
    current_time: str

    # 数据库连接池（由 API 层注入）
    db_pool: Any

    # Prophet 检测原始结果
    prophet_results: str

    # 规则检测原始结果
    rule_check_results: str

    # Anomaly 检测输出
    anomalies: dict[str, Any]

    # 逐个异常的归因和行动（列表）
    root_causes: list[dict[str, Any]]
    actions: list[dict[str, Any]]

    # 每条异常处理的当前索引
    current_anomaly_index: int

    # 元数据
    errors: list[str]
