"""Alert Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import action_node, anomaly_detection_node, root_cause_node
from .state import AlertState


def build_alert_graph() -> StateGraph:
    """
    构建 Alert Agent 的 LangGraph 状态机。

    Anomaly Detection → RootCause → Action
    """
    graph = StateGraph(AlertState)

    # --- 注册节点 ---
    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("root_cause", root_cause_node)
    graph.add_node("action", action_node)

    # --- 定义边 ---
    graph.set_entry_point("anomaly_detection")

    def should_analyze(state: AlertState) -> str:
        """如果没有异常，跳过后续分析"""
        anomalies = state.get("anomalies", {})
        count = anomalies.get("detection_summary", {}).get("anomalies_found", 0)
        if count == 0:
            return "end"
        return "analyze"

    graph.add_conditional_edges(
        "anomaly_detection",
        should_analyze,
        {
            "analyze": "root_cause",
            "end": END,
        },
    )

    graph.add_edge("root_cause", "action")
    graph.add_edge("action", END)

    return graph


def compile_alert_graph():
    """编译并返回可执行的 graph"""
    return build_alert_graph().compile()
