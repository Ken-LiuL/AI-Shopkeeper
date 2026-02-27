"""Customer Service Agent API routes."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import UTC

from fastapi import APIRouter, Depends, Query

from src.agents.orchestrator import Orchestrator
from src.db import redis as redis_db
from src.services.session_manager import SessionManager

from .deps import get_orchestrator
from .errors import AppError, NotFoundError
from .schemas import (
    APIResponse,
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    CreateSessionResponse,
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
    orch: Orchestrator = Depends(get_orchestrator),
) -> APIResponse[ChatResponse]:
    sm = _get_session_manager()

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
        # Run agent
        result = await orch.run_customer_service(
            user_message=request.message,
            conversation_history=history,
            session_id=request.session_id,
        )

        # Extract reply
        reply_data = result.get("reply", {})
        reply = (
            reply_data.get("reply_text", "") if isinstance(reply_data, dict) else str(reply_data)
        )
        intent_data = result.get("intent", {})
        intent = intent_data.get("intent") if isinstance(intent_data, dict) else None
        sources = result.get("enriched_results", result.get("sources", []))

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
            )
        )
    finally:
        if use_redis:
            await sm.release_lock(request.session_id)


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
