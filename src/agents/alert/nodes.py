# 注意：此文件的 data_insufficient 改动通过 orchestrator/agent 路径生效。
# 前端 /api/alerts 直接查 DB（不经过此 agent），前端空状态由 alerts.py 和 /api/alerts/status 控制。
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
import statistics
from datetime import UTC, date, datetime

from src.services.raw_data import fetch_latest_raw

from ..llm import MODEL_PRO, MODEL_SONNET, call_tool, call_tool_with_reflection
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
    无数据时优雅返回空 list，不报错。
    """
    try:
        data = await fetch_latest_raw(pool, "qnh_store_metrics_raw")
        if not data:
            return []
        alerts = []
        # raw_data 结构: 包含各指标的同比/环比字段
        items = data if isinstance(data, list) else [data]
        if len(items) < 3:
            return [{
                "type": "data_insufficient",
                "severity": "info",
                "title": "数据积累中",
                "message": f"需要至少3天历史数据才能进行门店KPI异常检测（当前{len(items)}条记录）",
                "recommendation": "请继续正常运营，系统将自动开始监测",
                "is_info": True,
            }]
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
    except Exception as e:
        logger.warning(f"check_store_metrics_anomaly failed (graceful): {e}")
        return []


async def _check_traffic_trend_anomaly(pool, consecutive_days: int = 3) -> list[dict]:
    """流量趋势异常检测。

    数据来源: qnh_traffic_raw (homepage_date_trend_list_new)
    连续多天下降时触发告警。
    无数据时优雅返回空 list，不报错。
    """
    try:
        data = await fetch_latest_raw(pool, "qnh_traffic_raw")
        if not data:
            return []
        alerts = []
        # raw_data 通常是按日期排序的列表
        items = data if isinstance(data, list) else []
        if len(items) < 3:
            return [{
                "type": "data_insufficient",
                "severity": "info",
                "title": "数据积累中",
                "message": f"需要至少3天历史数据才能进行流量趋势异常检测（当前{len(items)}天）",
                "recommendation": "请继续正常运营，系统将自动开始监测",
                "is_info": True,
            }]
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
    except Exception as e:
        logger.warning(f"check_traffic_trend_anomaly failed (graceful): {e}")
        return []


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
    if len(items) < 3:
        return [{
            "type": "data_insufficient",
            "severity": "info",
            "title": "数据积累中",
            "message": f"需要至少3条库存记录才能进行异常检测（当前{len(items)}条）",
            "recommendation": "请继续正常运营，系统将自动开始监测",
            "is_info": True,
        }]
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
            SELECT p.spu_id AS product_id, p.name,
                   COALESCE(sh.quantity_sold, 0) AS today_sales
            FROM qnh_products p
            LEFT JOIN qnh_sales_history sh
                ON sh.spu_id = p.spu_id AND sh.date = $1
            WHERE p.status = 'active'
              AND p.spu_id IN (
                  SELECT DISTINCT spu_id FROM qnh_sales_history
                  WHERE date >= CURRENT_DATE - INTERVAL '30 days'
              )
            ORDER BY COALESCE(sh.quantity_sold, 0) DESC
            LIMIT 50
            """,
            today,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch active products: {e}")
        return []


async def _fetch_recent_sales_series(pool, product_id: str, days: int = 30) -> list[int]:
    """获取商品近 N 天销量序列（用于统计降级检测）。"""
    if not pool or not product_id:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT quantity_sold AS quantity
            FROM qnh_sales_history
            WHERE spu_id = $1
              AND date >= CURRENT_DATE - $2 * INTERVAL '1 day'
            ORDER BY date ASC
            """,
            product_id,
            days,
        )
        return [int(r["quantity"] or 0) for r in rows]
    except Exception as e:
        logger.debug(f"Failed to fetch sales series for {product_id}: {e}")
        return []


def _zscore_anomaly(
    series: list[int],
    actual_sales: int,
    *,
    z_threshold: float = 2.5,
) -> dict | None:
    """使用 Z-Score 进行简易异常检测，返回异常字典（无异常返回 None）。"""
    if len(series) < 3:
        return None
    mean_val = statistics.mean(series)
    std_val = statistics.pstdev(series)
    if std_val <= 0:
        return None

    z = (actual_sales - mean_val) / std_val
    if abs(z) < z_threshold:
        return None

    anomaly_type = "spike" if z > 0 else "drop"
    deviation_pct = abs(actual_sales - mean_val) / max(abs(mean_val), 1)
    severity = "critical" if abs(z) >= 3.5 else "warning"
    return {
        "is_anomaly": True,
        "type": anomaly_type,
        "expected": round(mean_val, 1),
        "actual": actual_sales,
        "bounds": [round(mean_val - std_val, 1), round(mean_val + std_val, 1)],
        "deviation_pct": round(deviation_pct, 3),
        "severity": severity,
        "reason": f"zscore={z:.2f}",
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _check_traffic_spike_drop_anomaly(pool, threshold: float = 0.30) -> list[dict]:
    """检测 qnh_traffic 流量突降/突增。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT traffic_date,
                   SUM(COALESCE(impressions, 0)) AS impressions,
                   SUM(COALESCE(clicks, 0)) AS clicks
            FROM qnh_traffic
            GROUP BY traffic_date
            ORDER BY traffic_date DESC
            LIMIT 2
            """
        )
        if len(rows) < 2:
            return []

        latest = dict(rows[0])
        previous = dict(rows[1])
        latest_val = float(latest.get("impressions") or latest.get("clicks") or 0)
        previous_val = float(previous.get("impressions") or previous.get("clicks") or 0)
        if previous_val <= 0:
            return []

        change_pct = (latest_val - previous_val) / previous_val
        if abs(change_pct) < threshold:
            return []

        is_drop = change_pct < 0
        return [
            {
                "anomaly_id": f"traffic_{latest['traffic_date']}",
                "product_id": "store_traffic",
                "product_name": "门店整体流量",
                "anomaly_type": "exposure_drop" if is_drop else "multi_factor",
                "severity": "critical" if is_drop and abs(change_pct) >= 0.50 else "warning",
                "detection_method": "rule",
                "metrics": {
                    "expected_value": round(previous_val, 2),
                    "actual_value": round(latest_val, 2),
                    "deviation_percent": round(change_pct * 100, 2),
                    "threshold": round(threshold * 100, 2),
                },
                "description": (
                    f"近两日流量{'突降' if is_drop else '突增'}"
                    f"{abs(change_pct):.1%}（{previous['traffic_date']} -> {latest['traffic_date']}）"
                ),
                "detected_at": _utc_now_iso(),
            }
        ]
    except Exception as e:
        logger.warning(f"Failed to check qnh_traffic anomaly: {e}")
        return []


async def _check_inventory_low_stock_anomaly(pool, low_stock_threshold: int = 10) -> list[dict]:
    """检测 qnh_inventory 低库存/断货。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            WITH latest_stock AS (
                SELECT DISTINCT ON (spu_id)
                    spu_id,
                    product_name,
                    COALESCE(current_stock, available_stock, 0) AS stock,
                    snapshot_time
                FROM qnh_inventory
                WHERE spu_id IS NOT NULL
                ORDER BY spu_id, snapshot_time DESC
            )
            SELECT spu_id, product_name, stock
            FROM latest_stock
            WHERE stock < $1
            ORDER BY stock ASC
            LIMIT 50
            """,
            low_stock_threshold,
        )
        anomalies = []
        for r in rows:
            row_data = dict(r)
            stock = int(row_data.get("stock") or 0)
            is_stockout = stock <= 0
            anomalies.append(
                {
                    "anomaly_id": f"inventory_{row_data['spu_id']}_{'stockout' if is_stockout else 'low'}",
                    "product_id": str(row_data.get("spu_id") or ""),
                    "product_name": row_data.get("product_name") or "未知商品",
                    "anomaly_type": "stockout_urgent" if is_stockout else "stockout_warning",
                    "severity": "critical" if is_stockout else "warning",
                    "detection_method": "rule",
                    "metrics": {
                        "expected_value": float(low_stock_threshold),
                        "actual_value": float(stock),
                        "deviation_percent": round(((stock - low_stock_threshold) / low_stock_threshold) * 100, 2),
                        "threshold": float(low_stock_threshold),
                    },
                    "description": (
                        f"{'断货' if is_stockout else '低库存'}预警：当前库存 {stock}，阈值 < {low_stock_threshold}"
                    ),
                    "detected_at": _utc_now_iso(),
                }
            )
        return anomalies
    except Exception as e:
        logger.warning(f"Failed to check qnh_inventory anomaly: {e}")
        return []


async def _check_delivery_timeout_anomaly(pool, threshold: float = 0.05) -> list[dict]:
    """检测最近24小时配送超时率。"""
    if not pool:
        return []
    try:
        row = await pool.fetchrow(
            """
            WITH timeout_stats AS (
                SELECT COUNT(*)::int AS timeout_count
                FROM delivery_timeouts
                WHERE create_time >= NOW() - INTERVAL '24 hours'
            ),
            order_stats AS (
                SELECT COUNT(*)::int AS total_orders
                FROM qnh_orders
                WHERE order_time >= NOW() - INTERVAL '24 hours'
            )
            SELECT
                t.timeout_count,
                o.total_orders,
                CASE
                    WHEN o.total_orders > 0 THEN t.timeout_count::float / o.total_orders
                    ELSE NULL
                END AS timeout_rate
            FROM timeout_stats t, order_stats o
            """
        )
        if not row:
            return []

        row_data = dict(row)
        timeout_count = int(row_data.get("timeout_count") or 0)
        total_orders = int(row_data.get("total_orders") or 0)
        timeout_rate = float(row_data.get("timeout_rate") or 0)

        if total_orders <= 0 or timeout_rate < threshold:
            return []

        return [
            {
                "anomaly_id": "delivery_timeout_24h",
                "product_id": "store_delivery",
                "product_name": "门店配送",
                "anomaly_type": "multi_factor",
                "severity": "critical" if timeout_rate >= threshold * 2 else "warning",
                "detection_method": "rule",
                "metrics": {
                    "expected_value": round(threshold * 100, 2),
                    "actual_value": round(timeout_rate * 100, 2),
                    "deviation_percent": round((timeout_rate - threshold) * 100, 2),
                    "threshold": round(threshold * 100, 2),
                },
                "description": (
                    f"最近24小时配送超时率 {timeout_rate:.1%}，"
                    f"超时 {timeout_count}/{total_orders} 单"
                ),
                "detected_at": _utc_now_iso(),
            }
        ]
    except Exception as e:
        logger.warning(f"Failed to check delivery timeout anomaly: {e}")
        return []


async def _check_competitor_price_change_anomaly(pool, threshold_pct: float = 5.0) -> list[dict]:
    """检测 competitor_price_changes 竞品价格异动。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT product_name, store_name, old_price, new_price, change_pct, detected_at
            FROM competitor_price_changes
            WHERE detected_at >= NOW() - INTERVAL '24 hours'
              AND ABS(COALESCE(change_pct, 0)) >= $1
            ORDER BY ABS(change_pct) DESC
            LIMIT 10
            """,
            threshold_pct,
        )
        anomalies = []
        for i, r in enumerate(rows, start=1):
            row_data = dict(r)
            change_pct = float(row_data.get("change_pct") or 0)
            anomalies.append(
                {
                    "anomaly_id": f"competitor_change_{i}",
                    "product_id": "market_competitor",
                    "product_name": row_data.get("product_name") or "竞品",
                    "anomaly_type": "competitor_price_drop",
                    "severity": "warning" if change_pct < 0 else "info",
                    "detection_method": "rule",
                    "metrics": {
                        "expected_value": float(row_data.get("old_price") or 0),
                        "actual_value": float(row_data.get("new_price") or 0),
                        "deviation_percent": round(change_pct, 2),
                        "threshold": float(threshold_pct),
                    },
                    "description": (
                        f"竞品 {row_data.get('store_name') or '未知店铺'} 价格变动 {change_pct:.2f}%"
                    ),
                    "detected_at": _utc_now_iso(),
                }
            )
        return anomalies
    except Exception as e:
        logger.warning(f"Failed to check competitor price change anomaly: {e}")
        return []


async def _check_platform_penalty_anomaly(pool) -> list[dict]:
    """检测 platform_penalties 平台处罚通知。"""
    if not pool:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT keyword_matched, content, COALESCE(original_time, detected_at) AS event_time
            FROM platform_penalties
            WHERE detected_at >= NOW() - INTERVAL '24 hours'
            ORDER BY detected_at DESC
            LIMIT 5
            """
        )
        anomalies = []
        for i, r in enumerate(rows, start=1):
            row_data = dict(r)
            content = str(row_data.get("content") or "")
            short_content = (content[:100] + "...") if len(content) > 100 else content
            anomalies.append(
                {
                    "anomaly_id": f"platform_penalty_{i}",
                    "product_id": "store_platform",
                    "product_name": "平台通知",
                    "anomaly_type": "multi_factor",
                    "severity": "critical",
                    "detection_method": "rule",
                    "metrics": {
                        "expected_value": 0,
                        "actual_value": 1,
                        "deviation_percent": 100,
                        "threshold": 0,
                    },
                    "description": (
                        f"检测到平台处罚/警告关键词「{row_data.get('keyword_matched') or '未知'}」：{short_content}"
                    ),
                    "detected_at": _utc_now_iso(),
                }
            )
        return anomalies
    except Exception as e:
        logger.warning(f"Failed to check platform penalty anomaly: {e}")
        return []


async def check_isolation_forest_anomaly(pool) -> list[dict]:
    """用 Isolation Forest 进行多维度异常检测（与 Prophet 并行运行）。

    检测两个层面：
    1. 门店整体日指标（order_count / gmv / avg_order_value）
    2. 商品级特征矩阵（销量 / 库存 / 价格 / 销售斜率）

    无数据时优雅返回空列表，不抛异常。
    """
    if not pool:
        return []
    try:
        from src.skills.isolation_forest_skill import IsolationForestSkill

        skill = IsolationForestSkill(contamination=0.05)

        # 门店整体多维检测
        store_results = await skill.detect_anomalies(pool, days=30)
        store_anomalies = [r for r in store_results if r["is_anomaly"]]

        # 商品级检测
        product_anomalies = await skill.detect_product_anomalies(pool, days=30)

        anomalies: list[dict] = []

        for r in store_anomalies:
            score = r["anomaly_score"]
            severity = "critical" if score < -0.15 else "warning"
            metrics_snapshot = r.get("metrics", {})
            anomalies.append(
                {
                    "anomaly_id": f"if_store_{r['date']}",
                    "product_id": "store_overall",
                    "product_name": "门店整体指标",
                    "anomaly_type": "multi_factor",
                    "severity": severity,
                    "detection_method": "isolation_forest",
                    "metrics": {
                        "anomaly_score": score,
                        "expected_value": 0.0,
                        "actual_value": score,
                        "deviation_percent": round(abs(score) * 100, 2),
                        "threshold": -0.10,
                        **{f"metric_{k}": v for k, v in metrics_snapshot.items()},
                    },
                    "description": (
                        f"Isolation Forest 检测到 {r['date']} 门店指标联合异常 "
                        f"(score={score:.3f})，"
                        f"涉及指标：{', '.join(f'{k}={v:.1f}' for k, v in metrics_snapshot.items())}"
                    ),
                    "detected_at": _utc_now_iso(),
                }
            )

        for r in product_anomalies:
            score = r["anomaly_score"]
            severity = "critical" if score < -0.15 else "warning"
            features = r.get("features", {})
            anomalies.append(
                {
                    "anomaly_id": f"if_product_{r['product_id']}",
                    "product_id": str(r["product_id"]),
                    "product_name": r.get("product_name", ""),
                    "anomaly_type": "multi_factor",
                    "severity": severity,
                    "detection_method": "isolation_forest",
                    "metrics": {
                        "anomaly_score": score,
                        "expected_value": 0.0,
                        "actual_value": score,
                        "deviation_percent": round(abs(score) * 100, 2),
                        "threshold": -0.10,
                        **{f"feature_{k}": v for k, v in features.items()},
                    },
                    "description": (
                        f"商品「{r.get('product_name', r['product_id'])}」多维特征异常 "
                        f"(score={score:.3f})，"
                        f"avg_sales={features.get('avg_daily_sales', 0):.1f}，"
                        f"stock={features.get('current_stock', 0):.0f}，"
                        f"price={features.get('price', 0):.2f}"
                    ),
                    "detected_at": _utc_now_iso(),
                }
            )

        logger.info(
            f"check_isolation_forest_anomaly: {len(anomalies)} anomalies "
            f"({len(store_anomalies)} store + {len(product_anomalies)} product)"
        )
        return anomalies

    except Exception as e:
        logger.warning(f"check_isolation_forest_anomaly failed (graceful): {e}")
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

        # 检查是否有已训练的模型
        has_prophet_model = True
        if pool:
            try:
                model_count = await pool.fetchval("SELECT COUNT(*) FROM prophet_models")
                if not model_count:
                    has_prophet_model = False
                    logger.info(
                        "No trained Prophet models found, Prophet detection will use fallback when possible"
                    )
            except Exception as e:
                logger.warning(f"Failed to check prophet_models table: {e}")
                has_prophet_model = False

        active_products = await _get_active_products(pool)
        today = date.today().isoformat()

        prophet_results = []
        fallback_events: list[dict] = []
        for product in active_products[:20]:  # 限制前20个，避免超时
            product_id = product["product_id"]
            today_sales = int(product.get("today_sales") or 0)
            recent_sales = await _fetch_recent_sales_series(pool, product_id, days=30)
            history_days = len(recent_sales)
            try:
                use_fallback = (not has_prophet_model) or history_days < 14
                fallback_reason = None

                if history_days < 14:
                    fallback_reason = "历史数据不足14天，使用统计检测"
                elif not has_prophet_model:
                    fallback_reason = "Prophet 模型未训练，使用统计检测"

                if use_fallback:
                    fallback_events.append(
                        {
                            "product_id": product_id,
                            "product_name": product.get("name", ""),
                            "reason": fallback_reason,
                            "history_days": history_days,
                        }
                    )
                    z_result = _zscore_anomaly(recent_sales, today_sales)
                    if z_result and z_result.get("is_anomaly"):
                        prophet_results.append(
                            {
                                "product_id": product_id,
                                "product_name": product.get("name", ""),
                                "is_anomaly": True,
                                "type": z_result["type"],
                                "expected": z_result["expected"],
                                "actual": z_result["actual"],
                                "bounds": z_result["bounds"],
                                "deviation_pct": z_result["deviation_pct"],
                                "severity": z_result["severity"],
                                "reason": z_result["reason"],
                                "date": today,
                                "detection_method": "zscore_fallback",
                                "metadata": {
                                    "fallback_reason": fallback_reason,
                                    "history_days": history_days,
                                },
                            }
                        )
                    continue

                result = await prophet.detect_anomaly(product_id=product_id, date=today, actual_sales=today_sales)
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
                            "detection_method": "prophet",
                        }
                    )
            except Exception as e:
                logger.debug(f"Prophet detection skipped for {product_id}: {e}")
                continue

        logger.info(
            f"ProphetSkill detection: {len(prophet_results)} anomalies out of "
            f"{len(active_products[:20])} products checked"
        )
        return {
            "prophet_results": json.dumps(prophet_results, ensure_ascii=False),
            "prophet_detection_metadata": {
                "fallback_count": len(fallback_events),
                "fallback_events": fallback_events,
            },
        }

    except Exception as e:
        logger.warning(f"ProphetSkill detection failed: {e}")
        return {
            "prophet_results": "[]",
            "prophet_detection_metadata": {
                "fallback_count": 0,
                "fallback_events": [],
            },
        }


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

        # 新增: 结构化表异常检测（全部独立 try/except）
        import asyncio as _asyncio
        (
            traffic_table_alerts,
            inventory_table_alerts,
            delivery_timeout_alerts,
            competitor_change_alerts,
            platform_penalty_alerts,
            isolation_forest_alerts,
        ) = await _asyncio.gather(
            _check_traffic_spike_drop_anomaly(pool),
            _check_inventory_low_stock_anomaly(pool),
            _check_delivery_timeout_anomaly(pool),
            _check_competitor_price_change_anomaly(pool),
            _check_platform_penalty_anomaly(pool),
            check_isolation_forest_anomaly(pool),  # Isolation Forest 与其他检测并行
        )

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

        # 新增: 结构化数据源异常直接注入 anomalies
        anomaly_list.extend(traffic_table_alerts)
        anomaly_list.extend(inventory_table_alerts)
        anomaly_list.extend(delivery_timeout_alerts)
        anomaly_list.extend(competitor_change_alerts)
        anomaly_list.extend(platform_penalty_alerts)
        anomaly_list.extend(isolation_forest_alerts)  # Isolation Forest 多维异常

        summary = result.setdefault("detection_summary", {})
        summary["anomalies_found"] = len(anomaly_list)
        summary["critical_count"] = sum(1 for a in anomaly_list if a.get("severity") == "critical")
        summary["warning_count"] = sum(1 for a in anomaly_list if a.get("severity") == "warning")

        prophet_meta = state.get("prophet_detection_metadata", {}) or {}
        fallback_events = prophet_meta.get("fallback_events", [])
        metadata = result.setdefault("metadata", {})
        metadata["detection_method"] = "prophet"
        if fallback_events:
            metadata["detection_method"] = "zscore_fallback"
            metadata["details"] = (
                f"{len(fallback_events)} 个商品因历史数据不足14天或缺少模型，已使用统计检测（Z-Score）"
            )
            metadata["fallback_events"] = fallback_events

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
                SELECT barcode FROM qnh_products WHERE spu_id = $1 AND barcode IS NOT NULL
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
            "SELECT name, stock, monthly_sales, status FROM qnh_products WHERE spu_id = $1",
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
            FROM (
                SELECT date AS sale_date, quantity_sold AS quantity, revenue, spu_id
                FROM qnh_sales_history
            ) sh
            WHERE sh.spu_id = $1 AND sh.sale_date >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY sh.sale_date DESC
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
        # === GraphRAG 增强 ===
        graph_context = ""
        try:
            from src.db import neo4j as neo4j_db
            from src.skills.neo4j_skill import Neo4jSkill

            driver = neo4j_db.get_driver()
            skill = Neo4jSkill(driver=driver)
            impact_chain = await skill.get_impact_chain(product_id, depth=2)
            if impact_chain:
                lines = ["\n\n# 关联商品影响分析", "该商品异常可能影响以下关联商品："]
                for item in impact_chain:
                    name = str(item.get("name") or item.get("product_id") or "未知商品")
                    stock = item.get("stock")
                    distance = item.get("distance", 1)
                    lines.append(f"- {name}（库存:{stock}，距离:{distance}跳）")
                graph_context = "\n".join(lines) + "\n"
        except Exception:
            graph_context = ""

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
                external_factors=f"暂无外部因素数据{graph_context}",
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
            FROM qnh_products
            WHERE spu_id = $1
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
                SELECT barcode FROM qnh_products WHERE spu_id = $1 AND barcode IS NOT NULL
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
        anomaly_type = cause_result.get("anomaly_type", "")
        primary_cause = cause_result.get("primary_cause", "未知")

        # 从数据库查询真实商品数据
        product_details = await _fetch_product_details(pool, product_id)
        competitor_avg_price = await _fetch_competitor_avg_price(pool, product_id)
        product_name = product_details.get("name", product_id)

        memory_ctx = ""
        if pool:
            try:
                from src.agents.action_tracker import format_memory_context

                memory_ctx = await format_memory_context(
                    pool=pool,
                    agent_type="alert",
                    action_type=anomaly_type or "unknown",
                    product_name=product_name,
                )
            except Exception as e:
                logger.warning("Failed to load alert memory context for %s: %s", product_id, e)

        try:
            prompt = action_prompt(
                product_name=product_name,
                anomaly_type=anomaly_type,
                severity=cause_result.get("severity", "warning"),
                primary_cause=primary_cause,
                current_price=float(product_details.get("retail_price") or 0),
                cost_price=float(product_details.get("cost_price") or 0),
                stock=int(product_details.get("stock") or 0),
                avg_daily_sales=float(product_details.get("avg_daily_sales") or 0),
                competitor_avg_price=competitor_avg_price,
            )
            if memory_ctx:
                prompt = f"{prompt}\n{memory_ctx}"
            def _reflect_actions(initial_result_str: str) -> str:
                return f"""请审查以下行动建议，检查：
1. 建议价格是否在合理范围内（≥成本×1.25，≤竞品均价×1.05）
2. 建议的优先级是否与严重程度匹配
3. 是否遗漏了重要的行动项
4. 数据引用是否准确

初始建议：
{initial_result_str}

请给出修订后的版本，如果没问题则保持不变。"""

            result = await call_tool_with_reflection(
                initial_prompt=prompt,
                reflection_prompt_fn=_reflect_actions,
                tool=ACTIONS_TOOL,
                model=MODEL_SONNET,
            )

            # === 事实核查 ===
            try:
                from src.agents.fact_checker import validate_agent_output

                validation = await validate_agent_output(pool, "alert", result)
                if not validation["valid"]:
                    result["fact_check_warnings"] = validation["warnings"]
                    result["fact_check_passed"] = False
                    logger.warning(f"Alert action failed fact check: {validation['warnings']}")
                elif validation["warnings"]:
                    result["fact_check_warnings"] = validation["warnings"]
                    result["fact_check_passed"] = True
            except Exception:
                pass

            existing_actions.append(result)

            if pool:
                try:
                    from src.agents.action_tracker import record_action

                    await record_action(
                        pool=pool,
                        agent_type="alert",
                        action_type=anomaly_type or "unknown",
                        product_id=product_id or None,
                        product_name=product_name,
                        decision=result if isinstance(result, dict) else {"result": result},
                        confidence=float(cause_result.get("confidence", 0.8) or 0.8),
                        context_summary=f"{anomaly_type}: {primary_cause}",
                        baseline_metrics={
                            "sales_7d": round(float(product_details.get("avg_daily_sales") or 0) * 7, 2),
                            "price": float(product_details.get("retail_price") or 0),
                            "stock": int(product_details.get("stock") or 0),
                            "competitor_avg_price": competitor_avg_price,
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to record alert action for %s: %s", product_id, e)
        except Exception as e:
            logger.error(f"Action generation failed for {product_id}: {e}")
            errors.append(f"action_{product_id}: {e}")

    return {"actions": existing_actions, "errors": errors}
