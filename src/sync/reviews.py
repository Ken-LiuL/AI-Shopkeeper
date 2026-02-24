"""Review Syncer — ratings, review content via goldengateway."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class ReviewSyncer(BaseSyncer):
    """Sync review data from QNH via goldengateway.

    API: POST /goldengateway/empower/generic/table/query (module=reviewDetail)
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "reviews"
    full_sync_interval = timedelta(hours=24)

    # 推断的 goldengateway module 名，需验证
    MODULE_REVIEW = "reviewDetail"

    async def full_sync(self) -> SyncResult:
        """Full sync: last 90 days of reviews."""
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
                resp = await self.client.golden_query(
                    module=self.MODULE_REVIEW,
                    start_date=start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                    page=page,
                    page_size=50,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

                if not items:
                    break

                await self._upsert_reviews(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

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

    async def _upsert_reviews(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            review_id = str(item.get("reviewId", item.get("id", "")))
            if not review_id:
                continue

            review_time = item.get("reviewTime", item.get("createTime"))
            if isinstance(review_time, int | float):
                review_time = datetime.fromtimestamp(
                    review_time / 1000 if review_time > 1e12 else review_time,
                    tz=CST,
                )
            elif isinstance(review_time, str):
                try:
                    review_time = datetime.fromisoformat(review_time)
                except Exception:
                    review_time = None

            platform = str(item.get("platform", item.get("channel", ""))).lower()
            channel = "unknown"
            if "meituan" in platform or "美团" in platform:
                channel = "meituan"
            elif "eleme" in platform or "饿了么" in platform:
                channel = "eleme"
            elif "jddj" in platform or "京东" in platform:
                channel = "jddj"

            await self.pool.execute(
                """
                INSERT INTO qnh_reviews
                    (tenant_id, review_id, order_id, channel, rating,
                     content, reply, review_time, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
                ON CONFLICT (review_id) DO UPDATE SET
                    reply = EXCLUDED.reply,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                review_id,
                str(item.get("orderId", "")) or None,
                channel,
                item.get("rating", item.get("score")),
                item.get("content", item.get("comment", "")),
                item.get("reply", item.get("merchantReply", "")),
                review_time,
                json.dumps(item, ensure_ascii=False, default=str),
            )
