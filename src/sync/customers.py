"""Customer Syncer — 消费排行via goldengateway。

NOTE: goldengateway module 名称为推断，需根据实际抓包验证。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class CustomerSyncer(BaseSyncer):
    """同步客户画像与消费排行数据。

    API: POST /goldengateway/empower/generic/table/query (module=customerRank)
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "customers"
    full_sync_interval = timedelta(hours=24)

    # 推断的 goldengateway module 名，需验证
    VIEW_CODE = "customer_consume_rank_table_view_new"

    async def full_sync(self) -> SyncResult:
        return await self._sync_customers(SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        return await self._sync_customers(SyncMode.INCREMENTAL, since=since)

    async def _sync_customers(self, mode: SyncMode, since: datetime | None = None) -> SyncResult:
        total = 0
        page = 1

        try:
            while True:
                extra: dict[str, Any] = {
                    "sortBy": "totalAmount",
                    "sortOrder": "desc",
                }
                resp = await self.client.golden_query(
                    view_code=self.VIEW_CODE,
                    start_date=since.strftime("%Y-%m-%d") if since else None,
                    page=page,
                    page_size=50,
                    extra=extra,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

                if not items:
                    break

                await self._upsert_customers(items)
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

    async def _upsert_customers(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            cid = str(item.get("customerId", item.get("id", "")))
            if not cid:
                continue

            last_order = self._parse_time(item.get("lastOrderTime"))
            first_order = self._parse_time(item.get("firstOrderTime"))

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
                INSERT INTO qnh_customers
                    (tenant_id, customer_id, nickname, phone_tail, channel,
                     total_amount, order_count, avg_order_amount,
                     last_order_time, first_order_time, repurchase_rate,
                     address_city, address_district, tags, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,NOW())
                ON CONFLICT (customer_id) DO UPDATE SET
                    total_amount = EXCLUDED.total_amount,
                    order_count = EXCLUDED.order_count,
                    avg_order_amount = EXCLUDED.avg_order_amount,
                    last_order_time = EXCLUDED.last_order_time,
                    repurchase_rate = EXCLUDED.repurchase_rate,
                    tags = EXCLUDED.tags,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                cid,
                item.get("nickname", item.get("userName", "")),
                item.get("phoneTail", item.get("phone", "")),
                channel,
                float(item.get("totalAmount", 0)),
                int(item.get("orderCount", 0)),
                float(item.get("avgOrderAmount", 0)),
                last_order,
                first_order,
                float(item.get("repurchaseRate", 0)),
                item.get("city", ""),
                item.get("district", ""),
                json.dumps(item.get("tags", []), ensure_ascii=False),
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
