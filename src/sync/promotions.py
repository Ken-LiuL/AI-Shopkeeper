"""Promotion Syncer — 营销活动数据via goldengateway。

NOTE: goldengateway module 名称为推断，需根据实际抓包验证。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class PromotionSyncer(BaseSyncer):
    """同步营销活动数据（满减/折扣/秒杀/买赠/优惠券）。

    API: POST /goldengateway/empower/generic/table/query (module=promotionDetail)
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "promotions"
    full_sync_interval = timedelta(hours=24)

    # 推断的 goldengateway module 名，需验证
    VIEW_CODE = "homepage_not_erp_poi_rank_table_view"  # TODO: 需要找到营销专用 viewCode

    async def full_sync(self) -> SyncResult:
        """全量同步: 最近180天的活动。"""
        end = datetime.now(CST)
        start = end - timedelta(days=180)
        return await self._sync_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        end = datetime.now(CST)
        return await self._sync_range(since, end, SyncMode.INCREMENTAL)

    async def _sync_range(self, start: datetime, end: datetime, mode: SyncMode) -> SyncResult:
        total = 0
        page = 1

        try:
            while True:
                resp = await self.client.golden_query(
                    view_code=self.VIEW_CODE,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                    page=page,
                    page_size=50,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

                if not items:
                    break

                await self._upsert_promotions(items)
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

    async def _upsert_promotions(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            promo_id = str(item.get("promotionId", item.get("id", "")))
            if not promo_id:
                continue

            start_time = self._parse_time(item.get("startTime"))
            end_time = self._parse_time(item.get("endTime"))

            platform = str(item.get("platform", item.get("channel", ""))).lower()
            channel = self._detect_channel(platform)

            status = item.get("status", item.get("activityStatus", ""))
            if isinstance(status, int):
                status = {0: "pending", 1: "active", 2: "ended", 3: "paused"}.get(
                    status, str(status)
                )

            await self.pool.execute(
                """
                INSERT INTO qnh_promotions
                    (tenant_id, promotion_id, channel, promotion_type, title,
                     start_time, end_time, status, discount_rule, product_ids,
                     effect_data, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                ON CONFLICT (promotion_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    effect_data = EXCLUDED.effect_data,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                promo_id,
                channel,
                item.get("promotionType", item.get("type", "")),
                item.get("title", item.get("name", "")),
                start_time,
                end_time,
                str(status),
                json.dumps(item.get("discountRule", item.get("rule", {})), ensure_ascii=False),
                json.dumps(item.get("productIds", item.get("skuIds", [])), ensure_ascii=False),
                json.dumps(item.get("effectData", {}), ensure_ascii=False),
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

    def _detect_channel(self, platform: str) -> str:
        if "meituan" in platform or "美团" in platform:
            return "meituan"
        if "eleme" in platform or "饿了么" in platform:
            return "eleme"
        if "jddj" in platform or "京东" in platform:
            return "jddj"
        return "unknown"
