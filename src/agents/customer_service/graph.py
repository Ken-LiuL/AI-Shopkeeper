"""CustomerService Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    faq_reply_node,
    get_route,
    graphrag_node,
    human_transfer_node,
    hybrid_search_node,
    intent_recognition_node,
    reranker_node,
    reply_generation_node,
    route_node,
)
from .state import CustomerServiceState


def build_customer_service_graph() -> StateGraph:
    """
    构建 CustomerService Agent 的 LangGraph 状态机。

    Intent → 路由(FAQ/检索/转人工) → Hybrid Search → Reranker → GraphRAG → Reply
    """
    graph = StateGraph(CustomerServiceState)

    # --- 注册节点 ---
    graph.add_node("intent_recognition", intent_recognition_node)
    graph.add_node("route", route_node)
    graph.add_node("faq_reply", faq_reply_node)
    graph.add_node("hybrid_search", hybrid_search_node)
    graph.add_node("reranker", reranker_node)
    graph.add_node("graphrag", graphrag_node)
    graph.add_node("reply_generation", reply_generation_node)
    graph.add_node("human_transfer", human_transfer_node)

    # --- 定义边 ---

    # 入口 → 意图识别
    graph.set_entry_point("intent_recognition")

    # 意图识别 → 路由
    graph.add_edge("intent_recognition", "route")

    # 路由 → 条件分支
    graph.add_conditional_edges(
        "route",
        get_route,
        {
            "faq": "faq_reply",
            "search": "hybrid_search",
            "human": "human_transfer",
        },
    )

    # FAQ → 回复生成
    graph.add_edge("faq_reply", "reply_generation")

    # 检索流程: Hybrid Search → Reranker → GraphRAG → Reply
    graph.add_edge("hybrid_search", "reranker")
    graph.add_edge("reranker", "graphrag")
    graph.add_edge("graphrag", "reply_generation")

    # 终点
    graph.add_edge("reply_generation", END)
    graph.add_edge("human_transfer", END)

    return graph


def compile_customer_service_graph():
    """编译并返回可执行的 graph"""
    return build_customer_service_graph().compile()
