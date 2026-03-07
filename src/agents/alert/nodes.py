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
from datetime import date

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


async def _get_active_products(pool) -> list[dict]:
    """获取近30天有销售记录的商品（含今日实际销量）。"""
    if not pool:
        return []
    try:
        today = date.today().isoformat()
        rows = await pool.fetch(
            """
            SELECT p.product_id, p.name,
                   COALESCE(sh.quantity, 0) AS today_sales
            FROM products p
            LEFT JOIN sales_history sh
                ON sh.product_id = p.product_id AND sh.sale_date = $1
            WHERE p.status = 'active'
              AND p.product_id IN (
                  SELECT DISTINCT product_id FROM sales_history
                  WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
              )
            ORDER BY COALESCE(sh.quantity, 0) DESC
            LIMIT 50
            """,
            today,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch active products: {e}")
        return []


async def prophet_detection_node(state: AlertState) -> dict:
    """运行 ProphetSkill 对近期活跃商品进行异常检测，将结果注入 state。

    依赖 state['db_pool'] 访问数据库和加载 Prophet 模型。
    任何异常都不会导致整个 Alert Agent 崩溃——失败时返回空列表。
    """
    try:
        from src.skills.prophet_skill import ProphetSkill

        pool = state.get("db_pool")
        prophet = ProphetSkill(pool=pool)

        # 检查是否有已训练的模型，没有则跳过
        if pool:
            try:
                model_count = await pool.fetchval("SELECT COUNT(*) FROM prophet_models")
                if not model_count:
                    logger.info("No trained Prophet models found, skipping ProphetSkill detection")
                    return {"prophet_results": "[]"}
            except Exception as e:
                logger.warning(f"Failed to check prophet_models table: {e}")
                return {"prophet_results": "[]"}

        active_products = await _get_active_products(pool)
        today = date.today().isoformat()

        prophet_results = []
        for product in active_products[:20]:  # 限制前20个，避免超时
            product_id = product["product_id"]
            today_sales = int(product.get("today_sales") or 0)
            try:
                result = await prophet.detect_anomaly(
                    product_id=product_id,
                    date=today,
                    actual_sales=today_sales,
                )
                if result and result.is_anomaly:
                    prophet_results.append(
                        {
                            "product_id": product_id,
                            "product_name": product.get("name", ""),
                            "is_anomaly": result.is_anomaly,
                            "type": result.type,
                            "expected": result.expected,
                            "actual": result.actual,
                            "bounds": result.bounds,
                            "deviation_pct": result.deviation_pct,
                            "severity": result.severity,
                            "reason": result.reason,
                            "date": today,
                        }
                    )
            except Exception as e:
                logger.debug(f"Prophet detection skipped for {product_id}: {e}")
                continue

        logger.info(
            f"ProphetSkill detection: {len(prophet_results)} anomalies out of "
            f"{len(active_products[:20])} products checked"
        )
        return {"prophet_results": json.dumps(prophet_results, ensure_ascii=False)}

    except Exception as e:
        logger.warning(f"ProphetSkill detection failed: {e}")
        return {"prophet_results": "[]"}


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


async def _fetch_competitor_data(pool, product_id: str) -> str:
    """查询竞品价格数据（通过 barcode 匹配）。"""
    if not pool or not product_id:
        return "暂无竞品数据"
    try:
        rows = await pool.fetch(
            """
            SELECT cp.product_name, cp.price, cs.name AS competitor_name, cp.crawled_at
            FROM competitor_products cp
            JOIN competitor_stores cs ON cs.competitor_id = cp.competitor_id
            WHERE cp.barcode IN (
                SELECT barcode FROM products WHERE product_id = $1 AND barcode IS NOT NULL
            )
            ORDER BY cp.crawled_at DESC
            LIMIT 10
            """,
            product_id,
        )
        if not rows:
            return "暂无竞品数据"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)
    except Exception as e:
        logger.debug(f"Failed to fetch competitor data for {product_id}: {e}")
        return "暂无竞品数据"


async def _fetch_inventory_status(pool, product_id: str) -> str:
    """查询商品当前库存状态。"""
    if not pool or not product_id:
        return "暂无库存数据"
    try:
        row = await pool.fetchrow(
            "SELECT name, stock, monthly_sales, status FROM products WHERE product_id = $1",
            product_id,
        )
        if not row:
            return "暂无库存数据"
        return json.dumps(dict(row), ensure_ascii=False, default=str)
    except Exception as e:
        logger.debug(f"Failed to fetch inventory for {product_id}: {e}")
        return "暂无库存数据"


async def _fetch_pricing_history(pool, product_id: str) -> str:
    """查询商品近30天销售趋势（作为价格/销量历史参考）。"""
    if not pool or not product_id:
        return "暂无价格历史"
    try:
        rows = await pool.fetch(
            """
            SELECT sale_date, quantity, revenue
            FROM sales_history
            WHERE product_id = $1 AND sale_date >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY sale_date DESC
            LIMIT 30
            """,
            product_id,
        )
        if not rows:
            return "暂无价格历史"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)
    except Exception as e:
        logger.debug(f"Failed to fetch pricing history for {product_id}: {e}")
        return "暂无价格历史"


async def root_cause_node(state: AlertState) -> dict:
    """
    RootCause Sub-Agent: 逐个异常进行归因分析。
    使用 Opus 模型（复杂推理）。
    """
    anomalies_data = state.get("anomalies", {})
    anomaly_list = anomalies_data.get("anomalies", [])
    existing_causes = list(state.get("root_causes", []))
    errors = list(state.get("errors", []))
    pool = state.get("db_pool")

    # 只处理 critical 和 warning 级别
    for anomaly in anomaly_list:
        if anomaly.get("severity") == "info":
            continue

        product_id = anomaly.get("product_id", "")

        # 从数据库查询真实业务数据
        competitor_data = await _fetch_competitor_data(pool, product_id)
        inventory_status = await _fetch_inventory_status(pool, product_id)
        pricing_history = await _fetch_pricing_history(pool, product_id)

        try:
            prompt = root_cause_prompt(
                product_id=product_id,
                product_name=anomaly.get("product_name", ""),
                anomaly_type=anomaly.get("anomaly_type", ""),
                anomaly_description=anomaly.get("description", ""),
                metrics=json.dumps(anomaly.get("metrics", {}), ensure_ascii=False),
                competitor_data=competitor_data,
                our_data_changes=pricing_history,
                inventory_status=inventory_status,
                pricing_history=pricing_history,
                external_factors="暂无外部因素数据",
                operation_metrics="暂无运营指标数据",
            )
            result = await call_tool(prompt, ROOT_CAUSES_TOOL, model=MODEL_PRO)
            existing_causes.append(result)
        except Exception as e:
            logger.error(f"Root cause analysis failed for {anomaly.get('anomaly_id')}: {e}")
            errors.append(f"root_cause_{anomaly.get('anomaly_id')}: {e}")

    return {"root_causes": existing_causes, "errors": errors}


async def _fetch_product_details(pool, product_id: str) -> dict:
    """查询商品详情（名称、价格、成本、库存、日均销量）。"""
    defaults = {
        "name": product_id,
        "retail_price": 0.0,
        "cost_price": 0.0,
        "stock": 0,
        "avg_daily_sales": 0.0,
    }
    if not pool or not product_id:
        return defaults
    try:
        row = await pool.fetchrow(
            """
            SELECT name, retail_price, cost_price, stock,
                   ROUND(COALESCE(monthly_sales, 0) / 30.0, 2) AS avg_daily_sales
            FROM products
            WHERE product_id = $1
            """,
            product_id,
        )
        if row:
            return dict(row)
    except Exception as e:
        logger.debug(f"Failed to fetch product details for {product_id}: {e}")
    return defaults


async def _fetch_competitor_avg_price(pool, product_id: str) -> float:
    """查询竞品均价。"""
    if not pool or not product_id:
        return 0.0
    try:
        avg_price = await pool.fetchval(
            """
            SELECT AVG(cp.price)
            FROM competitor_products cp
            WHERE cp.barcode IN (
                SELECT barcode FROM products WHERE product_id = $1 AND barcode IS NOT NULL
            )
            AND cp.crawled_at >= NOW() - INTERVAL '7 days'
            """,
            product_id,
        )
        return float(avg_price or 0)
    except Exception as e:
        logger.debug(f"Failed to fetch competitor avg price for {product_id}: {e}")
        return 0.0


async def action_node(state: AlertState) -> dict:
    """
    Action Sub-Agent: 基于归因生成行动建议。
    """
    root_causes_list = state.get("root_causes", [])
    existing_actions = list(state.get("actions", []))
    errors = list(state.get("errors", []))
    pool = state.get("db_pool")

    for cause_result in root_causes_list:
        product_id = cause_result.get("product_id", "")
        primary_cause = cause_result.get("primary_cause", "未知")

        # 从数据库查询真实商品数据
        product_details = await _fetch_product_details(pool, product_id)
        competitor_avg_price = await _fetch_competitor_avg_price(pool, product_id)

        try:
            prompt = action_prompt(
                product_name=product_details.get("name", product_id),
                anomaly_type=cause_result.get("anomaly_type", ""),
                severity=cause_result.get("severity", "warning"),
                primary_cause=primary_cause,
                current_price=float(product_details.get("retail_price") or 0),
                cost_price=float(product_details.get("cost_price") or 0),
                stock=int(product_details.get("stock") or 0),
                avg_daily_sales=float(product_details.get("avg_daily_sales") or 0),
                competitor_avg_price=competitor_avg_price,
            )
            result = await call_tool(prompt, ACTIONS_TOOL, model=MODEL_SONNET)
            existing_actions.append(result)
        except Exception as e:
            logger.error(f"Action generation failed for {product_id}: {e}")
            errors.append(f"action_{product_id}: {e}")

    return {"actions": existing_actions, "errors": errors}
