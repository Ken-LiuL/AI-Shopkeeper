"""Chat API endpoint for v1 compatibility - Business Advisor."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.db import postgres as pg_db
from src.db import redis as redis_db
from src.services.session_manager import SessionManager

from .schemas import APIResponse, ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


def _get_session_manager() -> SessionManager | None:
    r = redis_db.get_redis()
    if r is None:
        return None
    return SessionManager(r)


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(request: ChatRequest) -> APIResponse[ChatResponse]:
    """
    Chat endpoint for business advisor (upgraded from customer service).
    Provides business insights and actionable recommendations.
    """
    from src.agents.business_advisor.nodes import chat as advisor_chat

    # Use session_id from request or generate a default one
    if not hasattr(request, "session_id") or not request.session_id:
        request.session_id = "default-session"

    pool = pg_db.get_pool()
    sm = _get_session_manager()

    # Get conversation history
    history = []
    try:
        if sm is not None and await sm.session_exists(request.session_id):
            history = await sm.get_history(request.session_id, limit=10)
            await sm.add_message(request.session_id, "user", request.message)
        else:
            # In-memory fallback - create simple history
            logger.info(f"Using in-memory session for {request.session_id}")
    except Exception as e:
        logger.warning(f"Failed to load history: {e}")

    try:
        # Call business advisor
        result = await advisor_chat(
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
        try:
            if sm is not None:
                await sm.add_message(request.session_id, "assistant", reply)
        except Exception as e:
            logger.warning(f"Failed to store assistant message: {e}")

        return APIResponse(
            data=ChatResponse(
                session_id=request.session_id,
                reply=reply,
                intent=intent,
                sources=sources,
                needs_human=needs_human,
            )
        )

    except Exception as e:
        logger.error(f"Business advisor chat failed: {e}")
        return APIResponse(
            data=ChatResponse(
                session_id=request.session_id,
                reply="抱歉，业务分析系统暂时不可用。请稍后重试或联系技术支持。",
                intent="error",
                sources=[],
                needs_human=True,
            )
        )
