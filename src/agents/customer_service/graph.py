"""CustomerService Agent Graph 入口。

兼容历史接口：
- build_customer_service_graph()
- compile_customer_service_graph()

现在返回 LangGraph 5步管线（Intent → Search → Rerank → GraphRAG → Reply）。
"""

from __future__ import annotations

from .pipeline import build_cs_pipeline


def build_customer_service_graph():
    """构建 CustomerService LangGraph 管线。"""
    return build_cs_pipeline()


def compile_customer_service_graph():
    """编译并返回 CustomerService LangGraph 管线。"""
    return build_cs_pipeline()
