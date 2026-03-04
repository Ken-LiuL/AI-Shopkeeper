"""MeituanProductSyncer — 同步美团买药商家中心的商品与销量数据。"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .base import CST, BaseSyncer, SyncMode, SyncResult
from .meituan_client import MeituanBrowserClient

logger = logging.getLogger(__name__)

PRODUCTS_API = "/reuse/health/product/retail/r/searchListPageV2"
DEFAULT_FORM_PARAMS = {
    "needTag": 0,
    "state": 0,
    "sortType": "",
    "sortKey": "",
    "saleStatus": 0,
    "limitSale": 0,
    "needCombinationSpu": -1,
    "noStockAutoClear": -1,
    "problemType": 1,
    "noSingleDeliveryType": 0,
}


class MeituanProductSyncer(BaseSyncer):
    """同步美团买药商品列表 → products & sales_history"""

    name = "meituan_products"

    def __init__(self, client: MeituanBrowserClient, db_pool: Any, wm_poi_id: str) -> None:
        super().__init__(client, db_pool)
        self.wm_poi_id = str(wm_poi_id)
        self._product_columns: set[str] = set()

    async def full_sync(self) -> SyncResult:
        total = 0
        try:
            total = await self._sync_all_products()
            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.FULL,
                success=True,
                records_synced=total,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("美团商品全量同步失败: %s", exc, exc_info=True)
            return SyncResult(
                syncer_name=self.name,
                mode=SyncMode.FULL,
                success=False,
                records_synced=total,
                error=str(exc),
            )

    async def incremental_sync(self, since: datetime) -> SyncResult:  # noqa: ARG002
        return await self.full_sync()

    # ── Internal ─────────────────────────────────────────────

    async def _sync_all_products(self) -> int:
        page = 1
        page_size = 50
        total_synced = 0

        while True:
            payload = {
                **DEFAULT_FORM_PARAMS,
                "wmPoiId": self.wm_poi_id,
                "pageNum": page,
                "pageSize": page_size,
            }
            resp = await self.client.execute_api(PRODUCTS_API, method="POST", body_params=payload)

            if not isinstance(resp, dict):
                raise RuntimeError("美团商品 API 返回非 JSON 数据")
            if resp.get("error") or resp.get("_error"):
                raise RuntimeError(f"美团商品 API 错误: {resp.get('message')}")
            code = resp.get("code")
            if code not in (0, None):
                raise RuntimeError(
                    f"美团商品 API 错误码 {code}: {resp.get('msg') or resp.get('message')}"
                )

            data = resp.get("data") if isinstance(resp, dict) else None
            if not data or "productList" not in data:
                raise RuntimeError("美团商品 API 响应缺少 data.productList")

            items = data.get("productList") or []
            total_count = int(data.get("totalCount") or 0)

            await self._upsert_products(items)
            total_synced += len(items)
            self.logger.info(
                "meituan_products page %s ⇒ %s items (total=%s)", page, len(items), total_synced
            )

            if not items or page * page_size >= total_count:
                break
            page += 1

        return total_synced

    async def _upsert_products(self, items: list[dict[str, Any]]) -> None:
        if not self.pool or not items:
            return

        await self._ensure_product_columns()
        has_image_col = "image_url" in self._product_columns
        has_upc_col = "upc_code" in self._product_columns

        now = datetime.now(CST)
        today = now.date()

        product_rows = []
        sales_rows = []
        for item in items:
            product_id = str(item.get("id"))
            if not product_id:
                continue

            skus = item.get("wmProductSkus") or []
            price = self._extract_price(skus)
            if price is None:
                price = Decimal("0")
            stock = sum(self._safe_int(sku.get("stock")) for sku in skus if isinstance(sku, dict))
            monthly_sales = self._safe_int(item.get("sellCount"))
            status = "active" if str(item.get("sellStatus")) == "0" else "delisted"
            barcode = item.get("upcCode") or None
            image_url = item.get("picture") if has_image_col else None

            product_rows.append(
                {
                    "product_id": product_id,
                    "name": item.get("name", "") or "",
                    "barcode": barcode,
                    "category": item.get("categoryName"),
                    "brand": item.get("brandName"),
                    "retail_price": price,
                    "stock": stock,
                    "monthly_sales": monthly_sales,
                    "status": status,
                    "image_url": image_url,
                    "upc_code": barcode if has_upc_col else None,
                    "description": None,
                }
            )

            revenue = (price * Decimal(monthly_sales or 0)).quantize(Decimal("0.01"))
            sales_rows.append((product_id, today, monthly_sales or 0, revenue, now))

        if not product_rows:
            return

        async with self.pool.acquire() as conn:
            columns = [
                "product_id",
                "name",
                "barcode",
                "category",
                "brand",
                "description",
                "retail_price",
                "stock",
                "monthly_sales",
                "status",
            ]
            values = []
            for row in product_rows:
                values.append(
                    [
                        row["product_id"],
                        row["name"],
                        row["barcode"],
                        row["category"],
                        row["brand"],
                        row["description"],
                        row["retail_price"],
                        row["stock"],
                        row["monthly_sales"],
                        row["status"],
                    ]
                )
            if has_image_col:
                columns.append("image_url")
                for idx, row in enumerate(product_rows):
                    values[idx].append(row["image_url"])
            if has_upc_col:
                columns.append("upc_code")
                for idx, row in enumerate(product_rows):
                    values[idx].append(row["upc_code"])
            # store_id for multi-tenant
            columns.append("store_id")
            for row in values:
                row.append(self.wm_poi_id)

            columns.extend(["updated_at"])
            for row in values:
                row.append(now)

            placeholders = ",".join(f"${i + 1}" for i in range(len(columns)))
            update_cols = [c for c in columns if c not in {"product_id"}]
            update_stmt = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
            insert_sql = f"""
                INSERT INTO products ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (product_id) DO UPDATE SET {update_stmt}
            """
            await conn.executemany(insert_sql, [tuple(v) for v in values])

            if sales_rows:
                # 加 store_id 到 sales_history
                sales_rows_with_store = [
                    (pid, date, qty, rev, ts, self.wm_poi_id)
                    for pid, date, qty, rev, ts in sales_rows
                ]
                await conn.executemany(
                    """
                    INSERT INTO sales_history (product_id, sale_date, quantity, revenue, created_at, store_id)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    ON CONFLICT (product_id, store_id, sale_date)
                    DO UPDATE SET quantity = EXCLUDED.quantity,
                                   revenue = EXCLUDED.revenue
                    """,
                    sales_rows_with_store,
                )

    async def _ensure_product_columns(self) -> None:
        if self._product_columns or not self.pool:
            return
        rows = await self.pool.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'products' AND table_schema = 'public'
            """
        )
        self._product_columns = {r["column_name"] for r in rows}

    @staticmethod
    def _safe_int(val: Any) -> int:
        if val in (None, ""):
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):  # noqa: BLE001
            return 0

    def _extract_price(self, skus: list[dict[str, Any]]) -> Decimal | None:
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            price = sku.get("price")
            if price is not None:
                return self._normalize_price(price)
            if sku.get("activityLowPrice") is not None:
                return self._normalize_price(sku.get("activityLowPrice"))
        return None

    @staticmethod
    def _normalize_price(value: Any) -> Decimal:
        try:
            dec = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):  # noqa: BLE001
            return Decimal("0")
        if dec > Decimal("1000") and dec == dec.to_integral_value():
            dec = dec / Decimal("100")
        return dec.quantize(Decimal("0.01"))
