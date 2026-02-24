"""Alert Agent 各节点实现

融合数据:
  - 退款明细 (qnh_refunds) — 退款率突增时定位到具体 SKU + 原因
  - 营销活动 (qnh_promotions) — 销量波动时先查是否有营销活动，有则不告警
  - 评价NLP (qnh_review_analysis) — 差评趋势作为异常信号
  - 门店 KPI 概览 (qnh_store_metrics_raw) — 同环比异常检测
  - 流量趋势 (qnh_traffic_raw) — 连续下降告警
  - 库存数据 (qnh_inventory_raw) — 缺货率超标告警
"""

from __future__ import annotations

import json
import logging

from src.services.raw_data import fetch_latest_raw

from ..llm import MODEL_PRO, MODEL_SONNET, call_tool
from ..prompts.alert import action_prompt, anomaly_detection_prompt, root_cause_prompt
from ..tools import ACTIONS_TOOL, ANOMALIES_TOOL, ROOT_CAUSES_TOOL
from .state import AlertState

logger = logging.getLogger(__name__)


async def _get_active_promotions(pool) -> list[dict]:
    """查询当前正在进行的营销活动。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT promotion_id, promotion_type, title, start_time, end_time,
                   product_ids, discount_rule
            FROM qnh_promotions
            WHERE status = 'active'
              AND start_time <= NOW() AND end_time >= NOW()
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch active promotions: {e}")
        return []


async def _get_refund_spikes(pool, days: int = 7) -> list[dict]:
    """检测退款率突增的SKU。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT sku_id, sku_name, refund_reason,
                   COUNT(*) as refund_count,
                   SUM(refund_amount) as total_refund
            FROM qnh_refunds
            WHERE refund_time >= CURRENT_DATE - $1 * INTERVAL '1 day'
            GROUP BY sku_id, sku_name, refund_reason
            HAVING COUNT(*) >= 3
            ORDER BY refund_count DESC
            LIMIT 20
            """,
            days,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch refund spikes: {e}")
        return []


async def _check_promotion_explains_spike(pool, product_id: str) -> bool:
    """检查销量波动是否可由当前活动解释。"""
    if not pool:
        return False
    try:
        row = await pool.fetchval(
            """
            SELECT COUNT(*) FROM qnh_promotions
            WHERE status = 'active'
              AND start_time <= NOW() AND end_time >= NOW()
              AND product_ids::jsonb @> $1::jsonb
            """,
            json.dumps([product_id]),
        )
        return (row or 0) > 0
    except Exception:
        return False


async def _check_store_metrics_anomaly(pool, threshold: float = 0.15) -> list[dict]:
    """门店 KPI 同环比异常检测。

    数据来源: qnh_store_metrics_raw (homepage_data_overview_view_not_erp)
    当有效订单金额/客单价/配送费等同比下降超过阈值时触发告警。
    """
    data = await fetch_latest_raw(pool, "qnh_store_metrics_raw")
    if not data:
        return []
    alerts = []
    # raw_data 结构: 包含各指标的同比/环比字段
    items = data if isinstance(data, list) else [data]
    for item in items:
        for key in ("validOrderAmount", "customerPrice", "deliveryFee", "validOrderCount"):
            yoy = item.get(f"{key}YearOnYear") or item.get(f"{key}_yoy")
            if yoy is not None:
                try:
                    yoy_val = (
                        float(str(yoy).replace("%", "")) / 100 if "%" in str(yoy) else float(yoy)
                    )
                except (ValueError, TypeError):
                    continue
                if yoy_val < -threshold:
                    alerts.append(
                        {
                            "type": "store_kpi_decline",
                            "metric": key,
                            "yoy_change": yoy_val,
                            "store_name": item.get("storeName", "未知门店"),
                            "description": f"{key} 同比下降 {abs(yoy_val):.1%}，超过阈值 {threshold:.0%}",
                        }
                    )
    return alerts


async def _check_traffic_trend_anomaly(pool, consecutive_days: int = 3) -> list[dict]:
    """流量趋势异常检测。

    数据来源: qnh_traffic_raw (homepage_date_trend_list_new)
    连续多天下降时触发告警。
    """
    data = await fetch_latest_raw(pool, "qnh_traffic_raw")
    if not data:
        return []
    alerts = []
    # raw_data 通常是按日期排序的列表
    items = data if isinstance(data, list) else []
    if len(items) >= consecutive_days:
        # 检查最近 N 天是否连续下降
        recent = items[-consecutive_days:]
        declining = True
        for i in range(1, len(recent)):
            curr_val = float(recent[i].get("exposure", 0) or recent[i].get("uv", 0) or 0)
            prev_val = float(recent[i - 1].get("exposure", 0) or recent[i - 1].get("uv", 0) or 0)
            if curr_val >= prev_val:
                declining = False
                break
        if declining:
            alerts.append(
                {
                    "type": "traffic_consecutive_decline",
                    "days": consecutive_days,
                    "description": f"流量连续 {consecutive_days} 天下降，请关注",
                }
            )
    return alerts


async def _check_inventory_anomaly(pool, stockout_threshold: float = 0.10) -> list[dict]:
    """库存预警检测。

    数据来源: qnh_inventory_raw (qnh_inventory)
    缺货率超标时触发告警。
    """
    data = await fetch_latest_raw(pool, "qnh_inventory_raw")
    if not data:
        return []
    alerts = []
    items = data if isinstance(data, list) else [data]
    total = len(items)
    stockout_count = 0
    stockout_products = []
    for item in items:
        stock = item.get("stock", item.get("inventory", item.get("availableStock", 0)))
        try:
            stock_val = int(stock or 0)
        except (ValueError, TypeError):
            stock_val = 0
        if stock_val <= 0:
            stockout_count += 1
            stockout_products.append(item.get("productName", item.get("skuName", "未知")))
    if total > 0:
        stockout_rate = stockout_count / total
        if stockout_rate >= stockout_threshold:
            alerts.append(
                {
                    "type": "high_stockout_rate",
                    "stockout_rate": stockout_rate,
                    "stockout_count": stockout_count,
                    "total_products": total,
                    "sample_products": stockout_products[:5],
                    "description": f"缺货率 {stockout_rate:.1%} 超过阈值 {stockout_threshold:.0%}，"
                    f"共 {stockout_count}/{total} 个商品缺货",
                }
            )
    return alerts


async def anomaly_detection_node(state: AlertState) -> dict:
    """
    Anomaly Sub-Agent: 综合 Prophet + 规则检测结果。

    实际的 Prophet 预测和规则检测在 Skills 层完成，
    这里用 LLM 综合分析、去重、判断多因素叠加。

    融合:
      - 当前活动数据：销量spike若可由活动解释则降级为info
      - 退款突增数据：作为额外异常信号
    """
    try:
        # 获取活动和退款上下文
        pool = state.get("db_pool")
        active_promos = await _get_active_promotions(pool)
        refund_spikes = await _get_refund_spikes(pool)

        promo_context = ""
        if active_promos:
            promo_context = (
                "\n\n# 当前正在进行的营销活动（销量波动若可由活动解释则降级为info）\n"
                + json.dumps(active_promos, ensure_ascii=False, default=str)
            )

        refund_context = ""
        if refund_spikes:
            refund_context = "\n\n# 近7天退款突增SKU（退款率异常需额外关注）\n" + json.dumps(
                refund_spikes, ensure_ascii=False, default=str
            )

        # 新增: 门店KPI/流量趋势/库存 异常检测
        kpi_alerts = await _check_store_metrics_anomaly(pool)
        traffic_alerts = await _check_traffic_trend_anomaly(pool)
        inventory_alerts = await _check_inventory_anomaly(pool)

        raw_data_context = ""
        if kpi_alerts:
            raw_data_context += (
                "\n\n# 门店KPI同环比异常（来自 qnh_store_metrics_raw）\n"
                + json.dumps(kpi_alerts, ensure_ascii=False, default=str)
            )
        if traffic_alerts:
            raw_data_context += "\n\n# 流量趋势异常（来自 qnh_traffic_raw）\n" + json.dumps(
                traffic_alerts, ensure_ascii=False, default=str
            )
        if inventory_alerts:
            raw_data_context += "\n\n# 库存预警（来自 qnh_inventory_raw）\n" + json.dumps(
                inventory_alerts, ensure_ascii=False, default=str
            )

        prompt = anomaly_detection_prompt(
            products_data=state.get("products_data", "暂无数据"),
            prophet_results=state.get("prophet_results", "暂无数据"),
            rule_check_results=state.get("rule_check_results", "暂无数据")
            + promo_context
            + refund_context
            + raw_data_context,
            current_time=state.get("current_time", ""),
        )
        result = await call_tool(prompt, ANOMALIES_TOOL, model=MODEL_SONNET)

        # 后处理：销量spike且有对应活动 → 降级为info
        anomaly_list = result.get("anomalies", [])
        for anomaly in anomaly_list:
            if anomaly.get("anomaly_type") in ("sales_spike_prophet", "sales_spike"):
                pid = anomaly.get("product_id", "")
                if pid and await _check_promotion_explains_spike(pool, pid):
                    anomaly["severity"] = "info"
                    anomaly["description"] = (
                        anomaly.get("description", "") + "（已确认有活动进行中，非异常波动）"
                    )

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
