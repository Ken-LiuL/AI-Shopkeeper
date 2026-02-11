"""Bundle Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import order_mining_node, pricing_node, scene_design_node
from .state import BundleState


def build_bundle_graph() -> StateGraph:
    """
    构建 Bundle Agent 的 LangGraph 状态机。

    OrderMining → Scene → Pricing
    """
    graph = StateGraph(BundleState)

    graph.add_node("order_mining", order_mining_node)
    graph.add_node("scene_design", scene_design_node)
    graph.add_node("pricing", pricing_node)

    graph.set_entry_point("order_mining")
    graph.add_edge("order_mining", "scene_design")
    graph.add_edge("scene_design", "pricing")
    graph.add_edge("pricing", END)

    return graph


def compile_bundle_graph():
    """编译并返回可执行的 graph"""
    return build_bundle_graph().compile()
