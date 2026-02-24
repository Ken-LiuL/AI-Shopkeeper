"""Traffic Syncer — channel distribution via goldengateway."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class TrafficSyncer(BaseSyncer):
    """Sync product traffic data from QNH via goldengateway.

    APIs:
      - POST /goldengateway/empower/homepage/channelDistributeList — 渠道分布
      - POST /goldengateway/empower/generic/table/query (module=trafficDetail) — 商品流量
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "traffic"
    full_sync_interval = timedelta(hours=20)

    # 推断的 goldengateway module 名，需验证
    MODULE_TRAFFIC = "trafficDetail"

    async def full_sync(self) -> SyncResult:
        """Full sync: last 7 days of traffic data."""
        end = datetime.now(CST).date()
        start = end - timedelta(days=7)
        return await self._sync_date_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental: traffic since last sync."""
        end = datetime.now(CST).date()
        start = since.date() if isinstance(since, datetime) else since
        return await self._sync_date_range(start, end, SyncMode.INCREMENTAL)

    async def _sync_date_range(self, start: Any, end: Any, mode: SyncMode) -> SyncResult:
        total = 0
        from datetime import date as date_cls

        current = start if isinstance(start, date_cls) else start.date()
        end_date = end if isinstance(end, date_cls) else end.date()

        try:
            while current <= end_date:
                date_str = current.strftime("%Y-%m-%d")

                page = 1
                while True:
                    try:
                        # 使用 goldengateway 通用查询获取商品流量
                        # NOTE: module 和参数格式为推断，需抓包验证
                        resp = await self.client.golden_query(
                            module=self.MODULE_TRAFFIC,
                            start_date=date_str,
                            end_date=date_str,
                            page=page,
                            page_size=100,
                        )
                        data = resp.get("data", {})
                        items = data.get("list", data.get("rows", data.get("records", [])))

                        if not items:
                            break

                        await self._upsert_traffic(current, None, items)
                        total += len(items)

                        total_pages = data.get("totalPage", data.get("pages", 1))
                        if page >= total_pages:
                            break
                        page += 1
                    except Exception as e:
                        self.logger.warning(f"Traffic {date_str} p={page}: {e}")
                        break

                current += timedelta(days=1)

            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=True,
                records_synced=total,
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=mode,
                success=False,
                records_synced=total,
                error=str(e),
            )

    async def _upsert_traffic(
        self, traffic_date: Any, channel: str | None, items: list[dict[str, Any]]
    ) -> None:
        if not self.pool:
            return

        for item in items:
            spu_id = str(item.get("spuId", item.get("goodsId", "")))
            if not spu_id:
                continue

            impressions = item.get("exposure", item.get("impressions", 0)) or 0
            clicks = item.get("click", item.get("clicks", 0)) or 0
            orders = item.get("orderCount", item.get("orders", 0)) or 0
            click_rate = (clicks / impressions) if impressions > 0 else 0
            conv_rate = (orders / clicks) if clicks > 0 else 0

            await self.pool.execute(
                """
                INSERT INTO qnh_traffic
                    (tenant_id, traffic_date, channel, spu_id, product_name,
                     impressions, clicks, click_rate, orders, conversion_rate,
                     extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())
                ON CONFLICT (traffic_date, channel, spu_id) DO UPDATE SET
                    product_name = EXCLUDED.product_name,
                    impressions = EXCLUDED.impressions,
                    clicks = EXCLUDED.clicks,
                    click_rate = EXCLUDED.click_rate,
                    orders = EXCLUDED.orders,
                    conversion_rate = EXCLUDED.conversion_rate,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                traffic_date,
                channel,
                spu_id,
                item.get("goodsName", item.get("name", "")),
                impressions,
                clicks,
                click_rate,
                orders,
                conv_rate,
                json.dumps(item, ensure_ascii=False, default=str),
            )
