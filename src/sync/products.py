"""Product Syncer — SPU/SKU list, prices, categories, status."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .base import BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class ProductSyncer(BaseSyncer):
    """Sync product master data from QNH.

    Data source: #/unifiedGoods/tenant/spu-list
    API: POST /api/v1/tenant/spu/list (paginated)
    Fallback: DOM extraction from SPU list page
    """

    name = "products"

    # ── API paths (discovered from network interception) ────────────────

    SPU_LIST_API = "/qnh-gw3/api/product/spu/list"
    SPU_DETAIL_API = "/qnh-gw3/api/product/spu/detail"
    STORE_GOODS_API = "/qnh-gw3/api/product/store-goods/list"
    CHANNEL_GOODS_API = "/qnh-gw3/api/product/channel-goods/list"

    async def full_sync(self) -> SyncResult:
        """Full sync: fetch all SPUs with pagination."""
        total = 0
        page = 1
        page_size = 50

        try:
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": page_size,
                    "status": None,  # all statuses
                }
                resp = await self.client.post(self.SPU_LIST_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                await self._upsert_products(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                self.logger.info(f"Products page {page}/{total_pages}, got {len(items)} items")

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
        """Incremental: fetch products updated since last sync."""
        total = 0
        page = 1
        page_size = 50

        try:
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "pageNum": page,
                    "pageSize": page_size,
                    "updateTimeStart": since.strftime("%Y-%m-%d %H:%M:%S"),
                }
                resp = await self.client.post(self.SPU_LIST_API, data=payload)
                data = resp.get("data", {})
                items = data.get("list", data.get("records", []))

                if not items:
                    break

                await self._upsert_products(items)
                total += len(items)

                total_pages = data.get("totalPage", data.get("pages", 1))
                if page >= total_pages:
                    break
                page += 1

            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.INCREMENTAL,
                success=True,
                records_synced=total,
            )
        except Exception as e:
            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.INCREMENTAL,
                success=False,
                records_synced=total,
                error=str(e),
            )

    async def _upsert_products(self, items: list[dict[str, Any]]) -> None:
        """Upsert product records into qnh_products."""
        if not self.pool:
            return

        for item in items:
            spu_id = str(item.get("spuId", item.get("id", "")))
            sku_id = str(item.get("skuId", ""))
            if not spu_id:
                continue

            await self.pool.execute(
                """
                INSERT INTO qnh_products
                    (spu_id, sku_id, tenant_id, name, barcode, category, brand,
                     spec, unit, cost_price, retail_price, channel_price,
                     status, channel_status, image_url, extra, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, NOW())
                ON CONFLICT (spu_id, sku_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    barcode = EXCLUDED.barcode,
                    category = EXCLUDED.category,
                    brand = EXCLUDED.brand,
                    spec = EXCLUDED.spec,
                    unit = EXCLUDED.unit,
                    cost_price = EXCLUDED.cost_price,
                    retail_price = EXCLUDED.retail_price,
                    channel_price = EXCLUDED.channel_price,
                    status = EXCLUDED.status,
                    channel_status = EXCLUDED.channel_status,
                    image_url = EXCLUDED.image_url,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                spu_id,
                sku_id or "",
                self.client.tenant_id,
                item.get("name", item.get("spuName", "")),
                item.get("barcode", item.get("upc", "")),
                item.get("categoryName", item.get("category", "")),
                item.get("brandName", item.get("brand", "")),
                item.get("spec", item.get("specification", "")),
                item.get("unit", ""),
                item.get("costPrice"),
                item.get("retailPrice", item.get("price")),
                _json_or_none(item.get("channelPrice")),
                item.get("status", item.get("spuStatus", "")),
                _json_or_none(item.get("channelStatus")),
                item.get("imageUrl", item.get("picUrl", "")),
                _json_or_none({
                    k: v for k, v in item.items()
                    if k not in {
                        "spuId", "id", "skuId", "name", "spuName", "barcode", "upc",
                        "categoryName", "category", "brandName", "brand", "spec",
                        "specification", "unit", "costPrice", "retailPrice", "price",
                        "channelPrice", "status", "spuStatus", "channelStatus",
                        "imageUrl", "picUrl",
                    }
                }),
            )


def _json_or_none(val: Any) -> Any:
    """Convert dict/list to JSON string for JSONB column, or None."""
    import json
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return None
