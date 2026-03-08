"""Business Advisor Agent LangGraph 状态机定义"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import chat
from .state import BusinessAdvisorState


async def business_advisor_node(state: BusinessAdvisorState) -> BusinessAdvisorState:
    """单节点业务咨询执行器。"""
    result = await chat(
        session_id=state.get("session_id", ""),
        message=state.get("message", ""),
        pool=state.get("db_pool"),
        conversation_history=state.get("conversation_history"),
        images=state.get("images"),
    )
    return {
        "result": result,
        "reply": result.get("reply", ""),
        "intent": result.get("intent", ""),
        "sources": result.get("sources", []),
        "needs_human": result.get("needs_human", False),
    }


def build_business_advisor_graph() -> StateGraph:
    """构建最小可用 Business Advisor graph（单节点）。"""
    graph = StateGraph(BusinessAdvisorState)
    graph.add_node("business_advisor", business_advisor_node)
    graph.set_entry_point("business_advisor")
    graph.add_edge("business_advisor", END)
    return graph


def compile_business_advisor_graph():
    """编译并返回可执行 graph。"""
    return build_business_advisor_graph().compile()
