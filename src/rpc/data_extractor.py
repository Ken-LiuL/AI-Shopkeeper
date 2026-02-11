"""数据提取器 — 解析美团 API 响应 JSON，存入 PostgreSQL competitor_* 表。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


class DataExtractor:
    """从 mitmproxy 拦截的 API 响应中提取结构化数据并存库。

    Usage:
        extractor = DataExtractor(db_pool)
        # 由 MeituanProxy 回调
        await extractor.process_response(url, json_data)
    """

    def __init__(self, db_pool: Any = None):
        self.db_pool = db_pool
        self._handlers: dict[str, Any] = {
            # 搜索结果
            "/api/v8/poi/food": self._handle_search_results,
            "/search/": self._handle_search_results,
            "/meituan.waimai.c.search": self._handle_search_results,
            # 店铺详情
            "/api/v8/poi/detail": self._handle_store_detail,
            "/poi/detail": self._handle_store_detail,
            # 商品列表
            "/api/v8/poi/food/v2": self._handle_product_list,
            "/food/list": self._handle_product_list,
            "/meituan.waimai.c.poi.food": self._handle_product_list,
        }

    async def process_response(self, url: str, data: dict) -> Optional[dict]:
        """根据 URL 模式分发到对应的处理器。"""
        for pattern, handler in self._handlers.items():
            if pattern in url:
                try:
                    result = await handler(data)
                    if result:
                        logger.info(f"Extracted data from {pattern}: {result.get('type', 'unknown')}")
                    return result
                except Exception as e:
                    logger.error(f"Extraction failed for {url}: {e}")
                    return None
        return None

    # ── Search Results ───────────────────────────────────────────────

    async def _handle_search_results(self, data: dict) -> Optional[dict]:
        """解析搜索结果 API 响应。"""
        # 美团搜索响应结构通常为: data.search_result / data.poi_list / data.items
        items = (
            _deep_get(data, "data", "search_result")
            or _deep_get(data, "data", "poi_list")
            or _deep_get(data, "data", "items")
            or _deep_get(data, "data", "searchResult")
            or _deep_get(data, "data", "poiList")
            or []
        )

        if not isinstance(items, list):
            return None

        stores = []
        products = []

        for item in items:
            # 提取店铺信息
            store = self._extract_store(item)
            if store:
                stores.append(store)

            # 提取商品信息
            product_list = (
                item.get("products")
                or item.get("food_list")
                or item.get("foods")
                or item.get("spuList")
                or []
            )
            for p in product_list:
                product = self._extract_product(p, store_name=store.get("name", "") if store else "")
                if product:
                    products.append(product)

        # 存库
        if self.db_pool:
            await self._save_stores(stores)
            await self._save_products(products)

        return {
            "type": "search_results",
            "store_count": len(stores),
            "product_count": len(products),
            "stores": stores,
            "products": products,
        }

    # ── Store Detail ─────────────────────────────────────────────────

    async def _handle_store_detail(self, data: dict) -> Optional[dict]:
        """解析店铺详情 API 响应。"""
        detail = _deep_get(data, "data") or data
        store = self._extract_store(detail)

        if store and self.db_pool:
            await self._save_stores([store])

        return {"type": "store_detail", "store": store} if store else None

    # ── Product List ─────────────────────────────────────────────────

    async def _handle_product_list(self, data: dict) -> Optional[dict]:
        """解析商品列表 API 响应。"""
        items = (
            _deep_get(data, "data", "food_list")
            or _deep_get(data, "data", "foods")
            or _deep_get(data, "data", "spuList")
            or _deep_get(data, "data", "items")
            or []
        )

        if not isinstance(items, list):
            return None

        products = []
        store_name = _deep_get(data, "data", "poi_name") or _deep_get(data, "data", "poiName") or ""

        for item in items:
            product = self._extract_product(item, store_name=store_name)
            if product:
                products.append(product)

        if products and self.db_pool:
            await self._save_products(products)

        return {"type": "product_list", "count": len(products), "products": products}

    # ── Field Extractors ─────────────────────────────────────────────

    def _extract_store(self, item: dict) -> Optional[dict]:
        """从 API 响应项中提取店铺字段。"""
        store_id = str(
            item.get("poi_id")
            or item.get("poiId")
            or item.get("id")
            or item.get("wmPoiId")
            or ""
        )
        name = (
            item.get("name")
            or item.get("poi_name")
            or item.get("poiName")
            or item.get("wmPoiName")
            or ""
        )
        if not name:
            return None

        return {
            "store_id": store_id,
            "name": name,
            "rating": _safe_float(
                item.get("wm_poi_score")
                or item.get("wmPoiScore")
                or item.get("rating")
                or item.get("score")
            ),
            "monthly_sales": _safe_int(
                item.get("month_sales_tip", "").replace("月售", "").replace("+", "").replace("单", "")
                if isinstance(item.get("month_sales_tip"), str) else
                item.get("monthSales")
                or item.get("monthlySales")
                or item.get("month_sales")
                or 0
            ),
            "distance_km": _safe_float(
                item.get("distance")
                or item.get("distance_km")
            ) / 1000 if _safe_float(item.get("distance")) > 100 else _safe_float(
                item.get("distance")
                or item.get("distance_km")
            ),
            "lat": _safe_float(item.get("latitude") or item.get("lat")),
            "lng": _safe_float(item.get("longitude") or item.get("lng")),
            "category": (
                item.get("category_name")
                or item.get("categoryName")
                or item.get("category")
                or ""
            ),
        }

    def _extract_product(self, item: dict, store_name: str = "") -> Optional[dict]:
        """从 API 响应项中提取商品字段。"""
        product_id = str(
            item.get("spu_id")
            or item.get("spuId")
            or item.get("id")
            or item.get("product_id")
            or ""
        )
        name = (
            item.get("name")
            or item.get("spuName")
            or item.get("product_name")
            or item.get("title")
            or ""
        )
        if not name:
            return None

        # 价格：美团API中价格通常以分为单位
        raw_price = _safe_float(
            item.get("min_price")
            or item.get("price")
            or item.get("currentPrice")
            or item.get("retail_price")
        )
        price = raw_price / 100 if raw_price > 1000 else raw_price  # 分→元

        return {
            "product_id": product_id,
            "name": name,
            "price": price,
            "monthly_sales": _safe_int(
                item.get("month_sales")
                or item.get("monthSales")
                or item.get("sales_count")
                or item.get("saleCount")
            ),
            "rating": _safe_float(item.get("rating") or item.get("score")),
            "store_name": store_name,
            "category": item.get("category") or item.get("tag") or "",
        }

    # ── Keyword Stats ────────────────────────────────────────────────

    async def save_keyword_stats(
        self,
        keyword: str,
        result_count: int,
        avg_price: float,
        stores: list[dict],
    ) -> None:
        """保存搜索关键词统计到 competitor_keywords 表。"""
        if not self.db_pool:
            return

        now = datetime.now(CST)
        await self.db_pool.execute(
            """
            INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price, last_synced)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (keyword)
            DO UPDATE SET
                result_count = EXCLUDED.result_count,
                avg_price = EXCLUDED.avg_price,
                last_synced = EXCLUDED.last_synced
            """,
            keyword,
            result_count,  # 作为 search_volume 的近似值
            result_count,
            avg_price,
            now,
        )

    # ── DB Persistence ───────────────────────────────────────────────

    async def _save_stores(self, stores: list[dict]) -> int:
        if not self.db_pool or not stores:
            return 0

        now = datetime.now(CST)
        count = 0
        for s in stores:
            if not s.get("store_id") or not s.get("name"):
                continue
            try:
                await self.db_pool.execute(
                    """
                    INSERT INTO competitor_stores
                        (store_id, name, rating, monthly_sales, distance_km, lat, lng, category, last_synced)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (store_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        rating = EXCLUDED.rating,
                        monthly_sales = EXCLUDED.monthly_sales,
                        distance_km = EXCLUDED.distance_km,
                        lat = EXCLUDED.lat,
                        lng = EXCLUDED.lng,
                        category = EXCLUDED.category,
                        last_synced = EXCLUDED.last_synced
                    """,
                    s["store_id"], s["name"], s["rating"], s["monthly_sales"],
                    s["distance_km"], s["lat"], s["lng"], s["category"], now,
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to save store {s.get('store_id')}: {e}")

        logger.info(f"Saved {count}/{len(stores)} stores")
        return count

    async def _save_products(self, products: list[dict]) -> int:
        if not self.db_pool or not products:
            return 0

        now = datetime.now(CST)
        count = 0
        for p in products:
            if not p.get("product_id") or not p.get("name"):
                continue
            try:
                await self.db_pool.execute(
                    """
                    INSERT INTO competitor_products
                        (product_id, store_id, name, price, monthly_sales, rating, category, last_synced)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (product_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        monthly_sales = EXCLUDED.monthly_sales,
                        rating = EXCLUDED.rating,
                        category = EXCLUDED.category,
                        last_synced = EXCLUDED.last_synced
                    """,
                    p["product_id"], "", p["name"], p["price"],
                    p["monthly_sales"], p["rating"], p["category"], now,
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to save product {p.get('product_id')}: {e}")

        logger.info(f"Saved {count}/{len(products)} products")
        return count


# ── Helpers ──────────────────────────────────────────────────────────────────

def _deep_get(d: dict, *keys: str) -> Any:
    """安全地从嵌套 dict 中取值。"""
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)  # type: ignore
    return d
