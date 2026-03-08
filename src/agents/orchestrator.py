"""
Orchestrator - 总调度 Agent
接收任务请求 → 路由到对应子 Agent → 聚合结果返回
"""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import Any

from .alert.graph import compile_alert_graph
from .bundle.graph import compile_bundle_graph
from .customer_service.graph import compile_customer_service_graph
from .listing.graph import compile_listing_graph
from .selection.graph import compile_selection_graph

logger = logging.getLogger(__name__)
ORCHESTRATION_TIMEOUT_SECONDS = 30
AUTO_ANALYSIS_FAILED_MSG = "自动分析失败，请人工处理"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


async def _selection_alternative_action(anomaly: dict[str, Any], pool) -> dict[str, Any]:
    from .selection import nodes as selection_nodes

    product_id = str(anomaly.get("product_id") or "")
    anomaly_product_name = str(anomaly.get("product_name") or "")
    metrics = anomaly.get("metrics") or {}
    anomaly_category = str(metrics.get("category") or "")

    products = await selection_nodes._get_qnh_products(pool)
    if not products:
        return {"alternatives": []}

    current_product = next((p for p in products if str(p.get("spu_id") or "") == product_id), None)
    current_category = anomaly_category or str((current_product or {}).get("category") or "")
    current_name = anomaly_product_name or str((current_product or {}).get("name") or "")

    candidates: list[dict[str, Any]] = []
    for p in products:
        spu_id = str(p.get("spu_id") or "")
        if spu_id and product_id and spu_id == product_id:
            continue
        stock = _safe_int(p.get("stock"))
        if stock <= 0:
            continue
        category = str(p.get("category") or "")
        name = str(p.get("name") or "")

        if current_category and category and category != current_category:
            continue
        if not current_category and current_name and current_name in name:
            continue

        candidates.append(
            {
                "product_id": spu_id,
                "name": name,
                "category": category,
                "retail_price": _safe_float(p.get("retail_price")),
                "stock": stock,
                "monthly_sales": _safe_int(p.get("monthly_sales")),
            }
        )

    candidates.sort(key=lambda x: (x["monthly_sales"], x["stock"]), reverse=True)
    return {"alternatives": candidates[:5]}


async def _pricing_adjustment_action(anomaly: dict[str, Any], pool) -> dict[str, Any]:
    from .alert import nodes as alert_nodes

    product_id = str(anomaly.get("product_id") or "")
    details = await alert_nodes._fetch_product_details(pool, product_id)
    competitor_avg = await alert_nodes._fetch_competitor_avg_price(pool, product_id)

    current_price = _safe_float(details.get("retail_price"))
    cost_price = _safe_float(details.get("cost_price"))
    floor_price = round(cost_price * 1.08, 2) if cost_price > 0 else 0.0

    target_price = current_price
    if competitor_avg > 0:
        target_price = min(current_price, competitor_avg * 1.02) if current_price > 0 else competitor_avg
    if floor_price > 0:
        target_price = max(target_price, floor_price)
    target_price = round(target_price, 2)

    delta_percent = 0.0
    if current_price > 0:
        delta_percent = round((target_price - current_price) / current_price * 100, 2)

    return {
        "product_id": product_id,
        "product_name": details.get("name") or anomaly.get("product_name") or product_id,
        "current_price": current_price,
        "competitor_avg_price": round(competitor_avg, 2),
        "cost_price": cost_price,
        "suggested_price": target_price,
        "price_change_percent": delta_percent,
        "reason": "基于竞品价格差与成本底线自动生成调价建议",
    }


async def _customer_service_reply_action(anomaly: dict[str, Any], pool) -> dict[str, Any]:
    from .customer_service import nodes as cs_nodes

    query = (
        str(anomaly.get("description") or "")
        or str(anomaly.get("title") or "")
        or str(anomaly.get("product_name") or "")
        or "用户反馈"
    )
    faq_context = await cs_nodes._search_auto_faq_context(query, pool, limit=2)

    standard_reply = "非常抱歉给您带来不便，我们已记录问题并安排优先处理，稍后会第一时间反馈处理结果。"
    if faq_context:
        template = str(faq_context[0].get("answer_template") or "").strip()
        if template:
            standard_reply = template

    return {
        "standard_reply": standard_reply,
        "faq_references": faq_context,
    }


async def _bundle_action(anomaly: dict[str, Any], pool) -> dict[str, Any]:
    from .bundle import nodes as bundle_nodes

    target_name = str(anomaly.get("product_name") or "")
    pairs = await bundle_nodes._fetch_top_association_pairs(pool, limit=30)
    if not pairs:
        return {"bundle_candidates": []}

    if target_name:
        selected = [
            pair
            for pair in pairs
            if target_name in str(pair.get("product_a") or "")
            or target_name in str(pair.get("product_b") or "")
        ]
    else:
        selected = pairs
    selected = selected[:5]

    names = sorted(
        {
            str(pair.get("product_a") or "").strip()
            for pair in selected
        }
        | {
            str(pair.get("product_b") or "").strip()
            for pair in selected
        }
    )
    names = [name for name in names if name]
    catalog_rows = await bundle_nodes._fetch_product_catalog(pool, names)
    catalog = bundle_nodes._build_catalog_index(catalog_rows)

    bundle_candidates: list[dict[str, Any]] = []
    for idx, pair in enumerate(selected, start=1):
        product_a = str(pair.get("product_a") or "")
        product_b = str(pair.get("product_b") or "")
        row_a = catalog.get(bundle_nodes._normalize_key(product_a), {})
        row_b = catalog.get(bundle_nodes._normalize_key(product_b), {})
        bundle_candidates.append(
            {
                "bundle_id": f"auto_bundle_{idx}",
                "products": [
                    {"name": product_a, "product_id": row_a.get("product_id"), "retail_price": _safe_float(row_a.get("retail_price"))},
                    {"name": product_b, "product_id": row_b.get("product_id"), "retail_price": _safe_float(row_b.get("retail_price"))},
                ],
                "co_occurrence": _safe_int(pair.get("co_occurrence")),
                "confidence": _safe_float(pair.get("confidence")),
                "hint": "优先用于滞销品搭售试销",
            }
        )

    return {"bundle_candidates": bundle_candidates[:3]}


async def handle_alert_actions(anomalies: list[dict], pool) -> list[dict]:
    """根据 Alert 异常自动触发其他 Agent 的轻量分析。"""
    if not anomalies or not pool:
        return []

    actions: list[dict[str, Any]] = []

    for anomaly in anomalies:
        anomaly_id = str(anomaly.get("anomaly_id") or "")
        anomaly_type = str(anomaly.get("anomaly_type") or "")
        product_id = str(anomaly.get("product_id") or "")
        base_action = {
            "anomaly_id": anomaly_id,
            "anomaly_type": anomaly_type,
            "product_id": product_id,
        }

        handler = None
        if anomaly_type in {"stockout_urgent", "stockout_warning"}:
            handler = ("selection", "alternative_recommendations", _selection_alternative_action)
        elif anomaly_type in {"competitor_price_drop", "price_gap"}:
            handler = ("pricing", "price_adjustment", _pricing_adjustment_action)
        elif anomaly_type == "negative_review_spike":
            handler = ("customer_service", "standard_reply", _customer_service_reply_action)
        elif anomaly_type == "zero_sales":
            handler = ("bundle", "bundle_recommendation", _bundle_action)

        if not handler:
            continue

        agent_name, action_type, func = handler
        try:
            result = await asyncio.wait_for(
                func(anomaly, pool),
                timeout=ORCHESTRATION_TIMEOUT_SECONDS,
            )
            actions.append(
                {
                    **base_action,
                    "agent": agent_name,
                    "action_type": action_type,
                    "auto_status": "success",
                    "result": result,
                }
            )
        except Exception as exc:
            logger.warning(
                "Alert orchestration failed for anomaly=%s type=%s: %s",
                anomaly_id,
                anomaly_type,
                exc,
            )
            actions.append(
                {
                    **base_action,
                    "agent": agent_name,
                    "action_type": action_type,
                    "auto_status": "failed",
                    "message": AUTO_ANALYSIS_FAILED_MSG,
                    "error": str(exc),
                }
            )

    return actions


class TaskType(StrEnum):
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

    async def _run_customer_service_fallback(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """客服 graph 不可用时，回退到当前线上使用的 chat 路径。"""
        from src.agents.customer_service.nodes import chat as cs_chat
        from src.db import postgres as pg

        pool = None
        try:
            pool = pg.get_pool()
        except Exception:
            logger.warning("Customer service fallback running without PostgreSQL pool")

        return await cs_chat(
            session_id=input_data.get("session_id", ""),
            message=input_data.get("user_message") or input_data.get("message", ""),
            pool=pool,
            conversation_history=input_data.get("conversation_history") or [],
            images=input_data.get("images"),
        )

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
        if task_type == TaskType.CUSTOMER_SERVICE and graph is None:
            logger.warning("Customer service graph is None, falling back to nodes.chat()")
            result = await self._run_customer_service_fallback(input_data)
            logger.info(f"Orchestrator: {task_type.value} completed (fallback)")
            return result

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
