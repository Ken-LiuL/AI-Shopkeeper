"""Channel Syncer — 渠道流量分布via goldengateway。

NOTE: 参数格式为推断，需根据实际抓包验证。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult
from .qnh_client import GOLDEN_CHANNEL_DIST

logger = logging.getLogger(__name__)


class ChannelSyncer(BaseSyncer):
    """同步渠道流量分布数据。

    API: POST /goldengateway/empower/homepage/channelDistributeList
    NOTE: 参数格式为推断，需根据实际抓包验证。
    """

    name = "channels"
    full_sync_interval = timedelta(hours=24)

    async def full_sync(self) -> SyncResult:
        end = datetime.now(CST)
        start = end - timedelta(days=90)
        return await self._sync_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        end = datetime.now(CST)
        return await self._sync_range(since, end, SyncMode.INCREMENTAL)

    async def _sync_range(self, start: datetime, end: datetime, mode: SyncMode) -> SyncResult:
        total = 0

        try:
            # 按天逐日拉取
            current = start
            while current <= end:
                date_str = current.strftime("%Y-%m-%d")
                # 使用 goldengateway 渠道分布接口
                # NOTE: 参数格式为推断，需抓包验证
                payload = {
                    "tenantId": self.client.tenant_id,
                    "poiIds": self.client.poi_ids,
                    "date": date_str,
                }
                try:
                    resp = await self.client.post(GOLDEN_CHANNEL_DIST, data=payload)
                    data = resp.get("data", {})
                    channels = data.get("channels", data.get("list", data.get("records", [])))

                    if channels:
                        await self._upsert_channels(date_str, channels)
                        total += len(channels)
                except Exception as e:
                    self.logger.warning(f"Channel data for {date_str}: {e}")

                current += timedelta(days=1)

            return SyncResult(syncer_name=self.name, mode=mode, success=True, records_synced=total)
        except Exception as e:
            return SyncResult(
                syncer_name=self.name, mode=mode, success=False, records_synced=total, error=str(e)
            )

    async def _upsert_channels(self, date_str: str, channels: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in channels:
            channel_name = str(item.get("channel", item.get("channelName", ""))).lower()
            if "meituan" in channel_name or "美团" in channel_name:
                channel = "meituan"
            elif "eleme" in channel_name or "饿了么" in channel_name:
                channel = "eleme"
            elif "jddj" in channel_name or "京东" in channel_name:
                channel = "jddj"
            else:
                channel = channel_name or "unknown"

            await self.pool.execute(
                """
                INSERT INTO qnh_traffic_channels
                    (tenant_id, date, channel, exposure, clicks, orders,
                     click_rate, conversion_rate, gmv, new_customers, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())
                ON CONFLICT (tenant_id, date, channel) DO UPDATE SET
                    exposure = EXCLUDED.exposure,
                    clicks = EXCLUDED.clicks,
                    orders = EXCLUDED.orders,
                    click_rate = EXCLUDED.click_rate,
                    conversion_rate = EXCLUDED.conversion_rate,
                    gmv = EXCLUDED.gmv,
                    new_customers = EXCLUDED.new_customers,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                datetime.strptime(date_str, "%Y-%m-%d").date(),
                channel,
                int(item.get("exposure", item.get("impressions", 0))),
                int(item.get("clicks", 0)),
                int(item.get("orders", item.get("orderCount", 0))),
                float(item.get("clickRate", item.get("ctr", 0))),
                float(item.get("conversionRate", item.get("cvr", 0))),
                float(item.get("gmv", item.get("totalAmount", 0))),
                int(item.get("newCustomers", 0)),
                json.dumps(item, ensure_ascii=False, default=str),
            )
