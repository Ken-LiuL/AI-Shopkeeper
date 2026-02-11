"""
Orchestrator - 总调度 Agent
接收任务请求 → 路由到对应子 Agent → 聚合结果返回
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from .alert.graph import compile_alert_graph
from .bundle.graph import compile_bundle_graph
from .customer_service.graph import compile_customer_service_graph
from .listing.graph import compile_listing_graph
from .selection.graph import compile_selection_graph

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    SELECTION = "selection"
    CUSTOMER_SERVICE = "customer_service"
    ALERT = "alert"
    BUNDLE = "bundle"
    LISTING = "listing"


class Orchestrator:
    """
    总调度器：接收任务请求，路由到对应的子 Agent，聚合结果返回。
    """

    def __init__(self):
        self._graphs: dict[TaskType, Any] = {}

    def _get_graph(self, task_type: TaskType):
        """惰性编译 graph"""
        if task_type not in self._graphs:
            builders = {
                TaskType.SELECTION: compile_selection_graph,
                TaskType.CUSTOMER_SERVICE: compile_customer_service_graph,
                TaskType.ALERT: compile_alert_graph,
                TaskType.BUNDLE: compile_bundle_graph,
                TaskType.LISTING: compile_listing_graph,
            }
            self._graphs[task_type] = builders[task_type]()
        return self._graphs[task_type]

    async def run(self, task_type: TaskType | str, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        执行任务。

        Args:
            task_type: 任务类型
            input_data: 输入数据（对应各 Agent 的 State 字段）

        Returns:
            Agent 执行后的完整 State
        """
        if isinstance(task_type, str):
            task_type = TaskType(task_type)

        logger.info(f"Orchestrator: routing to {task_type.value}")

        graph = self._get_graph(task_type)
        result = await graph.ainvoke(input_data)

        logger.info(f"Orchestrator: {task_type.value} completed")
        return result

    async def run_selection(self, **kwargs) -> dict[str, Any]:
        """快捷方法：运行选品 Agent"""
        return await self.run(TaskType.SELECTION, kwargs)

    async def run_customer_service(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        session_id: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        """快捷方法：运行客服 Agent"""
        return await self.run(
            TaskType.CUSTOMER_SERVICE,
            {
                "user_message": user_message,
                "conversation_history": conversation_history or [],
                "session_id": session_id,
                **kwargs,
            },
        )

    async def run_alert(self, **kwargs) -> dict[str, Any]:
        """快捷方法：运行预警 Agent"""
        return await self.run(TaskType.ALERT, kwargs)

    async def run_bundle(self, **kwargs) -> dict[str, Any]:
        """快捷方法：运行套餐 Agent"""
        return await self.run(TaskType.BUNDLE, kwargs)

    async def run_listing(
        self,
        source_url: str,
        source_platform: str = "alibaba",
        raw_product_data: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        """快捷方法：运行上架 Agent"""
        return await self.run(
            TaskType.LISTING,
            {
                "source_url": source_url,
                "source_platform": source_platform,
                "raw_product_data": raw_product_data,
                **kwargs,
            },
        )
