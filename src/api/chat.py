"""Chat API endpoint for v1 compatibility."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from .customer_service import chat as cs_chat_endpoint
from .schemas import APIResponse, ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(request: ChatRequest) -> APIResponse[ChatResponse]:
    """
    Chat endpoint for v1 API compatibility.
    Forwards to the customer service chat implementation.
    """
    # Use session_id from request or generate a default one
    if not hasattr(request, "session_id") or not request.session_id:
        request.session_id = "default-session"

    # Forward to the customer service chat endpoint
    return await cs_chat_endpoint(request)
