"""IM History Syncer — 客服IM会话与消息同步via neixin API。

使用 api.neixin.cn 的 IM 接口获取聊天历史。
NOTE: 部分参数格式为推断，需根据实际抓包验证。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult
from .qnh_client import (
    NEIXIN_CHAT_HISTORY,
    NEIXIN_PUB_CHATLIST,
)

logger = logging.getLogger(__name__)


class IMHistorySyncer(BaseSyncer):
    """同步客服IM会话历史。

    APIs (api.neixin.cn):
      - POST /msg/api/pub/v1/chatlist — 会话列表
      - POST /msg/api/pub/v1/chatlist/info — 会话详情
      - POST /msg/api/pub/v3/history/chat/range — 聊天历史（按时间范围）
    NOTE: 参数格式为推断，需根据实际抓包验证。
    """

    name = "im_history"
    full_sync_interval = timedelta(hours=24)

    async def full_sync(self) -> SyncResult:
        end = datetime.now(CST)
        start = end - timedelta(days=30)
        return await self._sync_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        end = datetime.now(CST)
        return await self._sync_range(since, end, SyncMode.INCREMENTAL)

    async def _sync_range(self, start: datetime, end: datetime, mode: SyncMode) -> SyncResult:
        total_sessions = 0
        total_messages = 0

        try:
            # 1. 获取会话列表 via neixin API
            # NOTE: 参数格式为推断，需抓包验证
            resp = await self.client.neixin_post(
                NEIXIN_PUB_CHATLIST,
                data={
                    "startTime": int(start.timestamp() * 1000),
                    "endTime": int(end.timestamp() * 1000),
                },
            )
            data = resp.get("data", {})
            sessions = data.get("list", data.get("chatlist", data.get("records", [])))

            if not sessions:
                return SyncResult(syncer_name=self.name, mode=mode, success=True, records_synced=0)

            for session in sessions:
                chat_id = str(
                    session.get("chatId", session.get("sessionId", session.get("id", "")))
                )
                if not chat_id:
                    continue

                try:
                    await self._upsert_session(chat_id, session)
                except Exception:
                    self.logger.error("Failed to upsert IM session %s", chat_id, exc_info=True)
                total_sessions += 1

                # 2. 拉取聊天历史 via neixin chat/range API
                try:
                    msg_resp = await self.client.neixin_post(
                        NEIXIN_CHAT_HISTORY,
                        data={
                            "chatId": chat_id,
                            "startTime": int(start.timestamp() * 1000),
                            "endTime": int(end.timestamp() * 1000),
                        },
                    )
                    msg_data = msg_resp.get("data", {})
                    messages = msg_data.get("messages", msg_data.get("list", []))
                    if messages:
                        await self._upsert_messages(chat_id, messages)
                        total_messages += len(messages)
                except Exception as e:
                    self.logger.warning(f"Failed to fetch messages for chat {chat_id}: {e}")

            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=True,
                records_synced=total_sessions,
                details={"messages_synced": total_messages},
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=False,
                records_synced=total_sessions,
                error=str(e),
            )

    async def _upsert_session(self, chat_id: str, item: dict[str, Any]) -> None:
        if not self.pool:
            return

        started_at = self._parse_time(item.get("startTime", item.get("createTime")))
        ended_at = self._parse_time(item.get("endTime"))

        channel = str(item.get("platform", item.get("channel", ""))).lower()
        if "meituan" in channel or "美团" in channel:
            channel = "meituan"
        elif "eleme" in channel or "饿了么" in channel:
            channel = "eleme"
        elif "jddj" in channel or "京东" in channel:
            channel = "jddj"
        else:
            channel = "unknown"

        await self.pool.execute(
            """
            INSERT INTO qnh_im_sessions
                (tenant_id, session_id, channel, customer_id, customer_name,
                 order_id, status, started_at, ended_at, message_count,
                 satisfaction, extra, synced_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                status = EXCLUDED.status,
                ended_at = EXCLUDED.ended_at,
                message_count = EXCLUDED.message_count,
                satisfaction = EXCLUDED.satisfaction,
                extra = EXCLUDED.extra,
                synced_at = NOW()
            """,
            self.client.tenant_id,
            chat_id,
            channel,
            str(item.get("customerId", "")) or None,
            item.get("customerName", item.get("userName", "")),
            str(item.get("orderId", "")) or None,
            item.get("status", ""),
            started_at,
            ended_at,
            int(item.get("messageCount", 0)),
            item.get("satisfaction") if item.get("satisfaction") else None,
            json.dumps(item, ensure_ascii=False, default=str),
        )

    async def _upsert_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        saved = 0
        failed = 0
        for msg in messages:
            msg_id = str(msg.get("messageId", msg.get("id", "")))
            if not msg_id:
                continue

            try:
                msg_time = self._parse_time(msg.get("time", msg.get("createTime")))

                await self.pool.execute(
                    """
                    INSERT INTO qnh_im_messages
                        (session_id, message_id, role, content, msg_time, msg_type, extra, synced_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    session_id,
                    msg_id,
                    msg.get("role", msg.get("sender", "customer")),
                    msg.get("content", msg.get("text", "")),
                    msg_time,
                    msg.get("msgType", msg.get("type", "text")),
                    json.dumps(msg, ensure_ascii=False, default=str),
                )
                saved += 1
            except Exception:
                logger.error("Failed to upsert IM message %s (session=%s)", msg_id, session_id, exc_info=True)
                failed += 1

        if failed:
            logger.warning("_upsert_messages session=%s: saved=%d, failed=%d", session_id, saved, failed)

    def _parse_time(self, val: Any) -> datetime | None:
        if val is None:
            return None
        if isinstance(val, int | float):
            return datetime.fromtimestamp(val / 1000 if val > 1e12 else val, tz=CST)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val)
            except Exception:
                return None
        return None
