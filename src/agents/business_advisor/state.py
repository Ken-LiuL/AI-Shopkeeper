"""Business Advisor Agent 状态定义"""

from __future__ import annotations

from typing import Any, TypedDict


class BusinessAdvisorState(TypedDict, total=False):
    """Business Advisor Agent LangGraph 状态"""

    session_id: str
    message: str
    conversation_history: list[dict[str, Any]]
    images: list[str]

    # 数据库连接池（由调用方注入）
    db_pool: Any

    # 输出
    result: dict[str, Any]
    reply: str
    intent: str
    sources: list[dict[str, Any]]
    needs_human: bool

    errors: list[str]
