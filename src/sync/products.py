"""Product Syncer — SPU/SKU list, prices, categories, status.

Sync strategy:
  1. Try /api/v1/merchant/spu/page (full product management API) — TODO: needs verification
  2. Fallback to goldengateway hot-sale ranking if SPU API unavailable
  3. Always sync categories via /api/v1/merchant/storeCategory/queryAll
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from .base import BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)


class ProductSyncer(BaseSyncer):
    """Sync product master data from QNH.

    Data source: #/unifiedGoods/tenant/spu-list
    APIs:
      - POST /api/v1/merchant/spu/page — SPU 分页列表 (TODO: 待验证)
      - GET  /api/v1/merchant/spu/detail — SPU 详情 (TODO: 待验证)
      - POST /api/v1/merchant/storeCategory/queryAll — 商品分类 (已验证)
      - POST /goldengateway/.../query (hotsale) — 热销排行 (fallback)
    """

    name = "products"

    # goldengateway fallback
    VIEW_CODE = "homepage_hotsale_goods_rank_table_view_new"

    async def full_sync(self) -> SyncResult:
        """Full sync: try SPU API → browser capture → goldengateway fallback."""
        total = 0

        # Strategy 1: Try SPU page API (cookie auth, no mtgsig needed)
        try:
            total = await self._sync_via_spu_api()
        except Exception as e:
            logger.warning(f"SPU API unavailable ({e}), trying next strategy")
            total = 0

        # Strategy 2: Browser-based capture from product management page
        if total == 0:
            try:
                total = await self._sync_via_browser_capture()
            except Exception as e:
                logger.warning(f"Browser capture unavailable ({e}), trying goldengateway")
                total = 0

        # Strategy 3: Fallback to goldengateway hot-sale ranking (partial data)
        if total == 0:
            try:
                total = await self._sync_via_golden()
            except Exception as e:
                return SyncResult(
                    syncer_name=self.name,
                    mode=SyncMode.FULL,
                    success=False,
                    records_synced=0,
                    error=str(e),
                )

        return SyncResult(
            syncer_name=self.name,
            mode=SyncMode.FULL,
            success=True,
            records_synced=total,
        )

    async def incremental_sync(self, since: datetime) -> SyncResult:
        """Incremental sync delegates to full_sync (product APIs rarely support date filters)."""
        return await self.full_sync()

    # ── SPU API sync (preferred) ────────────────────────────────────────

    async def _sync_via_spu_api(self) -> int:
        """Sync via /api/v1/merchant/spu/page + detail."""
        total = 0
        page = 1
        page_size = 50

        while True:
            resp = await self.client.get_spu_page(page=page, page_size=page_size)
            data = resp.get("data", {})

            # Handle both list and paginated response formats
            if isinstance(data, list):
                items = data
                has_more = False
            else:
                items = data.get("list", data.get("rows", data.get("records", [])))
                total_pages = data.get("totalPage", data.get("pages", 1))
                has_more = page < total_pages

            if not items:
                break

            # Try to fetch detail for each SPU (for images/description)
            enriched_items = []
            for item in items:
                spu_id = str(item.get("spuId", item.get("id", "")))
                if spu_id:
                    try:
                        detail = await self.client.get_spu_detail(spu_id)
                        detail_data = detail.get("data", {})
                        if detail_data:
                            # Merge detail into item
                            item.update(detail_data)
                    except Exception as e:
                        logger.debug(f"SPU detail failed for {spu_id}: {e}")
                enriched_items.append(item)

            await self._upsert_products(enriched_items)
            total += len(enriched_items)
            self.logger.info(f"Products SPU API page {page}, got {len(items)} items")

            if not has_more:
                break
            page += 1

        return total

    # ── Browser-based capture ───────────────────────────────────────────

    async def _sync_via_browser_capture(self) -> int:
        """Sync by navigating to product management page and intercepting API calls.

        Strategy: Navigate to #/unifiedGoods/tenant/spu-list in the browser,
        which triggers the actual SPU list API call with proper mtgsig signature.
        Intercept the response to get full product data.
        """
        from .browser_client import BrowserClient

        browser = await BrowserClient.get_instance()
        await browser.ensure_ready()

        if not browser._page:
            raise RuntimeError("Browser page not available")

        page = browser._page
        total = 0

        # Navigate to product management page to discover actual API
        logger.info("Navigating to product management page to capture API calls...")

        # Intercept network responses to capture the product list API
        capture_js = """
        window.__captured_products = [];
        window.__original_fetch = window.__original_fetch || window.fetch;
        window.fetch = function() {
            var args = arguments;
            return window.__original_fetch.apply(this, args).then(function(response) {
                var url = (typeof args[0] === 'string') ? args[0] : (args[0].url || '');
                // Capture any product/spu/goods related API responses
                if (url.indexOf('/spu/') !== -1 || url.indexOf('/goods/') !== -1 ||
                    url.indexOf('/product/') !== -1 || url.indexOf('unifiedGoods') !== -1) {
                    var cloned = response.clone();
                    cloned.json().then(function(data) {
                        window.__captured_products.push({url: url, data: data});
                    }).catch(function() {});
                }
                return response;
            });
        };
        """
        await page.evaluate(capture_js)

        # Navigate to SPU list page
        await page.evaluate("window.location.hash = '#/unifiedGoods/tenant/spu-list';")
        await page.sleep(8)  # Wait for page load and API calls

        # Check captured data
        captured_str = await page.evaluate("JSON.stringify(window.__captured_products)")
        if captured_str and captured_str != "[]":
            import json as _json

            captured = _json.loads(captured_str)
            logger.info(f"Captured {len(captured)} product API calls from browser")

            for entry in captured:
                url = entry.get("url", "")
                data = entry.get("data", {})
                logger.info(f"Captured API: {url[:100]}")

                # Extract product items from various response formats
                items = self._extract_items_from_response(data)
                if items:
                    await self._upsert_products(items)
                    total += len(items)
                    logger.info(f"Extracted {len(items)} products from {url[:80]}")

        # Also try direct SPU page API via browser (with proper signatures)
        if total == 0:
            logger.info("No captured data, trying direct SPU API via browser...")
            page_num = 1
            page_size = 50
            while True:
                payload = {
                    "tenantId": self.client.tenant_id,
                    "page": page_num,
                    "pageSize": page_size,
                }
                try:
                    resp = await browser.execute_api(
                        "/api/v1/merchant/spu/page", method="POST", body=payload
                    )
                    if resp.get("_error") or resp.get("code", 0) != 0:
                        logger.warning(f"Browser SPU API error: {resp}")
                        break

                    items = self._extract_items_from_response(resp)
                    if not items:
                        break

                    await self._upsert_products(items)
                    total += len(items)
                    logger.info(f"Browser SPU API page {page_num}, got {len(items)} items")

                    # Check pagination
                    data = resp.get("data", {})
                    if isinstance(data, dict):
                        total_pages = data.get("totalPage", data.get("pages", 1))
                        if page_num >= total_pages:
                            break
                    page_num += 1
                except Exception as e:
                    logger.warning(f"Browser SPU API page {page_num} failed: {e}")
                    break

        # Restore original fetch
        await page.evaluate("if (window.__original_fetch) window.fetch = window.__original_fetch;")

        if total == 0:
            raise RuntimeError("Browser capture found no products")

        return total

    @staticmethod
    def _extract_items_from_response(data: dict) -> list[dict]:
        """Extract product items from various API response formats."""
        if not isinstance(data, dict):
            return []

        inner = data.get("data", data)
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            for key in ("list", "rows", "records", "items", "spuList", "productList"):
                items = inner.get(key)
                if isinstance(items, list) and items:
                    return items
        return []

    # ── Goldengateway fallback ──────────────────────────────────────────

    async def _sync_via_golden(self) -> int:
        """Sync via goldengateway hot-sale ranking (partial data)."""
        total = 0
        page = 1
        page_size = 50

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

            await self._upsert_products(items)
            total += len(items)

            total_pages = data.get("totalPage", data.get("pages", 1))
            self.logger.info(f"Products golden page {page}/{total_pages}, got {len(items)} items")

            if page >= total_pages:
                break
            page += 1

        return total

    # ── Upsert ──────────────────────────────────────────────────────────

    async def _upsert_products(self, items: list[dict[str, Any]]) -> None:
        """Upsert product records into qnh_products."""
        if not self.pool:
            return

        for item in items:
            spu_id = str(item.get("spuId", item.get("id", "")))
            sku_id = str(item.get("skuId", ""))
            if not spu_id:
                continue

            # Extract image URLs
            main_image = item.get("imageUrl", item.get("picUrl", item.get("mainImage", "")))

            # Collect all image URLs into extra
            image_list = item.get("imageUrls", item.get("images", item.get("picUrls", [])))
            description = item.get("description", item.get("desc", item.get("detail", "")))

            extra_data = {
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
                    "mainImage",
                }
            }
            # Ensure images and description are in extra for knowledge base
            if image_list:
                extra_data["imageUrls"] = image_list
            if description:
                extra_data["description"] = description

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
                main_image,
                _json_or_none(extra_data),
            )


def _json_or_none(val: Any) -> Any:
    """Convert dict/list to JSON string for JSONB column, or None."""
    if val is None:
        return None
    if isinstance(val, dict | list):
        return json.dumps(val, ensure_ascii=False)
    return None
