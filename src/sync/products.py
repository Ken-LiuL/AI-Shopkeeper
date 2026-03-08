"""Product Syncer — SPU/SKU list, prices, categories, status.

Sync strategy:
  1. Try /qnh-gw3/api/product/tenant/page-query (via browser, h5guard signed)
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
      - POST /qnh-gw3/api/product/tenant/page-query — SPU 分页列表 (已验证, h5guard)
      - POST /qnh-gw3/api/product/tenant/detail — SPU 详情 (h5guard)
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
        """Sync via /qnh-gw3/api/product/tenant/page-query (browser, h5guard signed).

        Response format:
          {code: 0, data: {list: [{tenantId, spuId, spuName, picUrlList, skus, brand, weightType, ...}], total, ...}}
        """
        total = 0
        page = 1
        page_size = 20

        while True:
            resp = await self.client.get_spu_page(page=page, page_size=page_size)

            # Check for errors
            if isinstance(resp, dict) and resp.get("_error"):
                raise RuntimeError(f"SPU API error: {resp.get('message', resp)}")
            code = resp.get("code")
            if code is not None and code != 0:
                raise RuntimeError(f"SPU API code {code}: {resp.get('msg', '')}")

            data = resp.get("data", {})

            # Handle both list and paginated response formats
            if isinstance(data, list):
                items = data
                has_more = False
            else:
                items = data.get("list", data.get("rows", data.get("records", [])))
                total_count = data.get("total", data.get("totalCount", 0))
                has_more = page * page_size < total_count

            if not items:
                break

            # Optionally enrich with detail (skip if list already has enough data)
            enriched_items = []
            for item in items:
                spu_id = str(item.get("spuId", item.get("id", "")))
                # Only fetch detail if we need more data (e.g., description missing)
                if spu_id and not item.get("description") and not item.get("detail"):
                    try:
                        detail = await self.client.get_spu_detail(spu_id)
                        detail_data = detail.get("data", {})
                        if detail_data and isinstance(detail_data, dict):
                            item.update(detail_data)
                    except Exception as e:
                        logger.debug(f"SPU detail failed for {spu_id}: {e}")
                enriched_items.append(item)

            await self._upsert_products(enriched_items)
            total += len(enriched_items)
            self.logger.info(
                f"Products SPU API page {page}, got {len(items)} items (total so far: {total})"
            )

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
            page_size = 20
            while True:
                payload = {
                    "page": page_num,
                    "pageSize": page_size,
                    "current": page_num,
                }
                try:
                    resp = await browser.execute_api(
                        "/qnh-gw3/api/product/tenant/page-query", method="POST", body=payload
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
        """Upsert product records into qnh_products. Single item failure does not abort batch."""
        if not self.pool:
            return

        saved = 0
        failed = 0
        for item in items:
            spu_id = str(item.get("spuId", item.get("id", "")))
            sku_id = str(item.get("skuId", ""))
            if not spu_id:
                continue

            try:
                # Extract image URLs (new API uses picUrlList)
                pic_url_list = item.get("picUrlList", [])
                main_image = (
                    pic_url_list[0]
                    if pic_url_list
                    else item.get("imageUrl", item.get("picUrl", item.get("mainImage", "")))
                )

                # Collect all image URLs into extra
                image_list = pic_url_list or item.get(
                    "imageUrls", item.get("images", item.get("picUrls", []))
                )
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
                        "picUrlList",
                        "tenantId",
                        "weightType",
                    }
                }
                # Ensure images, description, and SKU data are in extra for knowledge base
                if image_list:
                    extra_data["imageUrls"] = image_list
                if description:
                    extra_data["description"] = description
                # Preserve embedded SKU data from new API
                skus = item.get("skus", [])
                if skus:
                    extra_data["skus"] = skus
                weight_type = item.get("weightType")
                if weight_type:
                    extra_data["weightType"] = weight_type

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
                    (lambda b: b.get("brandName", "") if isinstance(b, dict) else (b or ""))(item.get("brandName", item.get("brand", ""))),
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
                saved += 1
            except Exception:
                logger.error("Failed to upsert product spu_id=%s sku_id=%s", spu_id, sku_id, exc_info=True)
                failed += 1

        if failed:
            logger.warning("_upsert_products: saved=%d, failed=%d", saved, failed)


def _json_or_none(val: Any) -> Any:
    """Convert dict/list to JSON string for JSONB column, or None."""
    if val is None:
        return None
    if isinstance(val, dict | list):
        return json.dumps(val, ensure_ascii=False)
    return None
