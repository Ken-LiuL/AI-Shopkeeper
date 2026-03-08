"""LLM usage metrics API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
logger = logging.getLogger(__name__)


@router.get("/llm", response_model=APIResponse[dict])
async def llm_metrics(
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
) -> APIResponse[dict]:
    """Return LLM usage statistics: total tokens, cost, breakdown by model."""
    try:
        return await _llm_metrics_impl(days)
    except Exception as e:
        logger.error("Failed to get LLM metrics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get LLM metrics")


async def _llm_metrics_impl(days: int) -> APIResponse[dict]:
    pool = pg.get_pool()

    # Overall totals
    totals = await pool.fetchrow(
        """SELECT COALESCE(SUM(input_tokens), 0)::bigint AS total_input_tokens,
                  COALESCE(SUM(output_tokens), 0)::bigint AS total_output_tokens,
                  COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
                  COUNT(*)::int AS total_requests
           FROM llm_usage
           WHERE created_at >= NOW() - make_interval(days => $1)""",
        days,
    )

    # Per-model breakdown
    by_model = await pool.fetch(
        """SELECT model,
                  COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                  COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd,
                  COUNT(*)::int AS requests
           FROM llm_usage
           WHERE created_at >= NOW() - make_interval(days => $1)
           GROUP BY model ORDER BY cost_usd DESC""",
        days,
    )

    # Per-agent breakdown
    by_agent = await pool.fetch(
        """SELECT agent_type,
                  COALESCE(SUM(input_tokens), 0)::bigint AS input_tokens,
                  COALESCE(SUM(output_tokens), 0)::bigint AS output_tokens,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd,
                  COUNT(*)::int AS requests
           FROM llm_usage
           WHERE created_at >= NOW() - make_interval(days => $1)
                 AND agent_type IS NOT NULL
           GROUP BY agent_type ORDER BY cost_usd DESC""",
        days,
    )

    # Daily trend
    daily = await pool.fetch(
        """SELECT created_at::date AS date,
                  COALESCE(SUM(input_tokens + output_tokens), 0)::bigint AS tokens,
                  COALESCE(SUM(cost_usd), 0) AS cost_usd,
                  COUNT(*)::int AS requests
           FROM llm_usage
           WHERE created_at >= NOW() - make_interval(days => $1)
           GROUP BY created_at::date ORDER BY date""",
        days,
    )

    return APIResponse(
        data={
            "period_days": days,
            "total_input_tokens": totals["total_input_tokens"],
            "total_output_tokens": totals["total_output_tokens"],
            "total_cost_usd": float(totals["total_cost_usd"]),
            "total_requests": totals["total_requests"],
            "by_model": [dict(r) for r in by_model],
            "by_agent": [dict(r) for r in by_agent],
            "daily_trend": [dict(r) for r in daily],
        }
    )
