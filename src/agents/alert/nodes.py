"""Alert Agent 各节点实现"""

from __future__ import annotations

import json
import logging

from ..llm import MODEL_PRO, MODEL_SONNET, call_tool
from ..prompts.alert import action_prompt, anomaly_detection_prompt, root_cause_prompt
from ..tools import ACTIONS_TOOL, ANOMALIES_TOOL, ROOT_CAUSES_TOOL
from .state import AlertState

logger = logging.getLogger(__name__)


async def anomaly_detection_node(state: AlertState) -> dict:
    """
    Anomaly Sub-Agent: 综合 Prophet + 规则检测结果。

    实际的 Prophet 预测和规则检测在 Skills 层完成，
    这里用 LLM 综合分析、去重、判断多因素叠加。
    """
    try:
        prompt = anomaly_detection_prompt(
            products_data=state.get("products_data", "暂无数据"),
            prophet_results=state.get("prophet_results", "暂无数据"),
            rule_check_results=state.get("rule_check_results", "暂无数据"),
            current_time=state.get("current_time", ""),
        )
        result = await call_tool(prompt, ANOMALIES_TOOL, model=MODEL_SONNET)
        return {"anomalies": result, "root_causes": [], "actions": [], "current_anomaly_index": 0}
    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}")
        return {"errors": state.get("errors", []) + [f"anomaly_detection: {e}"]}


async def root_cause_node(state: AlertState) -> dict:
    """
    RootCause Sub-Agent: 逐个异常进行归因分析。
    使用 Opus 模型（复杂推理）。
    """
    anomalies_data = state.get("anomalies", {})
    anomaly_list = anomalies_data.get("anomalies", [])
    existing_causes = list(state.get("root_causes", []))
    errors = list(state.get("errors", []))

    # 只处理 critical 和 warning 级别
    for anomaly in anomaly_list:
        if anomaly.get("severity") == "info":
            continue

        try:
            prompt = root_cause_prompt(
                product_id=anomaly.get("product_id", ""),
                product_name=anomaly.get("product_name", ""),
                anomaly_type=anomaly.get("anomaly_type", ""),
                anomaly_description=anomaly.get("description", ""),
                metrics=json.dumps(anomaly.get("metrics", {}), ensure_ascii=False),
                # NOTE: 实际实现中这些数据由 Skills 层提供
                competitor_data="需要从Skills层获取",
                our_data_changes="需要从Skills层获取",
                inventory_status="需要从Skills层获取",
                pricing_history="需要从Skills层获取",
                external_factors="需要从Skills层获取",
                operation_metrics="需要从Skills层获取",
            )
            result = await call_tool(prompt, ROOT_CAUSES_TOOL, model=MODEL_PRO)
            existing_causes.append(result)
        except Exception as e:
            logger.error(f"Root cause analysis failed for {anomaly.get('anomaly_id')}: {e}")
            errors.append(f"root_cause_{anomaly.get('anomaly_id')}: {e}")

    return {"root_causes": existing_causes, "errors": errors}


async def action_node(state: AlertState) -> dict:
    """
    Action Sub-Agent: 基于归因生成行动建议。
    """
    root_causes_list = state.get("root_causes", [])
    existing_actions = list(state.get("actions", []))
    errors = list(state.get("errors", []))

    for cause_result in root_causes_list:
        product_id = cause_result.get("product_id", "")
        primary_cause = cause_result.get("primary_cause", "未知")

        try:
            prompt = action_prompt(
                product_name=product_id,  # 实际应查商品名
                anomaly_type=cause_result.get("anomaly_type", ""),
                severity="warning",
                primary_cause=primary_cause,
                # NOTE: 实际数据由 Skills 层提供
                current_price=0,
                cost_price=0,
                stock=0,
                avg_daily_sales=0,
                competitor_avg_price=0,
            )
            result = await call_tool(prompt, ACTIONS_TOOL, model=MODEL_SONNET)
            existing_actions.append(result)
        except Exception as e:
            logger.error(f"Action generation failed for {product_id}: {e}")
            errors.append(f"action_{product_id}: {e}")

    return {"actions": existing_actions, "errors": errors}
