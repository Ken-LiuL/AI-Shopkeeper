"""Alert Agent API routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import AlertScanResponse, AlertUpdateRequest, APIResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


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
