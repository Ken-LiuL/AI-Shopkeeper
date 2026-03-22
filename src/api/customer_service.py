"""Customer Service Agent API routes."""

from __future__ import annotations

import logging
import os
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
    LogChatRequest,
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
_feedback_schema_checked = False


def _session_lock_wait_seconds() -> float:
    raw = os.getenv("CS_SESSION_LOCK_WAIT", "35")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 35.0


def _session_lock_ttl_seconds() -> int:
    raw = os.getenv("CS_SESSION_LOCK_TTL", "90")
    try:
        return max(10, int(float(raw)))
    except ValueError:
        return 90


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


async def _ensure_feedback_schema(pool) -> None:
    """Best-effort schema compatibility for feedback enrichment fields."""
    global _feedback_schema_checked
    if _feedback_schema_checked:
        return
    import contextlib

    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS ai_reply_id TEXT;"
        )
    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS action TEXT;"
        )
    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS original_reply TEXT;"
        )
    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS edited_reply TEXT;"
        )
    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS actual_reply TEXT;"
        )
    with contextlib.suppress(Exception):
        await pool.execute(
            "ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS correction_text TEXT;"
        )
    _feedback_schema_checked = True


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
    import time as _time
    _api_t0 = _time.time()

    from src.agents.customer_service.nodes import chat as cs_chat
    from src.db import postgres as pg_db

    sm = _get_session_manager()
    pool = pg_db.get_pool()
    session_id = (request.session_id or "").strip()
    if not session_id:
        raise AppError("session_id cannot be empty", status_code=400)
    use_redis = False
    lock_acquired = False

    # Determine history source: Redis (with auto-create) or in-memory fallback
    #
    # 关键修复：如果 session_id 在 Redis 中不存在，自动创建而不是降级到内存。
    # 之前的 bug：Chrome 扩展传来的 session_id 如果没提前 create_session，
    # 就会走 in-memory fallback，导致每次重启/部署丢失所有上下文。
    #
    if sm is not None:
        session_exists = await sm.session_exists(session_id)
        if not session_exists:
            # Auto-create session in Redis (idempotent)
            logger.info(f"[CS] Auto-creating Redis session for {session_id}")
            await sm.create_session_with_id(session_id)
        if not await sm.acquire_lock(
            session_id,
            timeout=_session_lock_ttl_seconds(),
            wait=_session_lock_wait_seconds(),
        ):
            raise AppError("Session is busy, please retry", status_code=429)
        use_redis = True
        lock_acquired = True
        try:
            history = await sm.get_history(session_id, limit=20)
            session_summary = await sm.get_summary(session_id)
            await sm.add_message(session_id, "user", request.message)
        except Exception:
            await sm.release_lock(session_id)
            lock_acquired = False
            raise
    else:
        history = _mem_ensure(session_id)[-20:]
        session_summary = _mem_summaries.get(session_id, "")
        _mem_add(session_id, "user", request.message)

    # 调试日志：记录传给 chat() 的 history 条数
    logger.info(
        f"[CS-DEBUG] chat() called: session_id={session_id!r}, "
        f"use_redis={use_redis}, history_len={len(history)}, "
        f"has_summary={bool(session_summary)}"
    )

    if session_summary:
        history = [{"role": "system", "content": f"【早期对话摘要】{session_summary}"}] + history

    try:
        _api_pre_chat = _time.time()
        logger.info(f"[CS-API-PERF] Pre-chat setup took {(_api_pre_chat - _api_t0)*1000:.0f}ms (session/history)")

        # Call new simplified chat function
        result = await cs_chat(
            session_id=session_id,
            message=request.message,
            pool=pool,
            conversation_history=history,
            images=request.images,
            customer_info=request.customer_info,
            order_context=request.order_context,
        )

        _api_post_chat = _time.time()
        logger.info(f"[CS-API-PERF] cs_chat() took {(_api_post_chat - _api_pre_chat)*1000:.0f}ms")

        reply = result.get("reply", "")
        ai_reply_id = result.get("ai_reply_id")
        intent = result.get("intent")
        sources = result.get("sources", [])
        needs_human = result.get("needs_human", False)
        error_code = result.get("error_code")
        error_detail = result.get("error_detail")

        # Store assistant message
        if use_redis:
            await sm.add_message(session_id, "assistant", reply)
        else:
            _mem_add(session_id, "assistant", reply)

        _api_end = _time.time()
        logger.info(
            f"[CS-API-PERF] ===== API Total: {(_api_end - _api_t0)*1000:.0f}ms ===== "
            f"(setup={(_api_pre_chat - _api_t0)*1000:.0f}ms, "
            f"chat={(_api_post_chat - _api_pre_chat)*1000:.0f}ms, "
            f"post={(_api_end - _api_post_chat)*1000:.0f}ms)"
        )
        return APIResponse(
            data=ChatResponse(
                session_id=session_id,
                reply=reply,
                ai_reply_id=ai_reply_id,
                intent=intent,
                sources=sources,
                needs_human=needs_human,  # 添加新字段
                error_code=error_code,
                error_detail=error_detail,
            )
        )
    finally:
        if lock_acquired:
            await sm.release_lock(session_id)


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
                customer_info=getattr(request, "customer_info", None),
                order_context=getattr(request, "order_context", None),
            ),
            timeout=_timeout_seconds,
        )

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        logger.info("Auto-reply completed in %.0fms", elapsed_ms)

        return APIResponse(
            data={
                "reply": result.get("reply", ""),
                "ai_reply_id": result.get("ai_reply_id"),
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
    import asyncio
    import contextlib
    import json as _json

    from src.agents.customer_service.nodes import chat as cs_chat
    from src.db import postgres as pg_db

    sm = _get_session_manager()
    pool = pg_db.get_pool()
    session_id = (request.session_id or "").strip()
    if not session_id:
        raise AppError("session_id cannot be empty", status_code=400)
    use_redis = False
    lock_acquired = False

    # 与 /chat 相同的 auto-create session 逻辑
    if sm is not None:
        if not await sm.session_exists(session_id):
            logger.info(f"[CS] Stream: auto-creating Redis session for {session_id}")
            await sm.create_session_with_id(session_id)
        if not await sm.acquire_lock(
            session_id,
            timeout=_session_lock_ttl_seconds(),
            wait=_session_lock_wait_seconds(),
        ):
            async def _busy():
                yield f"data: {_json.dumps({'type': 'error', 'message': 'Session is busy'})}\n\n"

            return StreamingResponse(_busy(), media_type="text/event-stream")
        use_redis = True
        lock_acquired = True
        try:
            history = await sm.get_history(session_id, limit=20)
            session_summary = await sm.get_summary(session_id)
            await sm.add_message(session_id, "user", request.message)
        except Exception:
            await sm.release_lock(session_id)
            lock_acquired = False
            raise
    else:
        history = _mem_ensure(session_id)[-20:]
        session_summary = _mem_summaries.get(session_id, "")
        _mem_add(session_id, "user", request.message)

    logger.info(
        f"[CS-DEBUG] stream() called: session_id={session_id!r}, "
        f"use_redis={use_redis}, history_len={len(history)}"
    )

    if session_summary:
        history = [{"role": "system", "content": f"【早期对话摘要】{session_summary}"}] + history

    async def _stream():
        nonlocal lock_acquired
        token_queue: asyncio.Queue[str | None] = asyncio.Queue()
        chat_result: dict | None = None
        chat_error: Exception | None = None

        async def _on_token(token: str) -> None:
            await token_queue.put(token)

        async def _run_chat() -> None:
            nonlocal chat_result, chat_error
            try:
                chat_result = await cs_chat(
                    session_id=session_id,
                    message=request.message,
                    pool=pool,
                    conversation_history=history,
                    images=request.images,
                    customer_info=request.customer_info,
                    order_context=request.order_context,
                    stream=True,
                    token_callback=_on_token,
                )
            except Exception as e:
                chat_error = e
            finally:
                await token_queue.put(None)

        runner = asyncio.create_task(_run_chat())
        streamed_parts: list[str] = []
        try:
            while True:
                token = await token_queue.get()
                if token is None:
                    break
                streamed_parts.append(token)
                yield f"data: {_json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            await runner
            if chat_error:
                raise chat_error

            result = chat_result or {}
            reply = result.get("reply") or "".join(streamed_parts)

            if use_redis:
                await sm.add_message(session_id, "assistant", reply)
            else:
                _mem_add(session_id, "assistant", reply)

            yield (
                "data: "
                f"{_json.dumps({'type': 'done', 'reply': reply, 'ai_reply_id': result.get('ai_reply_id'), 'intent': result.get('intent'), 'needs_human': result.get('needs_human', False)}, ensure_ascii=False)}\n\n"
            )
        except Exception as e:
            logger.error("Stream chat failed: %s", e)
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if not runner.done():
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner
            if lock_acquired:
                await sm.release_lock(session_id)
                lock_acquired = False

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
        await _ensure_feedback_schema(pool)
        # Store feedback with extended fields
        try:
            await pool.execute(
                """
                INSERT INTO cs_feedback (session_id, message_id, rating, comment,
                                         ai_reply_id, action, original_reply, edited_reply, actual_reply,
                                         correction_text, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                """,
                request.session_id,
                request.message_id,
                request.rating,
                request.comment,
                request.ai_reply_id,
                request.action,
                request.original_reply,
                request.edited_reply,
                request.actual_reply,
                request.correction_text,
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


# ── Chat Log Collection (聊天记录采集) ────────────────────


@router.post("/log-chat", response_model=APIResponse[dict])
async def log_chat(request: LogChatRequest) -> APIResponse[dict]:
    """
    接收扩展采集的聊天记录（客服真实回复 + 客户消息）。
    用于学习系统分析和优化。
    通过 content_hash (session_id + role + content 前200字) 去重。
    """
    import hashlib

    from src.db import postgres as pg_db

    pool = pg_db.get_pool()
    if not pool:
        return APIResponse(data={"logged": False, "reason": "no_db"})

    content_trimmed = (request.content or "")[:2000]
    if not content_trimmed.strip():
        return APIResponse(data={"logged": False, "reason": "empty_content"})

    # 生成去重 hash：session_id + role + content 前 200 字
    dedup_key = f"{request.session_id}|{request.role}|{content_trimmed[:200]}"
    content_hash = hashlib.md5(dedup_key.encode()).hexdigest()

    try:
        result = await pool.execute(
            """
            INSERT INTO cs_chat_log (session_id, message_id, role, content, content_hash, source_timestamp, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (content_hash) DO NOTHING
            """,
            request.session_id or "",
            request.message_id or "",
            request.role or "agent",
            content_trimmed,
            content_hash,
            request.timestamp or None,
        )

        # result = "INSERT 0 1" (inserted) or "INSERT 0 0" (duplicate skipped)
        inserted = result.endswith("1")
        if inserted:
            logger.debug(f"Chat log recorded: session={request.session_id}, role={request.role}")
        else:
            logger.debug(f"Chat log deduplicated: hash={content_hash[:8]}")

        return APIResponse(data={"logged": inserted, "deduplicated": not inserted})

    except Exception as e:
        logger.warning(f"Failed to log chat: {e}")
        return APIResponse(data={"logged": False, "reason": str(e)[:100]})


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
            await pool.fetchval(
                """
                SELECT COALESCE(
                    AVG(
                        CASE
                            WHEN rating = 'good' THEN 5.0
                            WHEN rating = 'bad' THEN 1.0
                            ELSE NULL
                        END
                    ),
                    0
                )
                FROM cs_feedback
                """
            )
            or 0
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

    # ── Intent distribution from cs_conversation_log ─────────────────
    intent_distribution: dict[str, int] = {}
    try:
        rows = await pool.fetch(
            "SELECT intent, COUNT(*) as cnt FROM cs_conversation_log"
            " WHERE created_at >= $1 AND intent IS NOT NULL"
            " GROUP BY intent ORDER BY cnt DESC LIMIT 10",
            today_start,
        )
        intent_distribution = {row["intent"]: int(row["cnt"]) for row in rows}
    except Exception as e:
        logger.debug("Intent distribution query skipped: %s", e)

    # ── Average response time (from cs_conversation_log duration or estimate) ──
    avg_response_ms: float = 0.0
    try:
        fetched = await pool.fetchval(
            "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000)"
            " FROM cs_conversation_log WHERE created_at >= $1",
            today_start,
        )
        if fetched is not None:
            avg_response_ms = round(float(fetched), 0)
    except Exception as e:
        logger.debug("Avg response time query skipped: %s", e)

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
            # ── P1-2: 新增看板字段 ──
            "intentDistribution": intent_distribution,
            "avgResponseMs": avg_response_ms,
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
