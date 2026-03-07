"""Alert Agent API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import AlertScanResponse, AlertUpdateRequest, APIResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
logger = logging.getLogger(__name__)


async def _generate_smart_alerts(pool) -> list[dict]:
    """Generate real-time alerts based on actual business data."""
    import contextlib
    import json
    from datetime import UTC, datetime

    from .dashboard import _extract_metric, _get_dataset_records, _parse_data_value

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = []
    data = None  # raw metrics data (used below)

    # 1. Stock-out and performance alerts — prefer qnh_dataset_records, fallback raw
    store_records = await _get_dataset_records(pool, "store_rank")
    loss_amount = 0.0
    rate = 0.0
    refund_rate = 0.0

    if store_records:
        for rec in store_records:
            loss_amount += _parse_data_value(rec.get("stockout_loss_amt"))
        vals = [_parse_data_value(rec.get("overtime_ord_rate")) for rec in store_records]
        rate = (sum(vals) / len(vals) / 100) if vals else 0  # stored as percentage
        vals2 = [_parse_data_value(rec.get("stockout_refund_rate")) for rec in store_records]
        refund_rate = (sum(vals2) / len(vals2) / 100) if vals2 else 0
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
    alerts.sort(
        key=lambda x: (severity_order.get(x["severity"], 3), not x.get("actionable", False))
    )

    # Limit to top 10 alerts to reduce noise
    return alerts[:10]


@router.get("", response_model=APIResponse[list[dict]])
async def list_alerts(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    product_id: str | None = Query(None),
) -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    conditions: list[str] = []
    params: list[str] = []
    idx = 1
    if severity:
        conditions.append(f"severity = ${idx}")
        params.append(severity)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if product_id:
        conditions.append(f"product_id = ${idx}")
        params.append(product_id)
        idx += 1

    query = "SELECT * FROM alerts"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT 100"

    rows = await pool.fetch(query, *params)

    # If no structured alerts exist, generate smart alerts based on real data
    if not rows:
        logger.info("No structured alerts found, generating smart alerts from business data")
        smart_alerts = await _generate_smart_alerts(pool)

        # Apply filters to generated alerts
        filtered_alerts = smart_alerts
        if severity:
            filtered_alerts = [a for a in filtered_alerts if a.get("severity") == severity]
        if status:
            filtered_alerts = [a for a in filtered_alerts if a.get("status") == status]
        if product_id:
            filtered_alerts = [a for a in filtered_alerts if a.get("product_id") == product_id]

        return APIResponse(data=filtered_alerts)

    return APIResponse(data=[dict(r) for r in rows])


@router.get("/{alert_id}", response_model=APIResponse[dict])
async def get_alert(alert_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow("SELECT * FROM alerts WHERE alert_id = $1", alert_id)
    if not row:
        raise NotFoundError("Alert", alert_id)
    return APIResponse(data=dict(row))


@router.patch("/{alert_id}", response_model=APIResponse[dict])
async def update_alert(alert_id: str, body: AlertUpdateRequest) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        """UPDATE alerts SET status = $1, resolved_at = CASE WHEN $1 = 'resolved' THEN NOW() ELSE resolved_at END
           WHERE alert_id = $2 RETURNING *""",
        body.status,
        alert_id,
    )
    if not row:
        raise NotFoundError("Alert", alert_id)
    return APIResponse(data=dict(row))


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
    except Exception:
        logger.exception("Alert scan %s failed", task_id)


@router.post("/scan", response_model=APIResponse[AlertScanResponse])
async def trigger_scan(
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> APIResponse[AlertScanResponse]:
    task_id = gen_id("scan_")
    bg.add_task(_run_alert_scan, task_id, orch)
    return APIResponse(data=AlertScanResponse(task_id=task_id, message="Alert scan started"))


@router.post("/push", response_model=APIResponse[dict])
async def push_alerts() -> APIResponse[dict]:
    """手动触发告警推送（Telegram/Webhook）"""
    from src.services.notification import check_and_push_alerts
    pool = pg.get_pool()
    result = await check_and_push_alerts(pool)
    return APIResponse(data=result)


@router.post("/test-push", response_model=APIResponse[dict])
async def test_push(message: str = "这是一条测试告警") -> APIResponse[dict]:
    """测试推送通道"""
    from src.services.notification import send_alert
    result = await send_alert("测试告警", message, "medium")
    return APIResponse(data=result)
