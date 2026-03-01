"""Selection Agent API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends

from src.agents.orchestrator import Orchestrator
from src.db import postgres as pg

from .deps import gen_id, get_orchestrator
from .errors import NotFoundError
from .schemas import (
    APIResponse,
    SelectionRunDetail,
    SelectionRunRequest,
    SelectionRunSummary,
    TaskCreatedResponse,
)

router = APIRouter(prefix="/api/selection", tags=["selection"])
logger = logging.getLogger(__name__)


async def _run_selection(run_id: str, request: SelectionRunRequest, orch: Orchestrator) -> None:
    """Background task: execute selection agent and persist result."""
    try:
        input_data: dict[str, Any] = {}
        if request.keywords:
            input_data["keywords"] = request.keywords
        if request.categories:
            input_data["categories"] = request.categories

        result = await orch.run_selection(**input_data)

        pool = pg.get_pool()
        recommendations = result.get("recommendations", [])
        await pool.execute(
            """UPDATE selection_runs
               SET status = 'completed', result = $1::jsonb, result_count = $2, finished_at = NOW()
               WHERE run_id = $3""",
            __import__("json").dumps(result, default=str),
            len(recommendations),
            run_id,
        )
    except Exception:
        logger.exception("Selection run %s failed", run_id)
        pool = pg.get_pool()
        await pool.execute(
            "UPDATE selection_runs SET status = 'failed', finished_at = NOW() WHERE run_id = $1",
            run_id,
        )


@router.post("/run", response_model=TaskCreatedResponse)
async def trigger_selection(
    request: SelectionRunRequest,
    bg: BackgroundTasks,
    orch: Orchestrator = Depends(get_orchestrator),
) -> TaskCreatedResponse:
    run_id = gen_id("sel_")
    pool = pg.get_pool()
    await pool.execute(
        """INSERT INTO selection_runs (run_id, status, keywords, categories, created_at)
           VALUES ($1, 'running', $2, $3, NOW())""",
        run_id,
        request.keywords or [],
        request.categories or [],
    )
    bg.add_task(_run_selection, run_id, request, orch)
    return TaskCreatedResponse(task_id=run_id, message="Selection run started")


@router.get("/runs", response_model=APIResponse[list[SelectionRunSummary]])
async def list_runs() -> APIResponse[list[SelectionRunSummary]]:
    pool = pg.get_pool()
    rows = await pool.fetch(
        "SELECT run_id, status, keywords, categories, result_count, created_at FROM selection_runs ORDER BY created_at DESC LIMIT 50"
    )
    items = [SelectionRunSummary(**dict(r)) for r in rows]

    # If no runs exist, add helpful message
    if not items:
        return APIResponse(data=[], message="暂无选品运行记录")

    return APIResponse(data=items)


@router.get("/runs/{run_id}", response_model=APIResponse[SelectionRunDetail])
async def get_run(run_id: str) -> APIResponse[SelectionRunDetail]:
    pool = pg.get_pool()
    row = await pool.fetchrow("SELECT * FROM selection_runs WHERE run_id = $1", run_id)
    if not row:
        raise NotFoundError("SelectionRun", run_id)
    data = dict(row)
    result = data.pop("result", None) or {}
    detail = SelectionRunDetail(
        **{k: v for k, v in data.items() if k in SelectionRunDetail.model_fields},
        recommendations=result.get("recommendations", []),
        raw_state=result,
    )
    return APIResponse(data=detail)


@router.get("/recommendations", response_model=APIResponse[list[dict]])
async def get_recommendations() -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    row = await pool.fetchrow(
        """SELECT result FROM selection_runs
           WHERE status = 'completed' ORDER BY created_at DESC LIMIT 1"""
    )
    if row and row["result"]:
        import json

        result = json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]
        recommendations = result.get("recommendations", [])
        if recommendations:
            return APIResponse(data=recommendations)

    # Fallback: generate basic recommendations from product data
    import contextlib

    recs: list[dict] = []
    with contextlib.suppress(Exception):
        # High-margin products with good categories
        high_value = await pool.fetch(
            """SELECT spu_id, name, category, brand, retail_price
               FROM qnh_products
               WHERE status = '在售' AND retail_price > 100 AND category != ''
               ORDER BY retail_price DESC LIMIT 10"""
        )
        for p in high_value:
            recs.append(
                {
                    "product_id": p["spu_id"],
                    "name": p["name"],
                    "category": p.get("category", ""),
                    "brand": p.get("brand", ""),
                    "price": float(p["retail_price"]),
                    "reason": "高客单价商品，利润空间大",
                    "score": 0.85,
                }
            )

        # Low-price high-frequency candidates
        low_price = await pool.fetch(
            """SELECT spu_id, name, category, brand, retail_price
               FROM qnh_products
               WHERE status = '在售' AND retail_price BETWEEN 10 AND 50 AND category != ''
               ORDER BY retail_price ASC LIMIT 10"""
        )
        for p in low_price:
            recs.append(
                {
                    "product_id": p["spu_id"],
                    "name": p["name"],
                    "category": p.get("category", ""),
                    "brand": p.get("brand", ""),
                    "price": float(p["retail_price"]),
                    "reason": "低价引流商品，提升订单量",
                    "score": 0.75,
                }
            )

    if recs:
        return APIResponse(data=recs)
    return APIResponse(data=[], message="功能待开通")
