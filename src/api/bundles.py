"""Bundle Agent API routes."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import APIResponse, BundleGenerateRequest, BundleUpdateRequest, TaskCreatedResponse

router = APIRouter(prefix="/api/bundles", tags=["bundles"])
logger = logging.getLogger(__name__)


@router.get("/recommendations", response_model=APIResponse[list[dict]])
async def bundle_recommendations() -> APIResponse[list[dict]]:
    """智能套餐推荐 — 基于热销商品 + 品类互补生成 bundle 建议。"""
    from src.services.bundle_intelligence import generate_bundle_recommendations

    try:
        result = await generate_bundle_recommendations()
        bundles = result.get("bundles", [])
        return APIResponse(
            data=bundles,
            message=result.get("message", f"生成 {len(bundles)} 个套餐推荐"),
        )
    except Exception as e:
        logger.exception("Bundle recommendations failed")
        return APIResponse(data=[], message=f"推荐生成失败: {e}")


@router.get("/suggestions", response_model=APIResponse[list[dict]])
async def bundle_suggestions() -> APIResponse[list[dict]]:
    """套餐建议 — /recommendations 的别名"""
    return await bundle_recommendations()


@router.get("/{bundle_id}", response_model=APIResponse[dict])
async def get_bundle(bundle_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow("SELECT * FROM bundles WHERE bundle_id = $1", bundle_id)
    if not row:
        raise NotFoundError("Bundle", bundle_id)
    return APIResponse(data=dict(row))


@router.post("/{bundle_id}/activate", response_model=APIResponse[dict])
async def activate_bundle(bundle_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "UPDATE bundles SET status = 'active' WHERE bundle_id = $1 RETURNING *",
        bundle_id,
    )
    if not row:
        raise NotFoundError("Bundle", bundle_id)
    return APIResponse(data=dict(row), message="Bundle activated")


@router.post("/{bundle_id}/deactivate", response_model=APIResponse[dict])
async def deactivate_bundle(bundle_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "UPDATE bundles SET status = 'inactive' WHERE bundle_id = $1 RETURNING *",
        bundle_id,
    )
    if not row:
        raise NotFoundError("Bundle", bundle_id)
    return APIResponse(data=dict(row), message="Bundle deactivated")


@router.get("", response_model=APIResponse[list[dict]])
async def list_bundles() -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        "SELECT * FROM bundles WHERE status != 'deleted' ORDER BY created_at DESC"
    )
    if not rows:
        return APIResponse(data=[], message="功能待开通")
    return APIResponse(data=[dict(r) for r in rows])


async def _run_bundle_generate(
    task_id: str, request: BundleGenerateRequest, orch: Orchestrator
) -> None:
    try:
        kwargs = {k: v for k, v in request.model_dump().items() if v is not None}
        result = await orch.run_bundle(**kwargs)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE bundle_tasks SET status = 'completed', result = $1::jsonb, finished_at = NOW() WHERE task_id = $2",
            json.dumps(result, default=str),
            task_id,
        )
    except Exception:
        logger.exception("Bundle generate %s failed", task_id)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE bundle_tasks SET status = 'failed', finished_at = NOW() WHERE task_id = $1",
            task_id,
        )


@router.post("/generate", response_model=TaskCreatedResponse)
async def generate_bundles(
    request: BundleGenerateRequest,
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> TaskCreatedResponse:
    task_id = gen_id("bnd_")
    pool = pg.get_pool()
    await pool.execute(
        "INSERT INTO bundle_tasks (task_id, status, created_at) VALUES ($1, 'running', NOW())",
        task_id,
    )
    bg.add_task(_run_bundle_generate, task_id, request, orch)
    return TaskCreatedResponse(task_id=task_id, message="Bundle generation started")


@router.patch("/{bundle_id}", response_model=APIResponse[dict])
async def update_bundle(bundle_id: str, body: BundleUpdateRequest) -> APIResponse[dict]:
    pool = pg.get_pool()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise NotFoundError("Bundle", bundle_id)

    set_clauses = [f"{k} = ${i + 1}" for i, k in enumerate(updates)]
    params = list(updates.values()) + [bundle_id]
    row = await pool.fetchrow(
        f"UPDATE bundles SET {', '.join(set_clauses)} WHERE bundle_id = ${len(params)} RETURNING *",
        *params,
    )
    if not row:
        raise NotFoundError("Bundle", bundle_id)
    return APIResponse(data=dict(row))


@router.delete("/{bundle_id}", response_model=APIResponse[dict])
async def delete_bundle(bundle_id: str) -> APIResponse[dict]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        "UPDATE bundles SET status = 'deleted' WHERE bundle_id = $1 RETURNING *",
        bundle_id,
    )
    if not row:
        raise NotFoundError("Bundle", bundle_id)
    return APIResponse(data=dict(row), message="Bundle deleted")
