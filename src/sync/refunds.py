"""Refund Syncer — 退款/售后明细同步。

NOTE: API 路径为推断，需验证实际牵牛花接口。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class RefundSyncer(BaseSyncer):
    """同步退款/售后明细数据。

    API (推断，需验证):
      - POST /qnh-gw3/api/refund/list — 退款列表
      - POST /qnh-gw3/api/refund/detail — 退款详情
    """

    name = "refunds"
    full_sync_interval = timedelta(hours=24)

    LIST_API = "/qnh-gw3/api/refund/list"
    DETAIL_API = "/qnh-gw3/api/refund/detail"

    async def full_sync(self) -> SyncResult:
        end = datetime.now(CST)
        start = end - timedelta(days=90)
        return await self._sync_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        end = datetime.now(CST)
        return await self._sync_range(since, end, SyncMode.INCREMENTAL)

    async def _sync_range(self, start: datetime, end: datetime, mode: SyncMode) -> SyncResult:
        total = 0
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
                resp = await self.client.post(self.LIST_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                await self._upsert_refunds(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

            return SyncResult(syncer_name=self.name, mode=mode, success=True, records_synced=total)
        except Exception as e:
            return SyncResult(
                syncer_name=self.name, mode=mode, success=False, records_synced=total, error=str(e)
            )

    async def _upsert_refunds(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            refund_id = str(item.get("refundId", item.get("id", "")))
            if not refund_id:
                continue

            refund_time = self._parse_time(item.get("refundTime", item.get("createTime")))
            resolved_time = self._parse_time(item.get("resolvedTime", item.get("finishTime")))

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
                INSERT INTO qnh_refunds
                    (tenant_id, refund_id, order_id, channel, sku_id, sku_name,
                     refund_reason, refund_amount, refund_status,
                     refund_time, resolved_time, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                ON CONFLICT (refund_id) DO UPDATE SET
                    refund_status = EXCLUDED.refund_status,
                    resolved_time = EXCLUDED.resolved_time,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                refund_id,
                str(item.get("orderId", "")) or None,
                channel,
                str(item.get("skuId", "")) or None,
                item.get("skuName", item.get("productName", "")),
                item.get("refundReason", item.get("reason", "")),
                float(item.get("refundAmount", item.get("amount", 0))),
                item.get("refundStatus", item.get("status", "")),
                refund_time,
                resolved_time,
                json.dumps(item, ensure_ascii=False, default=str),
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
