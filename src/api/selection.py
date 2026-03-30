"""Selection Agent API routes."""

from __future__ import annotations

import logging
import math
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
        raise HTTPException(status_code=500, detail="Internal server error") from exc


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
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/recommendations", response_model=APIResponse[list[dict]])
async def get_recommendations() -> APIResponse[list[dict]]:
    pool = pg.get_pool()
    try:
        rows = await pool.fetch(
            """
            WITH knowledge_counts AS (
                SELECT product_id, COUNT(*) AS knowledge_count
                FROM product_knowledge
                GROUP BY product_id
            )
            SELECT
                p.product_id,
                p.name,
                COALESCE(p.category, '') AS category,
                COALESCE(p.brand, '') AS brand,
                COALESCE(p.retail_price, 0) AS retail_price,
                COALESCE(p.cost_price, 0) AS cost_price,
                COALESCE(p.monthly_sales, 0) AS monthly_sales,
                COALESCE(p.stock, 0) AS stock,
                COALESCE(k.knowledge_count, 0) AS knowledge_count
            FROM products p
            LEFT JOIN knowledge_counts k ON k.product_id = p.product_id
            WHERE p.status = 'active'
              AND COALESCE(p.retail_price, 0) > 0
              AND COALESCE(p.name, '') != ''
            ORDER BY COALESCE(p.monthly_sales, 0) DESC, COALESCE(p.stock, 0) DESC, p.updated_at DESC NULLS LAST
            LIMIT 50
            """
        )
    except Exception:
        rows = await pool.fetch(
            """
            SELECT
                p.product_id,
                p.name,
                COALESCE(p.category, '') AS category,
                COALESCE(p.brand, '') AS brand,
                COALESCE(p.retail_price, 0) AS retail_price,
                COALESCE(p.cost_price, 0) AS cost_price,
                COALESCE(p.monthly_sales, 0) AS monthly_sales,
                COALESCE(p.stock, 0) AS stock,
                0 AS knowledge_count
            FROM products p
            WHERE p.status = 'active'
              AND COALESCE(p.retail_price, 0) > 0
              AND COALESCE(p.name, '') != ''
            ORDER BY COALESCE(p.monthly_sales, 0) DESC, COALESCE(p.stock, 0) DESC, p.updated_at DESC NULLS LAST
            LIMIT 50
            """
        )

    recommendations: list[dict[str, Any]] = []
    for row in rows:
        monthly_sales = int(row["monthly_sales"] or 0)
        stock = int(row["stock"] or 0)
        price = float(row["retail_price"] or 0)
        cost = float(row["cost_price"] or 0)
        knowledge_count = int(row["knowledge_count"] or 0)

        profit_margin = round(((price - cost) / price * 100), 1) if price > 0 and cost > 0 else 0.0
        daily_sales = monthly_sales / 30 if monthly_sales > 0 else 0
        stock_days = round(stock / daily_sales, 1) if daily_sales > 0 else None

        demand_score = min(10.0, round(math.log1p(monthly_sales) / math.log(2.2), 1)) if monthly_sales > 0 else 0.5

        stock_score = 4.5
        if stock > 0 and stock_days is not None:
            if 7 <= stock_days <= 45:
                stock_score = 9.0
            elif stock_days < 7:
                stock_score = 6.5
            else:
                stock_score = 5.5
        elif stock > 0:
            stock_score = 7.0
        elif monthly_sales > 0:
            stock_score = 2.0
        else:
            stock_score = 4.0

        margin_score = min(10.0, round(profit_margin / 4.5, 1)) if profit_margin > 0 else 3.0
        knowledge_score = 9.0 if knowledge_count > 0 else 4.0

        recommendation_score = round(
            demand_score * 0.4 + stock_score * 0.25 + margin_score * 0.2 + knowledge_score * 0.15,
            1,
        )

        status = "recommended" if recommendation_score >= 7.5 else "considering"

        strengths: list[str] = []
        risks: list[str] = []
        data_source = ["订单销量", "库存", "商品主档"]
        if knowledge_count > 0:
            data_source.append("知识中心")

        if monthly_sales >= 30:
            strengths.append(f"近 30 天销量 {monthly_sales} 件")
        elif monthly_sales > 0:
            strengths.append(f"近 30 天有 {monthly_sales} 件销量")
        else:
            risks.append("近 30 天暂无销量")

        if stock > 0:
            if stock_days is not None:
                strengths.append(f"预计库存可售 {stock_days} 天")
            else:
                strengths.append(f"当前库存 {stock} 件")
        else:
            risks.append("当前库存为 0")

        if profit_margin >= 25:
            strengths.append(f"毛利率约 {profit_margin}%")
        elif cost > 0:
            risks.append(f"毛利率仅 {profit_margin}%")
        else:
            risks.append("缺少成本价，毛利判断不完整")

        if knowledge_count > 0:
            strengths.append("已有客服知识支撑")
        else:
            risks.append("缺少知识条目，客服与推荐支撑偏弱")

        recommendations.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": row["category"],
                "brand": row["brand"],
                "price": round(price, 2),
                "profit_margin": profit_margin,
                "demand_score": demand_score,
                "recommendation_score": recommendation_score,
                "monthly_sales": monthly_sales,
                "stock": stock,
                "stock_days": stock_days,
                "knowledge_count": knowledge_count,
                "knowledge_ready": knowledge_count > 0,
                "status": status,
                "reason": "；".join(strengths[:3]) if strengths else "当前数据不足，建议继续观察",
                "risk_warning": "；".join(risks[:3]) if risks else "",
                "score_breakdown": {
                    "销量": round(demand_score, 1),
                    "库存": round(stock_score, 1),
                    "毛利": round(margin_score, 1),
                    "知识": round(knowledge_score, 1),
                },
                "data_source": data_source,
            }
        )

    recommendations.sort(key=lambda item: item["recommendation_score"], reverse=True)

    if recommendations:
        return APIResponse(
            data=recommendations,
            message="基于商品、订单、库存和知识完整度生成重点运营候选",
        )
    return APIResponse(data=[], message="暂无可用于判断的商品数据")
