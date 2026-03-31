"""Alert Agent API routes."""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg
from src.services.manual_import import ManualImportService

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import AlertScanResponse, AlertUpdateRequest, APIResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
logger = logging.getLogger(__name__)


async def _table_exists(pool, table_name: str) -> bool:
    try:
        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table_name,
        )
        return bool(exists)
    except Exception:
        return False


def _normalize_severity(value: str | None) -> str:
    mapping = {
        "critical": "high",
        "warning": "medium",
        "info": "low",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    return mapping.get((value or "").lower(), "low")


def _normalize_alert_row(row: dict) -> dict:
    recommended_action = row.get("recommended_action") or row.get("suggestion")
    alert_type = row.get("type") or row.get("alert_type") or "system"
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    suggestions = row.get("action_suggestions")
    if not isinstance(suggestions, list):
        suggestions = [recommended_action] if recommended_action else []
    return {
        **row,
        "type": alert_type,
        "severity": _normalize_severity(row.get("severity")),
        "title": row.get("title") or row.get("alert_type") or "系统预警",
        "description": row.get("description") or row.get("root_cause") or "",
        "recommended_action": recommended_action,
        "action_suggestions": suggestions,
        "metrics": metrics,
    }


def _db_severity(value: str | None) -> str:
    mapping = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "critical": "high",
        "warning": "medium",
        "info": "low",
    }
    return mapping.get((value or "").lower(), "low")


def _extract_collaboration_from_metrics(metrics: object) -> list[dict]:
    if not isinstance(metrics, dict):
        return []
    for key in ("collaboration_results", "orchestrated_actions", "agent_actions"):
        value = metrics.get(key)
        if isinstance(value, list):
            return value
    return []


def _matches_alert_for_collaboration(action: dict, alert_data: dict) -> bool:
    alert_id = str(alert_data.get("alert_id") or "")
    product_id = str(alert_data.get("product_id") or "")
    metric_anomaly_id = str((alert_data.get("metrics") or {}).get("anomaly_id") or "")
    action_anomaly_id = str(action.get("anomaly_id") or "")
    action_product_id = str(action.get("product_id") or "")

    if alert_id and action_anomaly_id and action_anomaly_id == alert_id:
        return True
    if metric_anomaly_id and action_anomaly_id and action_anomaly_id == metric_anomaly_id:
        return True
    return bool(product_id and action_product_id and action_product_id == product_id)


async def _extract_collaboration_from_scans(pool, alert_data: dict) -> list[dict]:
    try:
        rows = await pool.fetch(
            """
            SELECT result
            FROM alert_scans
            WHERE status = 'completed'
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
    except Exception as exc:
        logger.warning("Failed to query alert_scans for collaboration data: %s", exc)
        return []
    for row in rows:
        result = row.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                continue
        if not isinstance(result, dict):
            continue
        actions = result.get("orchestrated_actions")
        if not isinstance(actions, list):
            continue
        matched = [action for action in actions if isinstance(action, dict) and _matches_alert_for_collaboration(action, alert_data)]
        if matched:
            return matched
    return []


def _issue_type(issue_key: str) -> str:
    return {
        "stockout_but_selling": "stockout",
        "catalog_gaps": "catalog",
        "products_missing_price": "pricing",
        "order_amount_mismatch": "orders",
        "inventory_missing_cost": "inventory",
    }.get(issue_key, "data_quality")


def _build_manual_review_description(issue: dict, rows: list[dict]) -> str:
    base = issue.get("description") or ""
    if not rows:
        return base
    sample = rows[0]
    if issue.get("key") == "stockout_but_selling":
        name = sample.get("name") or sample.get("product_id") or "商品"
        sales = sample.get("monthly_sales") or 0
        return f"{base} 当前最高风险商品是 {name}，近 30 天销量 {sales}。"
    if issue.get("key") == "catalog_gaps":
        name = sample.get("name") or sample.get("sku_id") or "商品"
        return f"{base} 例如 {name} 已在业务数据出现，但主档未补齐。"
    if issue.get("key") == "products_missing_price":
        name = sample.get("name") or sample.get("product_id") or "商品"
        return f"{base} 例如 {name} 当前缺少零售价。"
    if issue.get("key") == "order_amount_mismatch":
        order_id = sample.get("order_id") or "订单"
        diff = sample.get("diff") or 0
        return f"{base} 例如 {order_id} 的差额达到 {diff}。"
    if issue.get("key") == "inventory_missing_cost":
        name = sample.get("product_name") or sample.get("sku_id") or "SKU"
        return f"{base} 例如 {name} 还没有成本价。"
    return base


def _build_manual_review_suggestions(issue: dict, rows: list[dict]) -> list[str]:
    suggestions = []
    recommended_action = issue.get("recommended_action")
    if recommended_action:
        suggestions.append(str(recommended_action))
    if issue.get("key") == "stockout_but_selling" and rows:
        names = [str(row.get("name") or row.get("product_id")) for row in rows[:3] if row.get("name") or row.get("product_id")]
        if names:
            suggestions.append(f"优先处理这批断货商品：{'、'.join(names)}")
    if issue.get("key") == "catalog_gaps" and rows:
        suggestions.append("明天导入前先补一版商品规格明细，避免继续生成孤儿商品。")
    if issue.get("key") == "order_amount_mismatch":
        suggestions.append("利润判断和客单价分析先排除异常订单，再补贴优惠拆分逻辑。")
    if issue.get("key") == "inventory_missing_cost":
        suggestions.append("先补热销和高库存 SKU 的成本价，先把毛利分析做准。")
    return suggestions[:3]


async def _generate_manual_review_alerts(pool, limit: int = 5) -> list[dict]:
    service = ManualImportService(pool)
    review = await service.get_review(limit=max(limit, 3))
    summary = review.get("summary") if isinstance(review, dict) else {}
    issues = review.get("issues") if isinstance(review, dict) else []
    tables = review.get("tables") if isinstance(review, dict) else {}
    if not isinstance(summary, dict) or not isinstance(issues, list) or not isinstance(tables, dict):
        return []

    alerts = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        count = int(issue.get("count") or 0)
        if count <= 0:
            continue
        issue_key = str(issue.get("key") or "")
        table_key = "missing_price" if issue_key == "products_missing_price" else issue_key
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        alerts.append(
            {
                "alert_id": f"manual_review_{issue_key}",
                "type": _issue_type(issue_key),
                "severity": _normalize_severity(issue.get("severity")),
                "title": issue.get("title") or "数据质量问题",
                "description": _build_manual_review_description(issue, rows),
                "product_id": rows[0].get("product_id") if rows and isinstance(rows[0], dict) else None,
                "status": "pending",
                "created_at": None,
                "resolved_at": None,
                "actionable": True,
                "recommended_action": issue.get("recommended_action") or "",
                "action_suggestions": _build_manual_review_suggestions(issue, rows),
                "metrics": {
                    "count": count,
                    "issue_key": issue_key,
                    "summary_snapshot": {
                        "products": int(summary.get("products") or 0),
                        "orders": int(summary.get("orders") or 0),
                        "inventory_rows": int(summary.get("inventory_rows") or 0),
                    },
                    "examples": rows[:3],
                },
            }
        )
    return alerts


async def _load_persisted_alerts(pool) -> list[dict]:
    if not await _table_exists(pool, "alerts"):
        return []
    try:
        rows = await pool.fetch("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 100")
    except Exception as exc:
        logger.error("Failed to query alerts table: %s", exc)
        return []
    return [_normalize_alert_row(dict(row)) for row in rows]


def _merge_alerts(generated: list[dict], persisted: list[dict]) -> list[dict]:
    persisted_by_id = {
        str(alert.get("alert_id") or ""): alert
        for alert in persisted
        if alert.get("alert_id")
    }
    merged = []
    seen = set()

    for alert in generated:
        alert_id = str(alert.get("alert_id") or "")
        if not alert_id:
            continue
        override = persisted_by_id.get(alert_id)
        if override:
            merged_alert = {
                **alert,
                **override,
                "type": override.get("type") or alert.get("type"),
                "severity": _normalize_severity(override.get("severity") or alert.get("severity")),
                "action_suggestions": override.get("action_suggestions") or alert.get("action_suggestions") or [],
                "recommended_action": override.get("recommended_action") or alert.get("recommended_action"),
            }
        else:
            merged_alert = alert
        merged.append(merged_alert)
        seen.add(alert_id)

    for alert in persisted:
        alert_id = str(alert.get("alert_id") or "")
        if not alert_id or alert_id in seen:
            continue
        merged.append(alert)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    merged.sort(
        key=lambda item: (
            0 if item.get("status") == "pending" else 1,
            severity_order.get(str(item.get("severity") or ""), 3),
            str(item.get("created_at") or ""),
        )
    )
    return merged


def _apply_alert_filters(
    alerts: list[dict],
    *,
    severity: str | None,
    status: str | None,
    product_id: str | None,
) -> list[dict]:
    filtered = alerts
    if severity:
        filtered = [alert for alert in filtered if alert.get("severity") == severity]
    if status:
        filtered = [alert for alert in filtered if alert.get("status") == status]
    if product_id:
        filtered = [alert for alert in filtered if str(alert.get("product_id") or "") == product_id]
    return filtered


def _estimate_alert_impact(alert: dict, historical_daily_revenue: float) -> dict:
    severity = _normalize_severity(alert.get("severity"))
    alert_type = str(alert.get("type") or "system").lower()
    description = str(alert.get("description") or "")

    explicit_amount = None
    amount_match = re.search(r"¥\s*([0-9]+(?:\.[0-9]+)?)", description)
    if amount_match:
        with __import__("contextlib").suppress(Exception):
            explicit_amount = float(amount_match.group(1))

    amount = explicit_amount
    if amount is None and historical_daily_revenue > 0:
        severity_factor = {"high": 0.22, "medium": 0.12, "low": 0.06}.get(severity, 0.06)
        type_factor = {
            "stockout": 1.0,
            "orders": 0.8,
            "performance": 0.7,
            "inventory": 0.6,
            "pricing": 0.55,
            "catalog": 0.45,
            "data_quality": 0.35,
            "sales": 0.3,
            "system": 0.25,
        }.get(alert_type, 0.3)
        amount = round(historical_daily_revenue * severity_factor * type_factor, 2)

    if amount is None or amount <= 0:
        return {
            "expected_impact_amount": None,
            "impact_type": None,
            "confidence": 0.45,
            "impact_reason": "缺少可用历史经营均值，暂无法估算潜在损失",
        }

    impact_type = "loss_avoid"
    if alert_type in {"system", "data_quality", "catalog"}:
        impact_type = "cost_save"

    confidence = {"high": 0.85, "medium": 0.72, "low": 0.58}.get(severity, 0.58)
    if explicit_amount is not None:
        confidence = min(0.95, confidence + 0.05)

    return {
        "expected_impact_amount": round(amount, 2),
        "impact_type": impact_type,
        "confidence": round(confidence, 2),
        "impact_reason": None,
    }


async def _generate_smart_alerts(pool) -> list[dict]:
    """Generate real-time alerts based on actual business data."""
    import contextlib
    import json
    from datetime import UTC, datetime

    from .dashboard import _extract_metric, _get_dataset_records, _parse_data_value

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = []
    data = None  # raw metrics data (used below)

    with contextlib.suppress(Exception):
        alerts.extend(await _generate_manual_review_alerts(pool, limit=5))

    # 1. Stock-out and performance alerts — prefer qnh_dataset_records, fallback raw
    store_records = await _get_dataset_records(pool, "store_rank")
    loss_amount = 0.0
    rate = 0.0
    refund_rate = 0.0

    historical_daily_revenue = 0.0
    if store_records:
        for rec in store_records:
            loss_amount += _parse_data_value(rec.get("stockout_loss_amt"))
        vals = [_parse_data_value(rec.get("overtime_ord_rate")) for rec in store_records]
        rate = (sum(vals) / len(vals) / 100) if vals else 0  # stored as percentage
        vals2 = [_parse_data_value(rec.get("stockout_refund_rate")) for rec in store_records]
        refund_rate = (sum(vals2) / len(vals2) / 100) if vals2 else 0
        sale_vals = [_parse_data_value(rec.get("sale_amt_gmv")) for rec in store_records]
        sale_vals = [v for v in sale_vals if v > 0]
        historical_daily_revenue = (sum(sale_vals) / len(sale_vals)) if sale_vals else 0.0
    else:
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                "SELECT raw_data FROM qnh_store_metrics_raw ORDER BY created_at DESC LIMIT 1"
            )
            if row and row["raw_data"]:
                data = row["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                loss_amount = _extract_metric(data, "stockout_loss_amt")
                rate = _extract_metric(data, "overtime_ord_rate")
                refund_rate = _extract_metric(data, "stockout_refund_rate")
                historical_daily_revenue = _extract_metric(data, "sale_amt_gmv")

    if loss_amount > 0:
        alerts.append(
            {
                "alert_id": f"stockout_loss_{int(loss_amount)}",
                "type": "stockout",
                "severity": "high",
                "title": "缺货损失警告",
                "description": f"缺货造成损失: ¥{loss_amount:.2f}，请及时补货",
                "product_id": None,
                "status": "pending",
                "created_at": now_str,
                "resolved_at": None,
                "actionable": True,
                "action_suggestions": [
                    f"立即补货损失最大的{min(3, int(loss_amount / 100))}个商品，预计3-5天到货",
                    f"联系供应商申请紧急发货，可考虑支付{loss_amount * 0.1:.0f}元加急费",
                ],
            }
        )

    if rate > 0.05:  # > 5%
        alerts.append(
            {
                "alert_id": f"overtime_rate_{int(rate * 100)}",
                "type": "performance",
                "severity": "high" if rate > 0.2 else "medium",
                "title": "超时订单率偏高",
                "description": f"超时订单率: {rate * 100:.1f}%，建议优化配送流程",
                "product_id": None,
                "status": "pending",
                "created_at": now_str,
                "resolved_at": None,
                "actionable": True,
                "action_suggestions": [
                    "增加备货量前3名热销商品，减少缺货等待时间",
                    f"联系美团配送优化路线，目标降至{max(3, rate * 100 - 5):.0f}%以下",
                ],
            }
        )

    if refund_rate > 0:
        alerts.append(
            {
                "alert_id": f"stockout_refund_{int(refund_rate * 10000)}",
                "type": "inventory",
                "severity": "medium",
                "title": "缺货退款提醒",
                "description": f"缺货退款率: {refund_rate * 100:.2f}%",
                "product_id": None,
                "status": "pending",
                "created_at": now_str,
                "resolved_at": None,
                "actionable": refund_rate > 0.05,
            }
        )

    # 2. Product alerts - low revenue products (filter out promotional items < ¥1)
    with contextlib.suppress(Exception):
        low_revenue_products = await pool.fetch(
            """SELECT product_id, name, retail_price FROM products
               WHERE status = 'active' AND retail_price BETWEEN 1 AND 10
               ORDER BY retail_price ASC LIMIT 3"""
        )
        for product in low_revenue_products:
            alerts.append(
                {
                    "alert_id": f"low_revenue_{product['product_id']}",
                    "type": "pricing",
                    "severity": "low",
                    "title": "低价商品提醒",
                    "description": f"商品 {product['name']} 售价偏低 (¥{product['retail_price']})",
                    "product_id": product["product_id"],
                    "status": "pending",
                    "created_at": "2026-03-01T06:00:00Z",
                    "resolved_at": None,
                    "actionable": True,
                }
            )

    # 3. High price alerts - products with unusually high prices (only if significantly higher than category average)
    with contextlib.suppress(Exception):
        high_price_products = await pool.fetch(
            """SELECT p.product_id, p.name, p.retail_price,
                      AVG(p2.retail_price) as category_avg_price
               FROM products p
               JOIN products p2 ON p.category = p2.category
               WHERE p.status = 'active' AND p.retail_price > 200
                     AND p2.status = 'active' AND p2.retail_price > 0
               GROUP BY p.product_id, p.name, p.retail_price
               HAVING p.retail_price > AVG(p2.retail_price) * 1.5
               ORDER BY p.retail_price / AVG(p2.retail_price) DESC
               LIMIT 2"""
        )
        for product in high_price_products:
            suggested_price = product["category_avg_price"] * 1.2  # 20% premium
            alerts.append(
                {
                    "alert_id": f"high_price_{product['product_id']}",
                    "type": "pricing",
                    "severity": "medium",
                    "title": "高价商品提醒",
                    "description": f"商品 {product['name']} 售价¥{product['retail_price']}，高于同类均价{product['retail_price'] / product['category_avg_price']:.1f}倍",
                    "product_id": product["product_id"],
                    "status": "pending",
                    "created_at": "2026-03-01T06:30:00Z",
                    "resolved_at": None,
                    "actionable": True,
                    "action_suggestions": [
                        f"考虑降价至¥{suggested_price:.0f}提升竞争力",
                        f"强化该商品卖点宣传，突出{int((product['retail_price'] / product['category_avg_price'] - 1) * 100)}%价差的价值理由",
                    ],
                }
            )

    # 4. Turnover anomaly alert from store metrics
    with contextlib.suppress(Exception):
        turnover_days = 0.0
        if store_records:
            vals = [_parse_data_value(rec.get("turnover_days_by_amount")) for rec in store_records]
            turnover_days = sum(vals) / len(vals) if vals else 0
        elif data:
            turnover_days = _extract_metric(data, "turnover_days_by_amount")
        if turnover_days > 60:
            alerts.append(
                {
                    "alert_id": f"high_turnover_{int(turnover_days)}",
                    "type": "inventory",
                    "severity": "high" if turnover_days > 90 else "medium",
                    "title": "库存周转天数过高",
                    "description": f"库存周转天数: {turnover_days:.0f}天，远超行业标准30天，资金占用严重",
                    "product_id": None,
                    "status": "pending",
                    "created_at": now_str,
                    "resolved_at": None,
                    "actionable": True,
                    "action_suggestions": [
                        f"推广滞销商品：设置{int((turnover_days - 30) / 10) * 5 + 10}%折扣促销",
                        f"暂停进货{int(turnover_days / 30)}个月，专注清仓现有库存",
                    ],
                }
            )

    # 5. Category concentration alert - too many products in one category
    with contextlib.suppress(Exception):
        top_cat = await pool.fetchrow(
            """SELECT category, COUNT(*)::int AS cnt FROM products
               WHERE status = 'active' AND category != ''
               GROUP BY category ORDER BY cnt DESC LIMIT 1"""
        )
        total = await pool.fetchval("SELECT COUNT(*) FROM products WHERE status = 'active'") or 1
        if top_cat and top_cat["cnt"] > total * 0.4:  # Raised threshold to 40% to reduce noise
            alerts.append(
                {
                    "alert_id": f"category_concentration_{top_cat['cnt']}",
                    "type": "sales",
                    "severity": "low",
                    "title": "品类集中度偏高",
                    "description": f"品类「{top_cat['category']}」占 {top_cat['cnt']}/{total} 个商品({top_cat['cnt'] * 100 // total}%)，建议丰富其他品类",
                    "product_id": None,
                    "status": "pending",
                    "created_at": now_str,
                    "resolved_at": None,
                    "actionable": True,
                }
            )

    # 6. System alerts (only show if actionable)
    product_count = await pool.fetchval("SELECT COUNT(*) FROM products") or 0
    if product_count < 50:  # Only alert if too few products (actionable)
        alerts.append(
            {
                "alert_id": "low_inventory_scale",
                "type": "system",
                "severity": "medium",
                "title": "商品数量不足",
                "description": f"当前仅有 {product_count} 个商品，建议增加商品丰富度",
                "product_id": None,
                "status": "pending",
                "created_at": now_str,
                "resolved_at": None,
                "actionable": True,
            }
        )

    # Sort alerts by severity (high -> medium -> low) and actionable status
    severity_order = {"high": 0, "medium": 1, "low": 2}
    deduped = []
    seen = set()
    for alert in alerts:
        alert_id = str(alert.get("alert_id") or "")
        if alert_id and alert_id in seen:
            continue
        if alert_id:
            seen.add(alert_id)
        deduped.append(alert)
    for alert in deduped:
        alert.update(_estimate_alert_impact(alert, historical_daily_revenue))

    deduped.sort(
        key=lambda x: (severity_order.get(x["severity"], 3), not x.get("actionable", False))
    )

    # Limit to top 10 alerts to reduce noise
    return deduped[:10]


# UNUSED: no frontend caller
@router.get("", response_model=APIResponse[list[dict]])
async def list_alerts(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    product_id: str | None = Query(None),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    persisted = await _load_persisted_alerts(pool)
    try:
        generated = await _generate_smart_alerts(pool)
    except Exception as exc:
        logger.error("Failed to generate smart alerts: %s", exc)
        generated = []

    merged = _merge_alerts(generated, persisted)
    return APIResponse(
        data=_apply_alert_filters(
            merged,
            severity=severity,
            status=status,
            product_id=product_id,
        )[:100]
    )


@router.get("/{alert_id}", response_model=APIResponse[dict])
async def get_alert(alert_id: str) -> APIResponse[dict]:
    from fastapi import HTTPException

    pool = pg.get_pool()
    row = None
    if await _table_exists(pool, "alerts"):
        try:
            row = await pool.fetchrow("SELECT * FROM alerts WHERE alert_id = $1", alert_id)
        except Exception as exc:
            logger.error("Failed to fetch alert %s: %s", alert_id, exc)
            raise HTTPException(status_code=500, detail="Failed to fetch alert") from exc
    if row:
        data = _normalize_alert_row(dict(row))
    else:
        generated = await _generate_smart_alerts(pool)
        match = next((item for item in generated if item.get("alert_id") == alert_id), None)
        if not match:
            raise NotFoundError("Alert", alert_id)
        data = match

    try:
        collaboration_results = _extract_collaboration_from_metrics(data.get("metrics"))
        if not collaboration_results:
            collaboration_results = await _extract_collaboration_from_scans(pool, data)
        if collaboration_results:
            data["collaboration_results"] = collaboration_results
    except Exception as exc:
        logger.warning("Failed to enrich alert %s with collaboration data: %s", alert_id, exc)

    return APIResponse(data=data)


@router.patch("/{alert_id}", response_model=APIResponse[dict])
async def update_alert(alert_id: str, body: AlertUpdateRequest) -> APIResponse[dict]:
    from fastapi import HTTPException

    pool = pg.get_pool()
    row = None
    alerts_table_exists = await _table_exists(pool, "alerts")
    if alerts_table_exists:
        try:
            row = await pool.fetchrow(
                """UPDATE alerts SET status = $1, resolved_at = CASE WHEN $1 = 'resolved' THEN NOW() ELSE resolved_at END
                   WHERE alert_id = $2 RETURNING *""",
                body.status,
                alert_id,
            )
        except Exception as exc:
            logger.error("Failed to update alert %s: %s", alert_id, exc)
            raise HTTPException(status_code=500, detail="Failed to update alert") from exc
    if not row:
        generated = await _generate_smart_alerts(pool)
        match = next((item for item in generated if item.get("alert_id") == alert_id), None)
        if not match:
            raise NotFoundError("Alert", alert_id)
        if not alerts_table_exists:
            return APIResponse(
                data={
                    **match,
                    "status": body.status,
                    "resolved_at": None if body.status != "resolved" else "virtual",
                }
            )
        try:
            row = await pool.fetchrow(
                """
                INSERT INTO alerts (
                    alert_id, product_id, alert_type, severity, detection_method,
                    metrics, title, description, recommended_action, status,
                    created_at, resolved_at
                )
                VALUES (
                    $1, $2, $3, $4, 'manual_review',
                    $5::jsonb, $6, $7, $8, $9,
                    NOW(), CASE WHEN $9 = 'resolved' THEN NOW() ELSE NULL END
                )
                ON CONFLICT (alert_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    resolved_at = EXCLUDED.resolved_at,
                    recommended_action = EXCLUDED.recommended_action,
                    metrics = EXCLUDED.metrics,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description
                RETURNING *
                """,
                alert_id,
                match.get("product_id"),
                match.get("type") or "system",
                _db_severity(match.get("severity")),
                json.dumps(match.get("metrics") or {}, ensure_ascii=False, default=str),
                match.get("title") or "系统预警",
                match.get("description") or "",
                match.get("recommended_action") or "",
                body.status,
            )
        except Exception as exc:
            logger.error("Failed to persist generated alert %s: %s", alert_id, exc)
            raise HTTPException(status_code=500, detail="Failed to persist alert status") from exc
    return APIResponse(data=_normalize_alert_row(dict(row)))


async def _run_alert_scan(task_id: str, orch: Orchestrator) -> None:
    import json
    import logging

    logger = logging.getLogger(__name__)
    try:
        pool = pg.get_pool()
        result = await orch.run_alert(db_pool=pool)
        # Store scan result
        await pool.execute(
            "INSERT INTO alert_scans (scan_id, status, result, created_at) VALUES ($1, 'completed', $2::jsonb, NOW())",
            task_id,
            json.dumps(result, default=str),
        )
        # 扫描完成后自动推送通知（飞书/微信/钉钉/Telegram）
        try:
            from src.services.notification import check_and_push_alerts

            push_result = await check_and_push_alerts(pool)
            logger.info("Alert scan %s: auto-push result: %s", task_id, push_result)
        except Exception as push_exc:
            logger.warning("Alert scan %s: auto-push failed: %s", task_id, push_exc)
    except Exception:
        logger.exception("Alert scan %s failed", task_id)


# UNUSED: no frontend caller
@router.post("/scan", response_model=APIResponse[AlertScanResponse])
async def trigger_scan(
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> APIResponse[AlertScanResponse]:
    task_id = gen_id("scan_")
    bg.add_task(_run_alert_scan, task_id, orch)
    return APIResponse(data=AlertScanResponse(task_id=task_id, message="Alert scan started"))


# UNUSED: no frontend caller
@router.post("/push", response_model=APIResponse[dict])
async def push_alerts() -> APIResponse[dict]:
    """手动触发告警推送（Telegram/Webhook）"""
    from fastapi import HTTPException

    from src.services.notification import check_and_push_alerts

    pool = pg.get_pool()
    try:
        result = await check_and_push_alerts(pool)
    except Exception as exc:
        logger.error("Failed to push alerts: %s", exc)
        raise HTTPException(status_code=500, detail=f"Alert push failed: {exc}") from exc
    return APIResponse(data=result)


@router.post("/test-push", response_model=APIResponse[dict])
async def test_push(
    message: str = "这是一条测试告警",
    severity: str = "medium",
) -> APIResponse[dict]:
    """手动测试通知推送（飞书/微信企业/钉钉/Telegram/Webhook）

    Query params:
      - message: 测试消息正文（默认: "这是一条测试告警"）
      - severity: 严重程度 critical|high|medium|low（默认: medium）

    返回各通道配置状态和推送结果。
    """

    from fastapi import HTTPException

    from src.services.notification import (
        DINGTALK_WEBHOOK_URL,
        FEISHU_WEBHOOK_URL,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
        WEBHOOK_URL,
        WECHAT_WEBHOOK_URL,
        send_alert,
    )

    channels_configured = {
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "webhook": bool(WEBHOOK_URL),
        "feishu": bool(FEISHU_WEBHOOK_URL),
        "wechat": bool(WECHAT_WEBHOOK_URL),
        "dingtalk": bool(DINGTALK_WEBHOOK_URL),
    }

    try:
        result = await send_alert("【测试】店铺预警系统", message, severity)
    except Exception as exc:
        logger.error("Test push failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Test push failed: {exc}") from exc

    return APIResponse(
        data={
            **result,
            "channels_configured": channels_configured,
            "tip": "如需启用某通道，请在环境变量中配置对应的 Webhook URL",
            "env_vars": {
                "feishu": "FEISHU_WEBHOOK_URL",
                "wechat": "WECHAT_WEBHOOK_URL",
                "dingtalk": "DINGTALK_WEBHOOK_URL",
                "telegram": "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID",
                "webhook": "ALERT_WEBHOOK_URL",
            },
        }
    )
