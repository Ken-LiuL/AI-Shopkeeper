"""Selection Agent API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

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
    try:
        pool = pg.get_pool()
        rows = await pool.fetch(
            "SELECT run_id, status, keywords, categories, result_count, created_at FROM selection_runs ORDER BY created_at DESC LIMIT 50"
        )
        items = [SelectionRunSummary(**dict(r)) for r in rows]

        # If no runs exist, add helpful message
        if not items:
            return APIResponse(data=[], message="暂无选品运行记录")

        return APIResponse(data=items)
    except Exception as exc:
        logger.error("Failed to list selection runs: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/runs/{run_id}", response_model=APIResponse[SelectionRunDetail])
async def get_run(run_id: str) -> APIResponse[SelectionRunDetail]:
    try:
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
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to get selection run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


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

    # Fallback: generate recommendations using continuous scoring algorithm
    import contextlib

    from src.services.selection_scoring import SelectionScoringService

    recs: list[dict] = []
    with contextlib.suppress(Exception):
        # Get diverse product samples for recommendation
        products = await pool.fetch(
            """SELECT product_id, name, category, brand, retail_price
               FROM products
               WHERE status = 'active'
                 AND retail_price > 0
                 AND name != ''
                 AND category != ''
               ORDER BY retail_price DESC, RANDOM()
               LIMIT 25"""
        )

        for p in products:
            product_data = {
                "product_id": p["product_id"],
                "spu_id": p["product_id"],
                "name": p["name"],
                "category": p.get("category", ""),
                "brand": p.get("brand", ""),
                "retail_price": float(p["retail_price"]),
            }

            # Calculate continuous score using new algorithm
            score, score_breakdown = await SelectionScoringService.calculate_comprehensive_score(
                product_data, pool
            )

            # Generate explanation
            explanation = await SelectionScoringService.generate_scoring_explanation(
                product_data, score_breakdown
            )

            # Risk assessment based on price and category
            price = product_data["retail_price"]
            category = product_data["category"]

            if price > 1000:
                risk_note = "高价值医疗设备，需要专业资质和培训，客户群体有限"
            elif price > 500:
                risk_note = "中高价位产品，建议小批量试销，关注回款周期"
            elif price > 100:
                risk_note = "中价位产品，适合常规销售，注意库存管理"
            elif price > 50:
                risk_note = "经济型产品，销售频次较高，需要稳定供应链"
            else:
                risk_note = "低价位商品，适合引流促销，但利润空间有限"

            # Add medical device specific warnings
            from src.services.medical_device_service import MedicalDeviceService

            is_medical = MedicalDeviceService.is_medical_device(category, product_data["name"])
            if is_medical:
                device_type = MedicalDeviceService.classify_medical_device_type(
                    product_data["name"], category
                )
                if device_type in ["二类器械", "三类器械"]:
                    risk_note += "；医疗器械需要相关资质和合规经营"

            recs.append(
                {
                    "product_id": p["product_id"],
                    "name": p["name"],
                    "category": category,
                    "brand": p.get("brand", ""),
                    "price": price,
                    "reason": explanation,
                    "risk_warning": risk_note,
                    "score": score,  # Now truly continuous
                    "data_source": f"多因子连续评分算法（价格:{score_breakdown['price_factor']:.3f}，利润:{score_breakdown['margin_factor']:.3f}，品类:{score_breakdown['category_factor']:.3f}，周转:{score_breakdown['turnover_factor']:.3f}，季节:{score_breakdown['seasonal_factor']:.3f}）",
                    "score_breakdown": score_breakdown,  # For debugging/analysis
                }
            )

    if recs:
        return APIResponse(data=recs)
    return APIResponse(data=[], message="功能待开通")
