"""Session manager for customer service — Redis-backed session lifecycle."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis key prefixes
_SESSION_META = "cs:session:meta:"  # hash: customer_id, created_at, updated_at
_SESSION_MSGS = "cs:session:msgs:"  # list of JSON messages
_SESSION_SUMMARY = "cs:session:summary:"  # string: rolling summary
_SESSION_LOCK = "cs:session:lock:"  # distributed lock
_SESSION_INDEX = "cs:sessions"  # sorted set: session_id scored by updated_at
_CUSTOMER_INDEX = "cs:customer:"  # sorted set per customer_id

SESSION_TTL = 86400  # 24 hours


class SessionManager:
    """Encapsulates all Redis session operations for customer service."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self._r = redis

    # ── Create ────────────────────────────────────────────────

    async def create_session(
        self, customer_id: str | None = None, metadata: dict[str, Any] | None = None
    ) -> tuple[str, str]:
        """Create a new session. Returns (session_id, created_at)."""
        session_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()

        meta = {
            "customer_id": customer_id or "",
            "created_at": now,
            "updated_at": now,
            "message_count": "0",
            "metadata": json.dumps(metadata or {}, ensure_ascii=False),
        }
        meta_key = f"{_SESSION_META}{session_id}"
        await self._r.hset(meta_key, mapping=meta)
        await self._r.expire(meta_key, SESSION_TTL)

        # Index by time
        ts = datetime.now(UTC).timestamp()
        await self._r.zadd(_SESSION_INDEX, {session_id: ts})
        if customer_id:
            await self._r.zadd(f"{_CUSTOMER_INDEX}{customer_id}", {session_id: ts})

        logger.info("Created session %s (customer=%s)", session_id, customer_id)
        return session_id, now

    async def create_session_with_id(
        self, session_id: str, customer_id: str | None = None
    ) -> str:
        """Create a session with a specific ID (idempotent — skips if exists)."""
        meta_key = f"{_SESSION_META}{session_id}"
        if await self._r.exists(meta_key):
            return session_id  # Already exists, no-op

        now = datetime.now(UTC).isoformat()
        meta = {
            "customer_id": customer_id or "",
            "created_at": now,
            "updated_at": now,
            "message_count": "0",
            "metadata": "{}",
        }
        await self._r.hset(meta_key, mapping=meta)
        await self._r.expire(meta_key, SESSION_TTL)

        ts = datetime.now(UTC).timestamp()
        await self._r.zadd(_SESSION_INDEX, {session_id: ts})
        if customer_id:
            await self._r.zadd(f"{_CUSTOMER_INDEX}{customer_id}", {session_id: ts})

        logger.info("Auto-created session %s", session_id)
        return session_id

    # ── Messages ──────────────────────────────────────────────

    async def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return the last *limit* messages for a session."""
        key = f"{_SESSION_MSGS}{session_id}"
        raw = await self._r.lrange(key, -limit, -1)
        return [json.loads(m) for m in raw]

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message (user or assistant) and refresh TTL."""
        msg_key = f"{_SESSION_MSGS}{session_id}"
        meta_key = f"{_SESSION_META}{session_id}"
        now = datetime.now(UTC).isoformat()

        entry = json.dumps({"role": role, "content": content, "timestamp": now}, ensure_ascii=False)
        await self._r.rpush(msg_key, entry)
        await self._r.expire(msg_key, SESSION_TTL)

        # Update meta
        await self._r.hset(meta_key, mapping={"updated_at": now})
        await self._r.hincrby(meta_key, "message_count", 1)
        await self._r.expire(meta_key, SESSION_TTL)

        # Update index score
        ts = datetime.now(UTC).timestamp()
        await self._r.zadd(_SESSION_INDEX, {session_id: ts})

        # Rolling summary: refresh every 10 messages.
        msg_count = int(await self._r.hget(meta_key, "message_count") or 0)
        if msg_count > 0 and msg_count % 10 == 0:
            await self._update_rolling_summary(session_id)

    async def _update_rolling_summary(self, session_id: str) -> None:
        """Generate and store a rolling summary for earlier messages."""
        try:
            msg_key = f"{_SESSION_MSGS}{session_id}"
            raw_messages = await self._r.lrange(msg_key, 0, -7)
            if not raw_messages:
                return

            messages = [json.loads(message) for message in raw_messages]

            try:
                from src.agents.customer_service.nodes import _summarize_conversation

                summary = await _summarize_conversation(messages)
            except Exception as exc:
                logger.warning("Failed to import/use LLM summarizer, fallback to text: %s", exc)
                lines = []
                for message in messages[-10:]:
                    role = "用户" if message.get("role") == "user" else "客服"
                    content = (message.get("content") or "")[:100]
                    lines.append(f"{role}：{content}")
                summary = "\n".join(lines)

            if summary:
                summary_key = f"{_SESSION_SUMMARY}{session_id}"
                existing = await self._r.get(summary_key)
                if existing:
                    summary = f"{existing}\n{summary}"
                if len(summary) > 2000:
                    summary = summary[-2000:]
                await self._r.set(summary_key, summary, ex=SESSION_TTL)
                logger.info("Updated rolling summary for session %s", session_id)
        except Exception as exc:
            logger.warning("Failed to update rolling summary: %s", exc)

    async def get_summary(self, session_id: str) -> str:
        """Return the stored session summary."""
        summary_key = f"{_SESSION_SUMMARY}{session_id}"
        return (await self._r.get(summary_key)) or ""

    # ── Locking ───────────────────────────────────────────────

    async def acquire_lock(self, session_id: str, timeout: int = 30, wait: float = 0) -> bool:
        """Acquire a distributed lock for a session via SETNX.

        Args:
            session_id: Session to lock.
            timeout: Lock TTL in seconds.
            wait: Max seconds to wait for lock (0 = no wait, return immediately).
        Returns True if acquired."""
        import asyncio
        key = f"{_SESSION_LOCK}{session_id}"
        acquired = await self._r.set(key, "1", nx=True, ex=timeout)
        if acquired or wait <= 0:
            return bool(acquired)
        # Poll until lock is free or wait expires
        deadline = asyncio.get_event_loop().time() + wait
        interval = 0.3
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(interval)
            acquired = await self._r.set(key, "1", nx=True, ex=timeout)
            if acquired:
                return True
        return False

    async def release_lock(self, session_id: str) -> None:
        """Release the session lock."""
        key = f"{_SESSION_LOCK}{session_id}"
        await self._r.delete(key)

    # ── List / Close ──────────────────────────────────────────

    async def list_sessions(
        self, customer_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List recent sessions, optionally filtered by customer_id."""
        index_key = f"{_CUSTOMER_INDEX}{customer_id}" if customer_id else _SESSION_INDEX

        # Most recent first
        session_ids = await self._r.zrevrange(index_key, 0, limit - 1)
        results: list[dict[str, Any]] = []
        for sid in session_ids:
            meta = await self._r.hgetall(f"{_SESSION_META}{sid}")
            if not meta:
                continue
            # Get last message preview
            last_raw = await self._r.lindex(f"{_SESSION_MSGS}{sid}", -1)
            last_message = ""
            if last_raw:
                last_msg = json.loads(last_raw)
                last_message = last_msg.get("content", "")[:100]

            results.append(
                {
                    "session_id": sid,
                    "customer_id": meta.get("customer_id") or None,
                    "last_message": last_message,
                    "message_count": int(meta.get("message_count", 0)),
                    "created_at": meta.get("created_at", ""),
                    "updated_at": meta.get("updated_at", ""),
                }
            )
        return results

    async def close_session(self, session_id: str) -> bool:
        """Delete all data for a session. Returns True if session existed."""
        meta_key = f"{_SESSION_META}{session_id}"
        meta = await self._r.hgetall(meta_key)
        if not meta:
            return False

        customer_id = meta.get("customer_id")
        pipe = self._r.pipeline()
        pipe.delete(meta_key)
        pipe.delete(f"{_SESSION_MSGS}{session_id}")
        pipe.delete(f"{_SESSION_SUMMARY}{session_id}")
        pipe.delete(f"{_SESSION_LOCK}{session_id}")
        pipe.zrem(_SESSION_INDEX, session_id)
        if customer_id:
            pipe.zrem(f"{_CUSTOMER_INDEX}{customer_id}", session_id)
        await pipe.execute()
        logger.info("Closed session %s", session_id)
        return True

    async def session_exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        return bool(await self._r.exists(f"{_SESSION_META}{session_id}"))
