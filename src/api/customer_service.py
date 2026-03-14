"""Customer Service Agent API routes."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import UTC

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

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
_mem_summaries: dict[str, str] = {}


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
        overflow = history[: len(history) - _MAX_HISTORY]
        _mem_update_summary(session_id, overflow)
        del history[: len(history) - _MAX_HISTORY]


def _mem_update_summary(session_id: str, messages: list[dict]) -> None:
    """Synchronously fold trimmed messages into a simple text summary."""
    lines = []
    for message in messages:
        role = "用户" if message.get("role") == "user" else "客服"
        content = (message.get("content") or "")[:100]
        lines.append(f"{role}：{content}")
    new_summary = "\n".join(lines)
    existing = _mem_summaries.get(session_id, "")
    combined = f"{existing}\n{new_summary}" if existing else new_summary
    if len(combined) > 2000:
        combined = combined[-2000:]
    _mem_summaries[session_id] = combined


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
        session_summary = await sm.get_summary(request.session_id)
        await sm.add_message(request.session_id, "user", request.message)
    else:
        use_redis = False
        history = _mem_ensure(request.session_id)[-20:]
        session_summary = _mem_summaries.get(request.session_id, "")
        _mem_add(request.session_id, "user", request.message)

    if session_summary:
        history = [{"role": "system", "content": f"【早期对话摘要】{session_summary}"}] + history

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
        error_code = result.get("error_code")
        error_detail = result.get("error_detail")

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
                error_code=error_code,
                error_detail=error_detail,
            )
        )
    finally:
        if use_redis:
            await sm.release_lock(request.session_id)


# ── Quick auto-reply (stateless) ──────────────────────────────


@router.post("/auto-reply", response_model=APIResponse[dict])
async def auto_reply(request: ChatRequest) -> APIResponse[dict]:
    """无需 session 的快速自动回复，用于接入美团客服消息（30秒内响应要求）。"""
    import asyncio
    import time

    start_ts = time.monotonic()
    # 美团要求 30 秒内回复，预留 5 秒余量，AI 调用限时 25 秒
    _timeout_seconds = 25.0

    try:
        from src.agents.customer_service.nodes import chat as cs_chat
        from src.db import postgres as pg_db

        pool = pg_db.get_pool()
        history: list[dict] = []
        if request.session_id and request.session_id != "auto-reply":
            sm = _get_session_manager()
            if sm is not None:
                try:
                    if await sm.session_exists(request.session_id):
                        history = await sm.get_history(request.session_id, limit=10)
                except Exception:
                    pass
            else:
                history = _mem_ensure(request.session_id)[-10:]

        result = await asyncio.wait_for(
            cs_chat(
                session_id=request.session_id or "auto-reply",
                message=request.message,
                pool=pool,
                conversation_history=history,
                images=getattr(request, "images", None),
            ),
            timeout=_timeout_seconds,
        )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        logger.info("Auto-reply completed in %.0fms", elapsed_ms)

        return APIResponse(
            data={
                "reply": result.get("reply", ""),
                "intent": result.get("intent"),
                "needs_human": result.get("needs_human", False),
                "response_ms": round(elapsed_ms),
            }
        )
    except TimeoutError:
        elapsed_ms = (time.monotonic() - start_ts) * 1000
        logger.error("Auto-reply timeout after %.0fms (limit=%ss)", elapsed_ms, _timeout_seconds)
        return APIResponse(
            data={
                "reply": "亲，稍等一下，我马上为您处理～如有紧急问题可联系人工客服 😊",
                "intent": "timeout",
                "needs_human": True,
                "response_ms": round(elapsed_ms),
            },
            message="自动回复超时，建议转人工",
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - start_ts) * 1000
        logger.error("Auto-reply failed after %.0fms: %s", elapsed_ms, e)
        return APIResponse(
            data={
                "reply": "抱歉，系统暂时无法处理您的消息，请稍后再试或联系人工客服。",
                "intent": "error",
                "needs_human": True,
                "response_ms": round(elapsed_ms),
            },
            message="自动回复失败，建议转人工",
        )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """流式客服回复（SSE），提供更快的首字响应体验。"""
    import json as _json

    from src.agents.customer_service.nodes import chat as cs_chat
    from src.db import postgres as pg_db

    sm = _get_session_manager()
    pool = pg_db.get_pool()

    if sm is not None and await sm.session_exists(request.session_id):
        if not await sm.acquire_lock(request.session_id, timeout=30):
            async def _busy():
                yield f"data: {_json.dumps({'type': 'error', 'message': 'Session is busy'})}\n\n"

            return StreamingResponse(_busy(), media_type="text/event-stream")
        use_redis = True
        history = await sm.get_history(request.session_id, limit=20)
        session_summary = await sm.get_summary(request.session_id)
        await sm.add_message(request.session_id, "user", request.message)
    else:
        use_redis = False
        history = _mem_ensure(request.session_id)[-20:]
        session_summary = _mem_summaries.get(request.session_id, "")
        _mem_add(request.session_id, "user", request.message)

    if session_summary:
        history = [{"role": "system", "content": f"【早期对话摘要】{session_summary}"}] + history

    async def _stream():
        try:
            result = await cs_chat(
                session_id=request.session_id,
                message=request.message,
                pool=pool,
                conversation_history=history,
                images=request.images,
            )

            reply = result.get("reply", "")
            chunk_size = 10
            for i in range(0, len(reply), chunk_size):
                chunk = reply[i:i + chunk_size]
                yield (
                    f"data: {_json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"
                )

            if use_redis:
                await sm.add_message(request.session_id, "assistant", reply)
            else:
                _mem_add(request.session_id, "assistant", reply)

            yield (
                "data: "
                f"{_json.dumps({'type': 'done', 'reply': reply, 'intent': result.get('intent'), 'needs_human': result.get('needs_human', False)}, ensure_ascii=False)}\n\n"
            )
        except Exception as e:
            logger.error("Stream chat failed: %s", e)
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if use_redis:
                await sm.release_lock(request.session_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")


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
        # Ensure extended feedback columns exist (safe idempotent migration)
        try:
            await pool.execute(
                """
                ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS action VARCHAR(20);
                ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS original_reply TEXT;
                ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS edited_reply TEXT;
                ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS actual_reply TEXT;
                """
            )
        except Exception:
            logger.debug("Extended feedback columns may already exist or ALTER failed (non-critical)")

        # Store feedback with extended fields
        try:
            await pool.execute(
                """
                INSERT INTO cs_feedback (session_id, message_id, rating, comment,
                                         action, original_reply, edited_reply, actual_reply,
                                         created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                request.session_id,
                request.message_id,
                request.rating,
                request.comment,
                request.action,
                request.original_reply,
                request.edited_reply,
                request.actual_reply,
            )
        except Exception:
            # Fallback: store basic fields only (columns may not exist yet)
            logger.warning("Extended feedback insert failed, falling back to basic fields")
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
    """Get customer service statistics (today's AI performance dashboard)."""
    from datetime import datetime

    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        raise AppError("Database connection unavailable", status_code=503)

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Try primary tables (cs_sessions / cs_messages / cs_feedback) ──
    total_sessions = 0
    today_sessions = 0
    avg_session_length = 0.0
    total_feedback = 0
    avg_rating = 0.0
    resolved_sessions = 0
    human_transfers = 0

    try:
        total_sessions = await pool.fetchval("SELECT COUNT(*) FROM cs_sessions") or 0
        today_sessions = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM cs_sessions WHERE created_at >= CURRENT_DATE"
            )
            or 0
        )
        avg_session_length = float(
            await pool.fetchval(
                """SELECT COALESCE(AVG(message_count), 0) FROM (
                    SELECT session_id, COUNT(*) as message_count
                    FROM cs_messages
                    GROUP BY session_id
                ) sub"""
            )
            or 0
        )
        total_feedback = await pool.fetchval("SELECT COUNT(*) FROM cs_feedback") or 0
        avg_rating = float(
            await pool.fetchval("SELECT COALESCE(AVG(rating), 0) FROM cs_feedback") or 0
        )
        resolved_sessions = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM cs_sessions WHERE status = 'completed'"
            )
            or 0
        )
        human_transfers = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM cs_sessions WHERE needs_human = true"
            )
            or 0
        )
    except Exception as e:
        logger.warning("Primary cs_sessions query failed: %s", e)

    resolution_rate = (resolved_sessions / max(total_sessions, 1)) * 100
    transfer_rate = (human_transfers / max(total_sessions, 1)) * 100

    # ── Today-specific metrics from cs_conversation_log ──────────────
    total_today: int = today_sessions
    human_transfers_today: int = 0
    auto_resolve_rate: float = 100.0

    try:
        total_today = int(
            await pool.fetchval(
                "SELECT COUNT(DISTINCT session_id) FROM cs_conversation_log WHERE created_at >= $1",
                today_start,
            )
            or 0
        )
        human_transfers_today = int(
            await pool.fetchval(
                "SELECT COUNT(DISTINCT session_id) FROM cs_conversation_log"
                " WHERE created_at >= $1 AND ai_response LIKE '%转人工%'",
                today_start,
            )
            or 0
        )
        auto_resolve_rate = round(
            (total_today - human_transfers_today) / max(total_today, 1) * 100, 1
        )
    except Exception as e:
        logger.debug("cs_conversation_log query skipped (table may not exist): %s", e)
        # Fall back to session-level estimates
        total_today = today_sessions
        human_transfers_today = int(
            round(human_transfers * (today_sessions / max(total_sessions, 1)))
        )
        auto_resolve_rate = round((1 - transfer_rate / 100) * 100, 1)

    # ── Average quality score from cs_reply_scores ────────────────────
    avg_score: float = 0.85  # sensible default

    try:
        fetched = await pool.fetchval(
            "SELECT AVG(overall) FROM cs_reply_scores WHERE created_at >= $1",
            today_start,
        )
        if fetched is not None:
            avg_score = round(float(fetched), 2)
    except Exception as e:
        logger.debug("cs_reply_scores query skipped: %s", e)
        # Derive from feedback rating (scale 0-5 → 0-1)
        if avg_rating:
            avg_score = round(min(avg_rating / 5.0, 1.0), 2)

    saved_cost = round((total_today - human_transfers_today) * 5, 2)

    return APIResponse(
        data={
            # ── Legacy snake_case fields (keep for backward compat) ──
            "total_sessions": total_sessions,
            "today_sessions": today_sessions,
            "avg_session_length": round(avg_session_length, 2),
            "total_feedback": total_feedback,
            "avg_rating": round(avg_rating, 2),
            "resolution_rate": round(resolution_rate, 2),
            "human_transfer_rate": round(transfer_rate, 2),
            # ── New camelCase fields for the CS workbench dashboard ──
            "totalChats": total_today,
            "autoResolveRate": auto_resolve_rate,
            "avgScore": avg_score,
            "humanTransfer": human_transfers_today,
            "savedCost": saved_cost,
        }
    )


@router.get("/stats-fallback", response_model=APIResponse[dict])
async def _get_stats_fallback_from_raw() -> APIResponse[dict]:
    """Internal: extract IM task counts from qnh_orders_raw when cs tables are absent."""
    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        return APIResponse(data={"totalChats": 0, "autoResolveRate": 0, "avgScore": 0.85, "humanTransfer": 0, "savedCost": 0})

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
        logger.warning("Fallback IM task extraction failed: %s", fallback_err)

    total = im_sessions + call_sessions
    return APIResponse(
        data={
            "total_sessions": total,
            "today_sessions": im_sessions,
            "pending_im_tasks": im_sessions,
            "pending_call_tasks": call_sessions,
            "avg_session_length": 0,
            "total_feedback": 0,
            "avg_rating": 0,
            "resolution_rate": 0,
            "human_transfer_rate": 0,
            "totalChats": total,
            "autoResolveRate": 0,
            "avgScore": 0.85,
            "humanTransfer": 0,
            "savedCost": 0,
            "note": "客服会话表未初始化，显示待处理任务数"
            if total > 0
            else "暂无客服数据",
        }
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
