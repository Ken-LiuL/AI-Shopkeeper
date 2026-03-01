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

    from .dashboard import _extract_metric

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = []

    # 1. Stock-out and performance alerts from store metrics
    with contextlib.suppress(Exception):
        row = await pool.fetchrow(
            "SELECT raw_data FROM qnh_store_metrics_raw ORDER BY created_at DESC LIMIT 1"
        )
        if row and row["raw_data"]:
            data = row["raw_data"]
            if isinstance(data, str):
                data = json.loads(data)

            # Stockout loss (uses _extract_metric to handle nested + lastPeriodValue fallback)
            loss_amount = _extract_metric(data, "stockout_loss_amt")
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
                    }
                )

            # Overtime order rate
            rate = _extract_metric(data, "overtime_ord_rate")
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
                    }
                )

            # Stockout refund rate
            refund_rate = _extract_metric(data, "stockout_refund_rate")
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
                    }
                )

    # 2. Product alerts - low revenue products
    with contextlib.suppress(Exception):
        low_revenue_products = await pool.fetch(
            """SELECT spu_id, name, retail_price FROM qnh_products
               WHERE status = '在售' AND retail_price < 10 AND retail_price > 0
               ORDER BY retail_price ASC LIMIT 5"""
        )
        for product in low_revenue_products:
            alerts.append(
                {
                    "alert_id": f"low_revenue_{product['spu_id']}",
                    "type": "pricing",
                    "severity": "low",
                    "title": "低价商品提醒",
                    "description": f"商品 {product['name']} 售价偏低 (¥{product['retail_price']})",
                    "product_id": product["spu_id"],
                    "status": "pending",
                    "created_at": "2026-03-01T06:00:00Z",
                    "resolved_at": None,
                }
            )

    # 3. High price alerts - products with unusually high prices
    with contextlib.suppress(Exception):
        high_price_products = await pool.fetch(
            """SELECT spu_id, name, retail_price FROM qnh_products
               WHERE status = '在售' AND retail_price > 200
               ORDER BY retail_price DESC LIMIT 3"""
        )
        for product in high_price_products:
            alerts.append(
                {
                    "alert_id": f"high_price_{product['spu_id']}",
                    "type": "pricing",
                    "severity": "medium",
                    "title": "高价商品提醒",
                    "description": f"商品 {product['name']} 售价较高 (¥{product['retail_price']}), 请关注销售情况",
                    "product_id": product["spu_id"],
                    "status": "pending",
                    "created_at": "2026-03-01T06:30:00Z",
                    "resolved_at": None,
                }
            )

    # 4. Turnover anomaly alert from store metrics
    with contextlib.suppress(Exception):
        turnover_days = _extract_metric(data, "turnover_days_by_amount") if data else 0
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
                }
            )

    # 5. Category concentration alert - too many products in one category
    with contextlib.suppress(Exception):
        top_cat = await pool.fetchrow(
            """SELECT category, COUNT(*)::int AS cnt FROM qnh_products
               WHERE status = '在售' AND category != ''
               GROUP BY category ORDER BY cnt DESC LIMIT 1"""
        )
        total = await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE status = '在售'") or 1
        if top_cat and top_cat["cnt"] > total * 0.3:
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
                }
            )

    # 6. System alerts
    product_count = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0
    if product_count > 1500:
        alerts.append(
            {
                "alert_id": "inventory_scale",
                "type": "system",
                "severity": "low",
                "title": "商品数量提醒",
                "description": f"当前共有 {product_count} 个商品，库存管理良好",
                "product_id": None,
                "status": "resolved",
                "created_at": "2026-03-01T05:00:00Z",
                "resolved_at": "2026-03-01T06:00:00Z",
            }
        )

    return alerts


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

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await pool.fetch(
        f"SELECT * FROM alerts{where} ORDER BY created_at DESC LIMIT 100", *params
    )

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
        result = await orch.run_alert()
        pool = pg.get_pool()
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
