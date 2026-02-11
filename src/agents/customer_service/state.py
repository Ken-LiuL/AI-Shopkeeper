"""CustomerService Agent 状态定义"""

from __future__ import annotations

from typing import Any, TypedDict


class CustomerServiceState(TypedDict, total=False):
    """CustomerService Agent LangGraph 状态"""

    # 输入
    user_message: str
    conversation_history: list[dict[str, str]]
    session_id: str

    # Intent 识别结果
    intent: dict[str, Any]

    # 路由结果
    route: str  # "faq" | "search" | "human"

    # 检索结果
    search_results: list[dict[str, Any]]
    reranked_results: list[dict[str, Any]]
    enriched_results: list[dict[str, Any]]  # GraphRAG 子图

    # 回复
    reply: dict[str, Any]
    faq_reply: str | None

    # 元数据
    errors: list[str]
