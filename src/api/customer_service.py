"""Customer Service Agent API routes."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import UTC

from fastapi import APIRouter, Query

from src.db import redis as redis_db
from src.services.session_manager import SessionManager

from .errors import AppError, NotFoundError
from .schemas import (
    APIResponse,
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    FeedbackRequest,
    SessionHistory,
    SessionListItem,
)

router = APIRouter(prefix="/api/customer-service", tags=["customer_service"])
logger = logging.getLogger(__name__)

# ── In-memory session fallback (when Redis unavailable) ───────
_MAX_MEM_SESSIONS = 200
_MAX_HISTORY = 50
_mem_sessions: OrderedDict[str, list[dict]] = OrderedDict()


def _mem_ensure(session_id: str) -> list[dict]:
    """Get or create an in-memory session."""
    if session_id not in _mem_sessions:
        if len(_mem_sessions) >= _MAX_MEM_SESSIONS:
            _mem_sessions.popitem(last=False)
        _mem_sessions[session_id] = []
    return _mem_sessions[session_id]


def _mem_add(session_id: str, role: str, content: str) -> None:
    history = _mem_ensure(session_id)
    history.append({"role": role, "content": content})
    if len(history) > _MAX_HISTORY:
        del history[: len(history) - _MAX_HISTORY]


def _get_session_manager() -> SessionManager | None:
    r = redis_db.get_redis()
    if r is None:
        return None
    return SessionManager(r)


def _require_redis() -> SessionManager:
    sm = _get_session_manager()
    if sm is None:
        raise AppError("Customer service requires Redis (not configured)", status_code=503)
    return sm


# ── Create session ────────────────────────────────────────────


@router.post("/sessions", response_model=APIResponse[CreateSessionResponse])
async def create_session(
    request: CreateSessionRequest | None = None,
) -> APIResponse[CreateSessionResponse]:
    import uuid
    from datetime import datetime

    sm = _get_session_manager()
    req = request or CreateSessionRequest()

    if sm is not None:
        session_id, created_at = await sm.create_session(
            customer_id=req.customer_id,
            metadata=req.metadata,
        )
    else:
        # In-memory fallback
        session_id = f"mem-{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()
        _mem_ensure(session_id)

    return APIResponse(data=CreateSessionResponse(session_id=session_id, created_at=created_at))


# ── Chat ──────────────────────────────────────────────────────


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(
    request: ChatRequest,
) -> APIResponse[ChatResponse]:
    from src.agents.customer_service.nodes import chat as cs_chat
    from src.db import postgres as pg_db

    sm = _get_session_manager()
    pool = pg_db.get_pool()

    # Determine history source: Redis or in-memory fallback
    if sm is not None and await sm.session_exists(request.session_id):
        if not await sm.acquire_lock(request.session_id, timeout=30):
            raise AppError("Session is busy, please retry", status_code=429)
        use_redis = True
        history = await sm.get_history(request.session_id, limit=20)
        await sm.add_message(request.session_id, "user", request.message)
    else:
        use_redis = False
        history = _mem_ensure(request.session_id)[-20:]
        _mem_add(request.session_id, "user", request.message)

    try:
        # Call new simplified chat function
        result = await cs_chat(
            session_id=request.session_id,
            message=request.message,
            pool=pool,
            conversation_history=history,
            images=request.images,
        )

        reply = result.get("reply", "")
        intent = result.get("intent")
        sources = result.get("sources", [])
        needs_human = result.get("needs_human", False)

        # Store assistant message
        if use_redis:
            await sm.add_message(request.session_id, "assistant", reply)
        else:
            _mem_add(request.session_id, "assistant", reply)

        return APIResponse(
            data=ChatResponse(
                session_id=request.session_id,
                reply=reply,
                intent=intent,
                sources=sources,
                needs_human=needs_human,  # 添加新字段
            )
        )
    finally:
        if use_redis:
            await sm.release_lock(request.session_id)


# ── Quick auto-reply (stateless) ──────────────────────────────


@router.post("/auto-reply", response_model=APIResponse[dict])
async def auto_reply(request: ChatRequest) -> APIResponse[dict]:
    """无需 session 的快速自动回复，用于接入美团客服消息。"""
    try:
        from src.agents.customer_service.nodes import chat as cs_chat
        from src.db import postgres as pg_db

        pool = pg_db.get_pool()
        result = await cs_chat(
            session_id="auto-reply",
            message=request.message,
            pool=pool,
            conversation_history=[],
            images=getattr(request, "images", None),
        )
        return APIResponse(
            data={
                "reply": result.get("reply", ""),
                "intent": result.get("intent"),
                "needs_human": result.get("needs_human", False),
            }
        )
    except Exception as e:
        logger.error("Auto-reply failed: %s", e)
        return APIResponse(
            data={
                "reply": "抱歉，系统暂时无法处理您的消息，请稍后再试或联系人工客服。",
                "intent": "error",
                "needs_human": True,
            },
            message="自动回复失败，建议转人工",
        )


# ── List sessions ─────────────────────────────────────────────


@router.get("/sessions", response_model=APIResponse[list[SessionListItem]])
async def list_sessions(
    customer_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[SessionListItem]]:
    sm = _get_session_manager()
    if sm is None:
        return APIResponse(data=[])
    items = await sm.list_sessions(customer_id=customer_id, limit=limit)
    return APIResponse(data=[SessionListItem(**item) for item in items])


# ── Get session messages ──────────────────────────────────────


@router.get("/sessions/{session_id}/messages", response_model=APIResponse[SessionHistory])
async def get_session_messages(session_id: str) -> APIResponse[SessionHistory]:
    sm = _require_redis()
    if not await sm.session_exists(session_id):
        raise NotFoundError("Session", session_id)
    history = await sm.get_history(session_id, limit=200)
    return APIResponse(data=SessionHistory(session_id=session_id, messages=history))


# ── Delete session ────────────────────────────────────────────


@router.delete("/sessions/{session_id}", response_model=APIResponse[dict])
async def delete_session(session_id: str) -> APIResponse[dict]:
    sm = _require_redis()
    deleted = await sm.close_session(session_id)
    if not deleted:
        raise NotFoundError("Session", session_id)
    return APIResponse(data={"session_id": session_id, "deleted": True})


# ── Feedback ──────────────────────────────────────────────


@router.post("/feedback", response_model=APIResponse[dict])
async def submit_feedback(request: FeedbackRequest) -> APIResponse[dict]:
    """Submit user feedback for a customer service interaction."""
    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        raise AppError("Database connection unavailable", status_code=503)

    try:
        # Store feedback in database
        await pool.execute(
            """
            INSERT INTO cs_feedback (session_id, message_id, rating, comment, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            request.session_id,
            request.message_id,
            request.rating,
            request.comment,
        )

        return APIResponse(data={"submitted": True})

    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}")
        raise AppError("Failed to submit feedback", status_code=500) from e


# ── Analytics ─────────────────────────────────────────────


@router.get("/stats", response_model=APIResponse[dict])
async def get_stats() -> APIResponse[dict]:
    """Get customer service statistics."""
    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        raise AppError("Database connection unavailable", status_code=503)

    try:
        # Get session statistics
        total_sessions = await pool.fetchval("SELECT COUNT(*) FROM cs_sessions") or 0

        # Get today's sessions
        today_sessions = (
            await pool.fetchval("SELECT COUNT(*) FROM cs_sessions WHERE created_at >= CURRENT_DATE")
            or 0
        )

        # Get average session length (in messages)
        avg_session_length = (
            await pool.fetchval(
                """SELECT AVG(message_count) FROM (
                SELECT session_id, COUNT(*) as message_count
                FROM cs_messages
                GROUP BY session_id
            ) sub"""
            )
            or 0
        )

        # Get feedback statistics
        total_feedback = await pool.fetchval("SELECT COUNT(*) FROM cs_feedback") or 0
        avg_rating = await pool.fetchval("SELECT AVG(rating) FROM cs_feedback") or 0

        # Get resolution rate (estimated based on session completion)
        resolved_sessions = (
            await pool.fetchval("SELECT COUNT(*) FROM cs_sessions WHERE status = 'completed'") or 0
        )
        resolution_rate = (resolved_sessions / max(total_sessions, 1)) * 100

        # Get human transfer rate (estimated)
        human_transfers = (
            await pool.fetchval("SELECT COUNT(*) FROM cs_sessions WHERE needs_human = true") or 0
        )
        transfer_rate = (human_transfers / max(total_sessions, 1)) * 100

        return APIResponse(
            data={
                "total_sessions": total_sessions,
                "today_sessions": today_sessions,
                "avg_session_length": round(float(avg_session_length), 2),
                "total_feedback": total_feedback,
                "avg_rating": round(float(avg_rating), 2) if avg_rating else 0,
                "resolution_rate": round(resolution_rate, 2),
                "human_transfer_rate": round(transfer_rate, 2),
            }
        )

    except Exception as e:
        logger.error(f"Failed to get customer service stats: {e}")

        # Fallback: extract IM task data from qnh_orders_raw
        im_sessions = 0
        call_sessions = 0
        try:
            import json

            raw_row = await pool.fetchrow(
                "SELECT raw_data FROM qnh_orders_raw ORDER BY synced_at DESC LIMIT 1"
            )
            if raw_row and raw_row["raw_data"]:
                data = raw_row["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                if isinstance(data, dict):
                    im_sessions = data.get("upcomingIMTaskCount", 0)
                    call_sessions = data.get("upcomingCallTaskCount", 0)
        except Exception as fallback_err:
            logger.warning(f"Fallback IM task extraction failed: {fallback_err}")

        return APIResponse(
            data={
                "total_sessions": im_sessions + call_sessions,
                "today_sessions": im_sessions,
                "pending_im_tasks": im_sessions,
                "pending_call_tasks": call_sessions,
                "avg_session_length": 0,
                "total_feedback": 0,
                "avg_rating": 0,
                "resolution_rate": 0,
                "human_transfer_rate": 0,
                "note": "客服会话表未初始化，显示待处理任务数"
                if (im_sessions + call_sessions) > 0
                else "暂无客服数据",
            },
        )


@router.get("/analytics", response_model=APIResponse[dict])
async def get_analytics() -> APIResponse[dict]:
    """Get customer service analytics data."""
    from src.agents.customer_service.learning import get_analytics_summary
    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        raise AppError("Database connection unavailable", status_code=503)

    try:
        analytics_data = await get_analytics_summary(pool)
        return APIResponse(data=analytics_data)

    except Exception as e:
        logger.error(f"Failed to get analytics: {e}")
        raise AppError("Failed to get analytics", status_code=500) from e
