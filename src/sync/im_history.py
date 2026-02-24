"""IM History Syncer — 客服IM会话与消息同步。

NOTE: API 路径为推断，需验证实际牵牛花接口。
同步后可选向量化存入知识库供语义检索。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class IMHistorySyncer(BaseSyncer):
    """同步客服IM会话历史。

    API (推断，需验证):
      - POST /qnh-gw3/api/im/session/list — 会话列表
      - POST /qnh-gw3/api/im/history — 会话消息历史
    """

    name = "im_history"
    full_sync_interval = timedelta(hours=24)

    SESSION_LIST_API = "/qnh-gw3/api/im/session/list"
    HISTORY_API = "/qnh-gw3/api/im/history"

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
        page = 1

        try:
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": 50,
                    "startTime": start.strftime("%Y-%m-%d"),
                    "endTime": end.strftime("%Y-%m-%d"),
                    "storeIds": self.client.poi_ids,
                }
                resp = await self.client.post(self.SESSION_LIST_API, data=payload)
                data = resp.get("data", {})
                sessions = data.get("list", data.get("records", []))

                if not sessions:
                    break

                for session in sessions:
                    session_id = str(session.get("sessionId", session.get("id", "")))
                    if not session_id:
                        continue

                    await self._upsert_session(session)
                    total_sessions += 1

                    # 拉取消息列表
                    try:
                        msg_resp = await self.client.post(
                            self.HISTORY_API,
                            data={
                                "tenantId": self.client.tenant_id,
                                "sessionId": session_id,
                            },
                        )
                        messages = msg_resp.get("data", {}).get(
                            "messages", msg_resp.get("data", {}).get("list", [])
                        )
                        if messages:
                            await self._upsert_messages(session_id, messages)
                            total_messages += len(messages)
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to fetch messages for session {session_id}: {e}"
                        )

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

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

    async def _upsert_session(self, item: dict[str, Any]) -> None:
        if not self.pool:
            return

        session_id = str(item.get("sessionId", item.get("id", "")))
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
            session_id,
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

        for msg in messages:
            msg_id = str(msg.get("messageId", msg.get("id", "")))
            if not msg_id:
                continue

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
