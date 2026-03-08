"""Inventory Syncer — stock levels via goldengateway."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class InventorySyncer(BaseSyncer):
    """Sync inventory data from QNH via goldengateway.

    API: POST /goldengateway/empower/generic/table/query (module=stockDetail)
    NOTE: module 名称为推断，需根据实际抓包验证。
    """

    name = "inventory"
    full_sync_interval = timedelta(hours=6)

    # 推断的 goldengateway module 名，需验证
    # 使用热销商品排行视图（包含库存相关数据）
    VIEW_CODE = "homepage_hotsale_goods_rank_table_view_new"

    async def full_sync(self) -> SyncResult:
        """Full sync: snapshot of all current stock levels."""
        total = 0
        page = 1
        page_size = 100

        try:
            while True:
                resp = await self.client.golden_query(
                    view_code=self.VIEW_CODE,
                    page=page,
                    page_size=page_size,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

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
        """Incremental: fetch stock changes since last sync."""
        total = 0
        page = 1

        try:
            while True:
                resp = await self.client.golden_query(
                    view_code=self.VIEW_CODE,
                    start_date=since.strftime("%Y-%m-%d"),
                    page=page,
                    page_size=100,
                )
                data = resp.get("data", {})
                items = data.get("list", data.get("rows", data.get("records", [])))

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

    async def _upsert_inventory(self, items: list[dict[str, Any]]) -> None:
        if not self.pool:
            return

        now = datetime.now(CST)
        saved = 0
        failed = 0
        for item in items:
            sku_id = str(item.get("skuId", item.get("goodsId", "")))
            if not sku_id:
                continue

            try:
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
                saved += 1
            except Exception:
                logger.error("Failed to upsert inventory sku_id=%s", sku_id, exc_info=True)
                failed += 1

        if failed:
            logger.warning("_upsert_inventory: saved=%d, failed=%d", saved, failed)


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
