"""Order Syncer — order list, amounts, status, item details."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class OrderSyncer(BaseSyncer):
    """Sync order data from QNH.

    Data source: #/order/list
    API: POST /qnh-gw3/api/order/list (paginated, date-range filter)
    """

    name = "orders"
    full_sync_interval = timedelta(hours=12)

    ORDER_LIST_API = "/qnh-gw3/api/order/list"
    ORDER_DETAIL_API = "/qnh-gw3/api/order/detail"

    async def full_sync(self) -> SyncResult:
        """Full sync: last 30 days of orders."""
        end = datetime.now(CST)
        start = end - timedelta(days=30)
        return await self._sync_date_range(start, end, SyncMode.FULL)

    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental: orders since last sync."""
        end = datetime.now(CST)
        return await self._sync_date_range(since, end, SyncMode.INCREMENTAL)

    async def _sync_date_range(self, start: datetime, end: datetime, mode: SyncMode) -> SyncResult:
        total = 0
        page = 1
        page_size = 50

        try:
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": page_size,
                    "startTime": start.strftime("%Y-%m-%d %H:%M:%S"),
                    "endTime": end.strftime("%Y-%m-%d %H:%M:%S"),
                }
                resp = await self.client.post(self.ORDER_LIST_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                await self._upsert_orders(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                self.logger.info(f"Orders page {page}/{total_pages}, got {len(items)}")

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

    async def _upsert_orders(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        for item in items:
            order_id = str(item.get("orderId", item.get("id", "")))
            if not order_id:
                continue

            # Detect channel from platform field
            channel = _detect_channel(item)

            items_json = (
                json.dumps(
                    item.get("orderItems", item.get("items", [])),
                    ensure_ascii=False,
                )
                if item.get("orderItems") or item.get("items")
                else None
            )

            await self.pool.execute(
                """
                INSERT INTO qnh_orders
                    (order_id, tenant_id, channel, store_name, total_amount,
                     paid_amount, status, order_time, delivery_fee, packaging_fee,
                     customer_phone_suffix, items, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                ON CONFLICT (order_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    paid_amount = EXCLUDED.paid_amount,
                    items = EXCLUDED.items,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                order_id,
                self.client.tenant_id,
                channel,
                item.get("storeName", item.get("poiName", "")),
                item.get("totalAmount", item.get("orderAmount")),
                item.get("paidAmount", item.get("actualAmount")),
                item.get("status", item.get("orderStatus", "")),
                _parse_time(item.get("orderTime", item.get("createTime"))),
                item.get("deliveryFee", item.get("shippingFee")),
                item.get("packagingFee", item.get("boxFee")),
                item.get("phonesuffix", item.get("customerPhone", ""))[-4:]
                if item.get("phonesuffix") or item.get("customerPhone")
                else None,
                items_json,
                json.dumps(
                    {
                        k: v
                        for k, v in item.items()
                        if k
                        not in {
                            "orderId",
                            "id",
                            "storeName",
                            "poiName",
                            "totalAmount",
                            "orderAmount",
                            "paidAmount",
                            "actualAmount",
                            "status",
                            "orderStatus",
                            "orderTime",
                            "createTime",
                            "deliveryFee",
                            "shippingFee",
                            "packagingFee",
                            "boxFee",
                            "phonePrefix",
                            "customerPhone",
                            "orderItems",
                            "items",
                        }
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )


def _detect_channel(item: dict[str, Any]) -> str:
    platform = str(item.get("platform", item.get("channelName", ""))).lower()
    if "meituan" in platform or "闪购" in platform or "美团" in platform:
        return "meituan"
    if "eleme" in platform or "饿了么" in platform:
        return "eleme"
    if "jddj" in platform or "京东" in platform or "到家" in platform:
        return "jddj"
    return platform or "unknown"


def _parse_time(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, int | float):
        # Epoch millis
        if val > 1e12:
            val = val / 1000
        return datetime.fromtimestamp(val, tz=CST)
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None
