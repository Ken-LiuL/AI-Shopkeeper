"""Customer Service Agent API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.agents.orchestrator import Orchestrator
from src.db import redis as redis_db

from .deps import get_orchestrator
from .errors import NotFoundError
from .schemas import APIResponse, ChatRequest, ChatResponse, SessionHistory

router = APIRouter(prefix="/api/cs", tags=["customer_service"])

SESSION_PREFIX = "cs:session:"


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(
    request: ChatRequest,
    orch: Orchestrator = Depends(get_orchestrator),
) -> APIResponse[ChatResponse]:
    result = await orch.run_customer_service(
        user_message=request.message,
        conversation_history=request.conversation_history,
        session_id=request.session_id,
    )

    reply = result.get("final_response", result.get("response", ""))
    intent = result.get("intent", None)
    sources = result.get("sources", [])

    # Persist to Redis
    import json

    r = redis_db.get_redis()
    key = f"{SESSION_PREFIX}{request.session_id}"
    entry = json.dumps({"role": "user", "content": request.message})
    await r.rpush(key, entry)
    entry = json.dumps({"role": "assistant", "content": reply, "intent": intent})
    await r.rpush(key, entry)
    await r.expire(key, 86400 * 7)  # 7 days

    return APIResponse(
        data=ChatResponse(
            session_id=request.session_id,
            reply=reply,
            intent=intent,
            sources=sources,
        )
    )


@router.get("/sessions/{session_id}", response_model=APIResponse[SessionHistory])
async def get_session(session_id: str) -> APIResponse[SessionHistory]:
    import json

    r = redis_db.get_redis()
    key = f"{SESSION_PREFIX}{session_id}"
    raw = await r.lrange(key, 0, -1)
    if not raw:
        raise NotFoundError("Session", session_id)
    messages = [json.loads(m) for m in raw]
    return APIResponse(data=SessionHistory(session_id=session_id, messages=messages))
