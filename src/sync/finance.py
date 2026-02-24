"""Finance Syncer — 财务结算数据同步。

NOTE: API 路径为推断，需验证实际牵牛花接口。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class FinanceSyncer(BaseSyncer):
    """同步财务结算数据（结算单 + 扣费明细）。

    API (推断，需验证):
      - POST /qnh-gw3/api/finance/settlement — 结算单列表
      - POST /qnh-gw3/api/finance/fees — 扣费明细
    """

    name = "finance"
    full_sync_interval = timedelta(hours=24)

    SETTLEMENT_API = "/qnh-gw3/api/finance/settlement"
    FEES_API = "/qnh-gw3/api/finance/fees"

    async def full_sync(self) -> SyncResult:
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
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": 50,
                    "startDate": start.strftime("%Y-%m-%d"),
                    "endDate": end.strftime("%Y-%m-%d"),
                    "storeIds": self.client.poi_ids,
                }
                resp = await self.client.post(self.SETTLEMENT_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                # 逐个拉扣费明细
                for item in items:
                    sid = str(item.get("settlementId", item.get("id", "")))
                    if sid:
                        try:
                            fees_resp = await self.client.post(
                                self.FEES_API,
                                data={"tenantId": self.client.tenant_id, "settlementId": sid},
                            )
                            item["feeDetails"] = fees_resp.get("data", {})
                        except Exception:
                            pass

                await self._upsert_settlements(items)
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

    async def _upsert_settlements(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            sid = str(item.get("settlementId", item.get("id", "")))
            if not sid:
                continue

            channel = str(item.get("platform", item.get("channel", ""))).lower()
            if "meituan" in channel or "美团" in channel:
                channel = "meituan"
            elif "eleme" in channel or "饿了么" in channel:
                channel = "eleme"
            elif "jddj" in channel or "京东" in channel:
                channel = "jddj"
            else:
                channel = "unknown"

            period_start = self._parse_date(item.get("periodStart", item.get("startDate")))
            period_end = self._parse_date(item.get("periodEnd", item.get("endDate")))

            await self.pool.execute(
                """
                INSERT INTO qnh_settlements
                    (tenant_id, settlement_id, channel, period_start, period_end,
                     gross_income, platform_fee, delivery_fee, commission_fee,
                     promotion_fee, packaging_fee, other_fee, net_income,
                     order_count, fee_details, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,NOW())
                ON CONFLICT (settlement_id) DO UPDATE SET
                    net_income = EXCLUDED.net_income,
                    fee_details = EXCLUDED.fee_details,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                self.client.tenant_id,
                sid,
                channel,
                period_start,
                period_end,
                float(item.get("grossIncome", item.get("totalIncome", 0))),
                float(item.get("platformFee", item.get("serviceFee", 0))),
                float(item.get("deliveryFee", 0)),
                float(item.get("commissionFee", item.get("commission", 0))),
                float(item.get("promotionFee", item.get("activityFee", 0))),
                float(item.get("packagingFee", 0)),
                float(item.get("otherFee", 0)),
                float(item.get("netIncome", item.get("settlementAmount", 0))),
                int(item.get("orderCount", 0)),
                json.dumps(item.get("feeDetails", {}), ensure_ascii=False),
                json.dumps(item, ensure_ascii=False, default=str),
            )

    def _parse_date(self, val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except Exception:
                return None
        return None
