"""Selection Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import (
    competitor_analysis_node,
    fetch_data,
    gap_identification_node,
    inventory_analysis_node,
    market_analysis_node,
    scorer_node,
    seasonal_analysis_node,
    supplier_evaluation_node,
)
from .state import SelectionState


def build_selection_graph() -> StateGraph:
    """
    构建 Selection Agent 的 LangGraph 状态机。

    Phase 1: 并行执行 Market + Competitor + Inventory + Seasonal
    Phase 2: Gap Identification
    Phase 3: Supplier Evaluation（1688 + 拼多多）
    Phase 4: Scorer + Self-Reflection
    """
    graph = StateGraph(SelectionState)

    # --- 注册节点 ---
    graph.add_node("fetch_data", fetch_data)
    graph.add_node("market_analysis", market_analysis_node)
    graph.add_node("competitor_analysis", competitor_analysis_node)
    graph.add_node("inventory_analysis", inventory_analysis_node)
    graph.add_node("seasonal_analysis", seasonal_analysis_node)
    graph.add_node("gap_identification", gap_identification_node)
    graph.add_node("supplier_evaluation", supplier_evaluation_node)
    graph.add_node("scorer", scorer_node)

    # --- 定义边 ---

    # 入口 → 数据采集
    graph.set_entry_point("fetch_data")

    # Phase 1: 数据采集后并行执行 4 个分析节点
    graph.add_edge("fetch_data", "market_analysis")
    graph.add_edge("fetch_data", "competitor_analysis")
    graph.add_edge("fetch_data", "inventory_analysis")
    graph.add_edge("fetch_data", "seasonal_analysis")

    # Phase 2: 4 个分析节点全部完成后 → Gap Identification
    graph.add_edge("market_analysis", "gap_identification")
    graph.add_edge("competitor_analysis", "gap_identification")
    graph.add_edge("inventory_analysis", "gap_identification")
    graph.add_edge("seasonal_analysis", "gap_identification")

    # Phase 3: Gap → Supplier Evaluation
    graph.add_edge("gap_identification", "supplier_evaluation")

    # Phase 4: Supplier → Scorer
    graph.add_edge("supplier_evaluation", "scorer")

    # 结束
    graph.add_edge("scorer", END)

    return graph


def compile_selection_graph():
    """编译并返回可执行的 graph"""
    return build_selection_graph().compile()
