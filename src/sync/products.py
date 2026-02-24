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
    APIs:
      - POST /api/v1/merchant/storeCategory/queryAll — 商品分类
      - POST /goldengateway/empower/generic/table/query (module=hotProduct) — 商品列表
    NOTE: goldengateway module 名称为推断，需根据实际抓包验证。
    """

    name = "products"

    # 分类接口 (已验证)
    CATEGORY_API = "/api/v1/merchant/storeCategory/queryAll"

    # 推断的 goldengateway module 名，需验证
    MODULE_PRODUCT = "hotProduct"

    async def full_sync(self) -> SyncResult:
        """Full sync: fetch all products via goldengateway."""
        total = 0
        page = 1
        page_size = 50

        try:
            while True:
                # 使用 goldengateway 通用查询获取商品列表
                # NOTE: module 和参数格式为推断，需抓包验证
                resp = await self.client.golden_query(
                    module=self.MODULE_PRODUCT,
                    page=page,
                    page_size=page_size,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

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
                resp = await self.client.golden_query(
                    module=self.MODULE_PRODUCT,
                    start_date=since.strftime("%Y-%m-%d"),
                    page=page,
                    page_size=page_size,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

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
                _json_or_none(
                    {
                        k: v
                        for k, v in item.items()
                        if k
                        not in {
                            "spuId",
                            "id",
                            "skuId",
                            "name",
                            "spuName",
                            "barcode",
                            "upc",
                            "categoryName",
                            "category",
                            "brandName",
                            "brand",
                            "spec",
                            "specification",
                            "unit",
                            "costPrice",
                            "retailPrice",
                            "price",
                            "channelPrice",
                            "status",
                            "spuStatus",
                            "channelStatus",
                            "imageUrl",
                            "picUrl",
                        }
                    }
                ),
            )


def _json_or_none(val: Any) -> Any:
    """Convert dict/list to JSON string for JSONB column, or None."""
    import json

    if val is None:
        return None
    if isinstance(val, dict | list):
        return json.dumps(val, ensure_ascii=False)
    return None
