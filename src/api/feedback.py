"""Feedback API — 查看 AI 推荐反馈追踪数据及模型权重。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas import APIResponse
from src.db import postgres as pg

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)


async def _feedback_time_column(pool) -> str | None:
    """Support old prod schemas that used tracked_at before created_at."""
    column = await pool.fetchval(
        """
        SELECT CASE
            WHEN EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'feedback_tracking' AND column_name = 'created_at'
            ) THEN 'created_at'
            WHEN EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'feedback_tracking' AND column_name = 'tracked_at'
            ) THEN 'tracked_at'
            ELSE NULL
        END
        """
    )
    return str(column) if column else None


@router.get("/summary", response_model=APIResponse[dict])
async def get_feedback_summary() -> APIResponse:
    """返回最近的反馈追踪汇总（各类型数量 + 平均得分）。"""
    try:
        pool = pg.get_pool()
        time_column = await _feedback_time_column(pool)
        if not time_column:
            return APIResponse(success=True, data={"summary": [], "count": 0})
        rows = await pool.fetch(
            f"""
            SELECT
                tracking_type,
                COUNT(*) AS total,
                ROUND(AVG(performance_score)::numeric, 4) AS avg_score,
                MAX({time_column}) AS last_tracked_at
            FROM feedback_tracking
            WHERE {time_column} >= NOW() - INTERVAL '30 days'
            GROUP BY tracking_type
            ORDER BY tracking_type
            """
        )
        summary = [
            {
                "tracking_type": r["tracking_type"],
                "total": r["total"],
                "avg_score": float(r["avg_score"] or 0),
                "last_tracked_at": r["last_tracked_at"].isoformat() if r["last_tracked_at"] else None,
            }
            for r in rows
        ]
        return APIResponse(success=True, data={"summary": summary, "count": len(summary)})
    except Exception as exc:
        logger.exception("Failed to get feedback summary")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/selection/{run_id}", response_model=APIResponse[dict])
async def get_selection_feedback(run_id: str) -> APIResponse:
    """查看某次选品推荐的实际反馈效果。"""
    try:
        pool = pg.get_pool()
        time_column = await _feedback_time_column(pool)
        if not time_column:
            raise HTTPException(status_code=404, detail=f"No feedback found for run_id={run_id}")
        rows = await pool.fetch(
            f"""
            SELECT id, reference_id, outcome_data, performance_score, {time_column} AS tracked_at
            FROM feedback_tracking
            WHERE tracking_type = 'selection' AND reference_id = $1
            ORDER BY {time_column} DESC
            LIMIT 10
            """,
            run_id,
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"No feedback found for run_id={run_id}")

        records = [
            {
                "id": r["id"],
                "run_id": r["reference_id"],
                "outcome_data": r["outcome_data"],
                "performance_score": float(r["performance_score"] or 0),
                "tracked_at": r["tracked_at"].isoformat() if r["tracked_at"] else None,
            }
            for r in rows
        ]
        return APIResponse(success=True, data={"run_id": run_id, "records": records})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get selection feedback for run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/weights", response_model=APIResponse[dict])
async def get_model_weights() -> APIResponse:
    """查看当前 AI 模型权重。"""
    try:
        from src.learning.weight_learner import WeightLearner

        pool = pg.get_pool()
        table_exists = await pool.fetchval("SELECT to_regclass('public.learning_weights') IS NOT NULL")
        if not table_exists:
            return APIResponse(success=True, data={"weights": {}})
        learner = WeightLearner(pool=pool)
        weights = await learner.load_weights()
        return APIResponse(success=True, data={"weights": weights})
    except ImportError:
        return APIResponse(
            success=False,
            data={"weights": {}, "error": "WeightLearner not available"},
        )
    except Exception as exc:
        logger.exception("Failed to get model weights")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/track/selection/{run_id}", response_model=APIResponse[dict])
async def trigger_track_selection(run_id: str) -> APIResponse:
    """手动触发某次选品 run 的效果追踪。"""
    try:
        from src.services.feedback_loop import FeedbackLoopService

        feedback = FeedbackLoopService()
        result = await feedback.track_selection_outcome(run_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return APIResponse(success=True, data=result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to track selection outcome for run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
