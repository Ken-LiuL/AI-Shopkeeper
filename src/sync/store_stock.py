"""Store Stock Syncer — sync per-store inventory & sales data via browser API."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StockAggregate:
    total_stock: int = 0
    monthly_sales: int = 0
    cost_price: Decimal | None = None

    def apply(
        self,
        stock_delta: int,
        monthly_sales_delta: int,
        cost_candidate: Decimal | None,
    ) -> None:
        self.total_stock += stock_delta
        self.monthly_sales += monthly_sales_delta
        if self.cost_price is None and cost_candidate is not None:
            self.cost_price = cost_candidate


class StoreStockSyncer(BaseSyncer):
    """Syncer that fetches detailed store inventory using BrowserClient."""

    name = "store_stock"
    full_sync_interval = timedelta(hours=6)

    API_PATH = "/qnh-gw3/api/product/store/page-query-spu"
    DEFAULT_POI_IDS: tuple[int, ...] = (1175006, 1221411, 1232550)
    PAGE_SIZE = 50

    def __init__(
        self,
        client: Any,
        db_pool: Any,
        poi_ids: Sequence[int] | None = None,
        page_size: int | None = None,
    ) -> None:
        super().__init__(client, db_pool)
        self.poi_ids = tuple(int(pid) for pid in (poi_ids or self.DEFAULT_POI_IDS))
        self.page_size = page_size or self.PAGE_SIZE

    async def full_sync(self) -> SyncResult:
        stats = await self._sync_all_stores()
        return SyncResult(
            syncer_name=self.name,
            mode=SyncMode.FULL,
            success=True,
            records_synced=stats["updated_spu"],
            details=stats,
        )

    async def incremental_sync(self, since: datetime) -> SyncResult:  # noqa: ARG002
        # API 不支持按时间增量，直接跑全量
        return await self.full_sync()

    # ── Internal helpers ────────────────────────────────────────────

    async def _sync_all_stores(self) -> dict[str, Any]:
        aggregated: dict[str, StockAggregate] = {}
        per_store: dict[str, Any] = {}
        total_rows = 0

        for poi_id in self.poi_ids:
            store_stats = {"pages": 0, "items": 0, "stock": 0}
            page = 1
            while True:
                items, total_pages = await self._fetch_page(poi_id, page)
                if not items:
                    if page == 1:
                        self.logger.warning("POI %s 返回空数据（可能无权限或无商品）", poi_id)
                    break

                store_stats["pages"] += 1
                store_stats["items"] += len(items)
                total_rows += len(items)

                for item in items:
                    stock_delta = self._extract_stock(item.get("storeSkuList", []))
                    store_stats["stock"] += stock_delta
                    monthly_sales_delta = _to_int(item.get("monthSaleAmount"))
                    cost_candidate = self._extract_cost(item.get("storeSkuList", []))
                    spu_id = str(item.get("spuId") or "")
                    if not spu_id:
                        continue
                    aggregate = aggregated.setdefault(spu_id, StockAggregate())
                    aggregate.apply(stock_delta, monthly_sales_delta, cost_candidate)

                if page >= total_pages:
                    break
                page += 1

            per_store[str(poi_id)] = store_stats
            self.logger.info(
                "Store %s processed: %s pages, %s items, stock=%s",
                poi_id,
                store_stats["pages"],
                store_stats["items"],
                store_stats["stock"],
            )

        await self._update_tables(aggregated.items())

        total_stock = sum(agg.total_stock for agg in aggregated.values())
        stats = {
            "updated_spu": len(aggregated),
            "total_rows": total_rows,
            "total_stock": total_stock,
            "stores": per_store,
        }
        self.logger.info(
            "Store stock sync completed: %d SPUs, %d rows, total stock=%d",
            stats["updated_spu"],
            total_rows,
            total_stock,
        )
        return stats

    async def _fetch_page(self, poi_id: int, page: int) -> tuple[list[dict[str, Any]], int]:
        payload = {"page": page, "pageSize": self.page_size, "poiId": poi_id}
        resp = await self.client.execute_api(self.API_PATH, method="POST", body=payload)

        if not isinstance(resp, dict):
            raise RuntimeError(f"Unexpected API response for poi {poi_id}: {resp!r}")
        if resp.get("_error"):
            raise RuntimeError(f"Store API error (poi={poi_id}, page={page}): {resp['_error']}")
        code = resp.get("code")
        if code not in (None, 0):
            raise RuntimeError(f"Store API code={code} (poi={poi_id}, page={page})")

        data = resp.get("data") or {}
        items = data.get("list") or []
        total_pages = data.get("totalPage") or 0
        if not total_pages:
            total = data.get("total")
            total_pages = math.ceil(total / self.page_size) if total else 1

        return items, int(max(total_pages, 1))

    def _extract_stock(self, sku_list: Iterable[dict[str, Any]] | None) -> int:
        if not sku_list:
            return 0
        stock = 0
        for sku in sku_list:
            stock += _to_int(sku.get("stock"))
        return stock

    def _extract_cost(self, sku_list: Iterable[dict[str, Any]] | None) -> Decimal | None:
        if not sku_list:
            return None
        for sku in sku_list:
            candidate = _to_decimal(sku.get("costPrice"))
            if candidate is not None:
                return candidate
        return None

    async def _update_tables(
        self,
        entries: Iterable[tuple[str, StockAggregate]],
    ) -> None:
        if not self.pool:
            self.logger.warning("DB pool unavailable, skip stock update")
            return

        tuples = list(entries)
        if not tuples:
            self.logger.warning("No store stock data to update")
            return

        qnh_rows = [(spu_id, agg.total_stock, agg.cost_price) for spu_id, agg in tuples]
        product_rows = [
            (spu_id, agg.total_stock, agg.cost_price, agg.monthly_sales) for spu_id, agg in tuples
        ]

        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                UPDATE qnh_products
                SET stock = $2,
                    stock_num = $2,
                    cost_price = COALESCE($3, cost_price),
                    updated_at = NOW()
                WHERE spu_id = $1
                """,
                qnh_rows,
            )
            await conn.executemany(
                """
                UPDATE products
                SET stock = $2,
                    cost_price = COALESCE($3, cost_price),
                    monthly_sales = $4,
                    updated_at = NOW()
                WHERE product_id = $1
                """,
                product_rows,
            )

        self.logger.info(
            "Updated %d rows in qnh_products/products with store stock aggregates", len(tuples)
        )


def _to_int(value: Any) -> int:
    if value in (None, "", "null"):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
