"""Listing Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import compliance_node, filler_node, matcher_node, parser_node
from .state import ListingState


def build_listing_graph() -> StateGraph:
    """
    构建 Listing Agent 的 LangGraph 状态机。

    Parser → Matcher → Filler → Compliance
    """
    graph = StateGraph(ListingState)

    graph.add_node("parser", parser_node)
    graph.add_node("matcher", matcher_node)
    graph.add_node("filler", filler_node)
    graph.add_node("compliance", compliance_node)

    graph.set_entry_point("parser")
    graph.add_edge("parser", "matcher")
    graph.add_edge("matcher", "filler")
    graph.add_edge("filler", "compliance")
    graph.add_edge("compliance", END)

    return graph


def compile_listing_graph():
    """编译并返回可执行的 graph"""
    return build_listing_graph().compile()
