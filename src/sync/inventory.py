"""Inventory Syncer — real-time stock levels and stock flow."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class InventorySyncer(BaseSyncer):
    """Sync inventory data from QNH.

    Data source: #/stock/query-new, #/stock/flow
    API: POST /qnh-gw3/api/stock/query (paginated)
    """

    name = "inventory"
    full_sync_interval = timedelta(hours=6)

    STOCK_QUERY_API = "/qnh-gw3/api/stock/query"
    STOCK_FLOW_API = "/qnh-gw3/api/stock/flow/list"

    async def full_sync(self) -> SyncResult:
        """Full sync: snapshot of all current stock levels."""
        total = 0
        page = 1
        page_size = 100

        try:
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": page_size,
                }
                resp = await self.client.post(self.STOCK_QUERY_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                await self._upsert_inventory(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.FULL,
                success=True,
                records_synced=total,
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.FULL,
                success=False,
                records_synced=total,
                error=str(e),
            )

    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental: fetch stock flow since last sync, then update affected items."""
        total = 0
        page = 1

        try:
            affected_skus: set[str] = set()

            # First get flow records to identify changed items
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": 100,
                    "startTime": since.strftime("%Y-%m-%d %H:%M:%S"),
                    "endTime": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                }
                resp = await self.client.post(self.STOCK_FLOW_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                for item in items:
                    sku_id = str(item.get("skuId", item.get("goodsId", "")))
                    if sku_id:
                        affected_skus.add(sku_id)

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

            # Then fetch current stock for affected SKUs
            if affected_skus:
                for sku_batch in _chunks(list(affected_skus), 50):
                    payload = {
                        "tenantId": self.client.tenant_id,
                        "skuIds": sku_batch,
                        "pageNum": 1,
                        "pageSize": len(sku_batch),
                    }
                    resp = await self.client.post(self.STOCK_QUERY_API, data=payload)
                    items = resp.get("data", {}).get("list", [])
                    await self._upsert_inventory(items)
                    total += len(items)

            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.INCREMENTAL,
                success=True,
                records_synced=total,
                details={"affected_skus": len(affected_skus)},
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.INCREMENTAL,
                success=False,
                records_synced=total,
                error=str(e),
            )

    async def _upsert_inventory(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        now = datetime.now(CST)
        for item in items:
            sku_id = str(item.get("skuId", item.get("goodsId", "")))
            if not sku_id:
                continue

            current_stock = item.get("currentStock", item.get("totalStock", 0))
            cost_price = item.get("costPrice")
            stock_value = None
            if current_stock and cost_price:
                with contextlib.suppress(ValueError, TypeError):
                    stock_value = float(current_stock) * float(cost_price)

            await self.pool.execute(
                """
                INSERT INTO qnh_inventory
                    (tenant_id, spu_id, sku_id, barcode, product_name,
                     current_stock, available_stock, locked_stock,
                     cost_price, stock_value, warehouse,
                     snapshot_time, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                """,
                self.client.tenant_id,
                str(item.get("spuId", "")),
                sku_id,
                item.get("barcode", item.get("upc", "")),
                item.get("goodsName", item.get("name", "")),
                _safe_int(current_stock),
                _safe_int(item.get("availableStock", item.get("sellableStock"))),
                _safe_int(item.get("lockedStock")),
                _safe_float(cost_price),
                stock_value,
                item.get("warehouseName", item.get("warehouse", "")),
                now,
                json.dumps(item, ensure_ascii=False, default=str),
            )


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
