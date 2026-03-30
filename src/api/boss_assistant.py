"""Boss Assistant API — 店主经营顾问对话接口。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.db import postgres as pg_db
from src.db import redis as redis_db
from src.services.session_manager import SessionManager

from .schemas import APIResponse, ChatRequest, ChatResponse

router = APIRouter(prefix="/api/boss", tags=["boss_assistant"])
logger = logging.getLogger(__name__)


def _get_session_manager() -> SessionManager | None:
    r = redis_db.get_redis()
    if r is None:
        return None
    return SessionManager(r)


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def boss_chat(request: ChatRequest) -> APIResponse[ChatResponse]:
    """店主助手对话 — 经营数据查询、分析建议、库存预警等。"""
    from src.agents.boss_assistant.nodes import boss_chat as _boss_chat

    if not request.session_id:
        request.session_id = "boss-default"

    pool = pg_db.get_pool()
    sm = _get_session_manager()

    # 加载/存储对话历史
    history: list[dict] = []
    try:
        if sm is not None and await sm.session_exists(request.session_id):
            history = await sm.get_history(request.session_id, limit=10)
            await sm.add_message(request.session_id, "user", request.message)
        else:
            logger.info("[BossAssistant] Using in-memory session for %s", request.session_id)
    except Exception as e:
        logger.warning("[BossAssistant] Failed to load history: %s", e)

    try:
        result = await _boss_chat(
            session_id=request.session_id,
            message=request.message,
            pool=pool,
            conversation_history=history,
        )

        reply = result.get("reply", "")
        intent = result.get("intent")
        sources = result.get("sources", [])
        needs_human = result.get("needs_human", False)

        # 保存助手回复
        try:
            if sm is not None:
                await sm.add_message(request.session_id, "assistant", reply)
        except Exception as e:
            logger.warning("[BossAssistant] Failed to store assistant message: %s", e)

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
        logger.error("[BossAssistant] Chat failed: %s", e)
        return APIResponse(
            data=ChatResponse(
                session_id=request.session_id,
                reply="抱歉，经营顾问系统暂时不可用，请稍后重试。",
                intent="error",
                sources=[],
                needs_human=False,
            )
        )


class AskRequest(BaseModel):
    """Simple ask endpoint — 接收自然语言问题，返回经营建议。"""

    question: str


class AskResponse(BaseModel):
    answer: str
    data: dict[str, Any] | None = None
    intent: str | None = None


@router.post("/ask", response_model=APIResponse[AskResponse])
async def boss_ask(request: AskRequest) -> APIResponse[AskResponse]:
    """自然语言查询经营数据 — POST /api/boss/ask。

    接收 { question: str }，调用 boss_assistant agent，返回 { answer: str, data?: any }。
    """
    from src.agents.boss_assistant.nodes import boss_chat as _boss_chat

    pool = pg_db.get_pool()
    session_id = "boss-ask"

    try:
        result = await _boss_chat(
            session_id=session_id,
            message=request.question,
            pool=pool,
            conversation_history=None,
        )
        return APIResponse(
            data=AskResponse(
                answer=result.get("reply", ""),
                data=result.get("context"),
                intent=result.get("intent"),
            )
        )
    except Exception as e:
        logger.error("[BossAssistant/ask] failed: %s", e)
        return APIResponse(
            data=AskResponse(
                answer="抱歉，经营分析系统暂时不可用，请稍后重试。",
                data=None,
                intent="error",
            )
        )


@router.get("/capabilities", response_model=APIResponse[list])
async def list_capabilities() -> APIResponse[list]:
    """返回 AI 店长助手的能力列表（用于前端快捷入口展示）。"""
    return APIResponse(
        data=[
            {"id": "sales_analysis", "name": "今日判断", "icon": "🧭", "example": "今天最该先处理什么"},
            {"id": "inventory", "name": "库存管理", "icon": "📦", "example": "哪些商品快断货了"},
            {"id": "pricing", "name": "价格复核", "icon": "💰", "example": "哪些商品的价格需要复核"},
            {"id": "selection", "name": "选品推荐", "icon": "🎯", "example": "最近适合上什么新品"},
            {"id": "alerts", "name": "预警处理", "icon": "🔔", "example": "有什么需要处理的预警"},
            {"id": "cs_management", "name": "客服管理", "icon": "💬", "example": "今天客服哪里最容易出错"},
        ]
    )
