"""Customer service effect metrics — async write & query helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def record_cs_metric(
    pool,
    *,
    session_id: str,
    ai_reply_id: str | None = None,
    message_id: str | None = None,
    received_at: datetime,
    replied_at: datetime | None = None,
    intent: str | None = None,
    confidence: float | None = None,
    needs_human: bool = False,
    was_fast_path: bool = False,
    compliance_filtered: bool = False,
) -> None:
    """Asynchronously write one metrics row.

    Gracefully no-ops when *pool* is None (e.g. test environments).
    """
    if pool is None:
        return

    response_time_ms: int | None = None
    if replied_at is not None and received_at is not None:
        delta_ms = (replied_at - received_at).total_seconds() * 1000
        response_time_ms = max(0, int(delta_ms))

    try:
        await pool.execute(
            """
            INSERT INTO cs_metrics (
                session_id, message_id, ai_reply_id,
                received_at, replied_at, response_time_ms,
                intent, confidence,
                needs_human, was_fast_path, compliance_filtered,
                created_at
            ) VALUES (
                $1, $2, $3,
                $4, $5, $6,
                $7, $8,
                $9, $10, $11,
                NOW()
            )
            """,
            session_id,
            message_id,
            ai_reply_id,
            received_at,
            replied_at,
            response_time_ms,
            intent,
            confidence,
            needs_human,
            was_fast_path,
            compliance_filtered,
        )
    except Exception as exc:
        # Never propagate — metrics must not affect the main chat flow
        logger.warning("[cs_metrics] Failed to record metric: %s", exc)


async def get_cs_stats(pool, *, days: int = 7) -> dict:
    """Return aggregated customer service metrics for the past *days* days.

    Returns an empty/zero-filled dict when *pool* is None or the table
    does not yet exist.
    """
    _empty: dict = {
        "period_days": days,
        "total_messages": 0,
        "ai_handled": 0,
        "human_needed": 0,
        "ai_handle_rate": 0.0,
        "avg_response_ms": 0.0,
        "fast_path_rate": 0.0,
        "compliance_filter_rate": 0.0,
        "intent_distribution": {},
    }

    if pool is None:
        return _empty

    try:
        row = await pool.fetchrow(
            """
            SELECT
                COUNT(*)                                                          AS total_messages,
                COUNT(*) FILTER (WHERE needs_human = FALSE)                      AS ai_handled,
                COUNT(*) FILTER (WHERE needs_human = TRUE)                       AS human_needed,
                COALESCE(AVG(response_time_ms), 0)                               AS avg_response_ms,
                COALESCE(
                    COUNT(*) FILTER (WHERE was_fast_path = TRUE)::float
                    / NULLIF(COUNT(*), 0), 0
                )                                                                AS fast_path_rate,
                COALESCE(
                    COUNT(*) FILTER (WHERE compliance_filtered = TRUE)::float
                    / NULLIF(COUNT(*), 0), 0
                )                                                                AS compliance_filter_rate
            FROM cs_metrics
            WHERE created_at >= NOW() - ($1 || ' days')::interval
            """,
            str(days),
        )

        intent_rows = await pool.fetch(
            """
            SELECT intent, COUNT(*) AS cnt
            FROM cs_metrics
            WHERE created_at >= NOW() - ($1 || ' days')::interval
              AND intent IS NOT NULL
            GROUP BY intent
            ORDER BY cnt DESC
            """,
            str(days),
        )

        total = int(row["total_messages"] or 0)
        ai_handled = int(row["ai_handled"] or 0)
        human_needed = int(row["human_needed"] or 0)
        ai_handle_rate = round(ai_handled / total, 4) if total > 0 else 0.0

        return {
            "period_days": days,
            "total_messages": total,
            "ai_handled": ai_handled,
            "human_needed": human_needed,
            "ai_handle_rate": ai_handle_rate,
            "avg_response_ms": round(float(row["avg_response_ms"] or 0), 1),
            "fast_path_rate": round(float(row["fast_path_rate"] or 0), 4),
            "compliance_filter_rate": round(float(row["compliance_filter_rate"] or 0), 4),
            "intent_distribution": {r["intent"]: int(r["cnt"]) for r in intent_rows},
        }

    except Exception as exc:
        logger.warning("[cs_metrics] get_cs_stats failed (graceful): %s", exc)
        return _empty
