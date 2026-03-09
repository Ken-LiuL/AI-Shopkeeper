"""YiyaoFullSyncer — 美团买药全量数据同步（CDP 拦截模式）。

策略：
  * 导航到 yiyao.meituan.com SPA 各页面
  * 用 CDP 拦截页面自身发出的 API 响应（绕过 h5guard mtgsig）
  * 翻页通过 JS 模拟点击"下一页"按钮 + 继续拦截
  * 抓取: 商品、订单、评价、销售统计、退款、门店信息
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# 常量
WM_POI_ID = "30850916"
REGION_ID = "1000420100"
REGION_VERSION = "1763630401"
ACCT_ID = "264097650"

# yiyao SPA 页面路径
PAGE_PRODUCTS = (
    f"/page/product/list?wmPoiId={WM_POI_ID}"
    f"&region_id={REGION_ID}&region_version={REGION_VERSION}"
)
PAGE_ORDERS = (
    f"/page/order/list?wmPoiId={WM_POI_ID}"
    f"&region_id={REGION_ID}&region_version={REGION_VERSION}"
)
PAGE_REVIEWS = (
    f"/page/evaluate/list?wmPoiId={WM_POI_ID}"
    f"&region_id={REGION_ID}&region_version={REGION_VERSION}"
)
PAGE_DATA = (
    f"/page/data/business?wmPoiId={WM_POI_ID}"
    f"&region_id={REGION_ID}&region_version={REGION_VERSION}"
)
PAGE_HOME = (
    f"/main/frame?wmPoiId={WM_POI_ID}"
    f"&region_id={REGION_ID}&region_version={REGION_VERSION}"
)

# CDP 拦截 URL 匹配模式
PATTERNS_PRODUCTS = ["searchSpListByCond", "indexPageModel", "searchListPage"]
PATTERNS_ORDERS = ["order/list/interval", "order/list/count", "orderList"]
PATTERNS_REVIEWS = ["comment/r/list", "pageQueryEvaluate", "evaluate/r/"]
PATTERNS_STATS = ["businessOverview", "businessDataStat", "indexOverview"]
PATTERNS_REFUNDS = ["refundOrderCount", "refund/list", "refundOrder"]
PATTERNS_POI = ["poiInfo/get", "poi/info"]
PATTERNS_MENU = ["poi/menu/list", "menu/list"]

# 翻页按钮 JS 选择器（美团 SPA 常见的分页组件）
JS_CLICK_NEXT = """
(function() {
    // 尝试多种"下一页"按钮选择器
    var selectors = [
        '.ant-pagination-next:not(.ant-pagination-disabled)',
        '.next-btn:not(.disabled)',
        '.pagination .next:not(.disabled)',
        '[class*="next"]:not([class*="disabled"])',
        'button[aria-label="next"]',
        '.el-pagination .btn-next:not(:disabled)',
    ];
    for (var i = 0; i < selectors.length; i++) {
        var btn = document.querySelector(selectors[i]);
        if (btn) {
            btn.click();
            return true;
        }
    }
    return false;
})()
"""

# 检查是否有下一页
JS_HAS_NEXT = """
(function() {
    var selectors = [
        '.ant-pagination-next:not(.ant-pagination-disabled)',
        '.next-btn:not(.disabled)',
        '.pagination .next:not(.disabled)',
        '[class*="next"]:not([class*="disabled"])',
        'button[aria-label="next"]',
        '.el-pagination .btn-next:not(:disabled)',
    ];
    for (var i = 0; i < selectors.length; i++) {
        var btn = document.querySelector(selectors[i]);
        if (btn) return true;
    }
    return false;
})()
"""


@dataclass
class SyncResult:
    syncer: str
    success: bool
    records: int
    error: str | None = None
    pages: int = 0


def _parse_intercepted_json(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 CDP 拦截的响应中提取 JSON 数据。

    Returns: 成功解析的 JSON 响应列表 [{url, data}]
    """
    results = []
    for item in captured:
        body = item.get("body", "")
        if not body:
            continue
        try:
            data = json.loads(body)
            results.append({"url": item.get("url", ""), "data": data})
        except json.JSONDecodeError:
            logger.debug("非 JSON 响应: %s → %s", item.get("url", "")[:60], body[:100])
    return results


def _extract_list_from_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从 API 响应中提取列表数据，兼容多种嵌套格式。"""
    if not isinstance(data, dict):
        return []

    # 检查 code
    code = data.get("code")
    if code is not None and code != 0:
        return []

    # 尝试常见的数据路径
    payload = data.get("data") or data

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        # 常见列表字段名
        for key in (
            "list", "items", "records", "rows",
            "productList", "orderList", "orders",
            "commentList", "evaluateList", "reviewList",
            "spuList", "skuList", "goodsList",
            "wmPoiMenuList", "menuList",
        ):
            val = payload.get(key)
            if isinstance(val, list) and val:
                return val

        # 嵌套 data.data
        inner = payload.get("data")
        if isinstance(inner, dict):
            return _extract_list_from_response({"data": inner})
        if isinstance(inner, list):
            return inner

    return []


def _extract_total_from_response(data: dict[str, Any]) -> int:
    """从 API 响应中提取 total count。"""
    if not isinstance(data, dict):
        return 0
    payload = data.get("data") or data
    if isinstance(payload, dict):
        for key in ("total", "totalCount", "totalNum", "count"):
            val = payload.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
    return 0


class YiyaoFullSyncer:
    """全量同步器，通过 CDP 拦截 yiyao SPA 页面的 API 响应获取数据。"""

    def __init__(self, client: Any, pool: Any, wm_poi_id: str, days_back: int = 90) -> None:
        self.client = client
        self.pool = pool
        self.wm_poi_id = str(wm_poi_id)
        self.days_back = days_back

    # ── Public ────────────────────────────────────────────────────────────

    async def sync_all(self) -> list[SyncResult]:
        """依次同步所有数据类型，返回结果列表。"""
        results = []
        tasks = [
            ("商品", self.sync_products),
            ("订单", self.sync_orders),
            ("评价", self.sync_reviews),
            ("销售统计", self.sync_stats),
            ("退款", self.sync_refunds),
            ("日报指标", self.sync_daily_metrics),
            ("销售历史", self.sync_sales_history),
            ("促销活动", self.sync_promotions),
            ("评价分析", self.sync_review_analysis),
        ]
        for name, fn in tasks:
            logger.info("开始同步: %s", name)
            try:
                result = await fn()
                results.append(result)
                logger.info(
                    "完成同步: %s → %d 条，%d 页，success=%s",
                    name,
                    result.records,
                    result.pages,
                    result.success,
                )
            except Exception as exc:
                logger.exception("同步失败: %s", name)
                results.append(SyncResult(syncer=name, success=False, records=0, error=str(exc)))
        return results

    # ── 商品 ──────────────────────────────────────────────────────────────

    async def sync_products(self) -> SyncResult:
        """导航到商品列表页，CDP 拦截商品数据，自动翻页。"""
        all_items: list[dict] = []
        pages = 0

        # 第一页：导航到商品列表页，自动触发 API
        captured = await self.client.intercept_navigate(
            PAGE_PRODUCTS,
            PATTERNS_PRODUCTS,
            timeout=30.0,
            wait_after_load=8.0,
        )

        parsed = _parse_intercepted_json(captured)
        for resp in parsed:
            items = _extract_list_from_response(resp["data"])
            if items:
                all_items.extend(items)
                pages += 1
                logger.info("商品第1页: 获取 %d 条", len(items))

        # 翻页
        max_pages = 50  # 安全上限
        while pages < max_pages:
            has_next = await self.client.evaluate_js(JS_HAS_NEXT)
            if not has_next:
                break

            page_captured = await self.client.click_and_intercept(
                JS_CLICK_NEXT,
                PATTERNS_PRODUCTS,
                timeout=20.0,
                wait_after_click=3.0,
            )

            page_parsed = _parse_intercepted_json(page_captured)
            page_items: list[dict] = []
            for resp in page_parsed:
                items = _extract_list_from_response(resp["data"])
                page_items.extend(items)

            if not page_items:
                logger.info("商品翻页结束: 第 %d 页无数据", pages + 1)
                break

            all_items.extend(page_items)
            pages += 1
            logger.info("商品第%d页: 获取 %d 条，累计 %d", pages, len(page_items), len(all_items))
            await asyncio.sleep(1.0)

        if all_items:
            await self._save_products(all_items)

        return SyncResult(syncer="products", success=True, records=len(all_items), pages=pages)

    # ── 订单 ──────────────────────────────────────────────────────────────

    async def sync_orders(self) -> SyncResult:
        """导航到订单列表页，CDP 拦截订单数据，自动翻页。"""
        all_orders: list[dict] = []
        pages = 0

        # 第一页：导航到订单页
        captured = await self.client.intercept_navigate(
            PAGE_ORDERS,
            PATTERNS_ORDERS,
            timeout=30.0,
            wait_after_load=8.0,
        )

        parsed = _parse_intercepted_json(captured)
        for resp in parsed:
            items = _extract_list_from_response(resp["data"])
            if items:
                all_orders.extend(items)
                pages += 1
                logger.info("订单第1页: 获取 %d 条", len(items))

        # 翻页
        max_pages = 100
        while pages < max_pages:
            has_next = await self.client.evaluate_js(JS_HAS_NEXT)
            if not has_next:
                break

            page_captured = await self.client.click_and_intercept(
                JS_CLICK_NEXT,
                PATTERNS_ORDERS,
                timeout=20.0,
                wait_after_click=3.0,
            )

            page_parsed = _parse_intercepted_json(page_captured)
            page_items: list[dict] = []
            for resp in page_parsed:
                items = _extract_list_from_response(resp["data"])
                page_items.extend(items)

            if not page_items:
                logger.info("订单翻页结束: 第 %d 页无数据", pages + 1)
                break

            all_orders.extend(page_items)
            pages += 1
            logger.info("订单第%d页: 获取 %d 条，累计 %d", pages, len(page_items), len(all_orders))
            await asyncio.sleep(1.0)

        if all_orders:
            await self._save_raw(all_orders, "qnh_orders")

        return SyncResult(syncer="orders", success=True, records=len(all_orders), pages=pages)

    # ── 评价 ──────────────────────────────────────────────────────────────

    async def sync_reviews(self) -> SyncResult:
        """导航到评价列表页，CDP 拦截评价数据，自动翻页。"""
        all_reviews: list[dict] = []
        pages = 0

        captured = await self.client.intercept_navigate(
            PAGE_REVIEWS,
            PATTERNS_REVIEWS,
            timeout=30.0,
            wait_after_load=8.0,
        )

        parsed = _parse_intercepted_json(captured)
        for resp in parsed:
            items = _extract_list_from_response(resp["data"])
            if items:
                all_reviews.extend(items)
                pages += 1
                logger.info("评价第1页: 获取 %d 条", len(items))

        # 翻页
        max_pages = 50
        while pages < max_pages:
            has_next = await self.client.evaluate_js(JS_HAS_NEXT)
            if not has_next:
                break

            page_captured = await self.client.click_and_intercept(
                JS_CLICK_NEXT,
                PATTERNS_REVIEWS,
                timeout=20.0,
                wait_after_click=3.0,
            )

            page_parsed = _parse_intercepted_json(page_captured)
            page_items: list[dict] = []
            for resp in page_parsed:
                items = _extract_list_from_response(resp["data"])
                page_items.extend(items)

            if not page_items:
                break

            all_reviews.extend(page_items)
            pages += 1
            logger.info("评价第%d页: 获取 %d 条，累计 %d", pages, len(page_items), len(all_reviews))
            await asyncio.sleep(1.0)

        if all_reviews:
            await self._save_raw(all_reviews, "qnh_reviews")

        return SyncResult(syncer="reviews", success=True, records=len(all_reviews), pages=pages)

    # ── 销售统计 ──────────────────────────────────────────────────────────

    async def sync_stats(self) -> SyncResult:
        """导航到数据中心页，CDP 拦截业务概览和统计数据。"""
        captured = await self.client.intercept_navigate(
            PAGE_DATA,
            PATTERNS_STATS,
            timeout=30.0,
            wait_after_load=10.0,
        )

        parsed = _parse_intercepted_json(captured)
        all_stats: list[dict] = []

        for resp in parsed:
            data = resp.get("data", {})
            # businessOverview 通常返回单个对象或列表
            items = _extract_list_from_response(data)
            if items:
                all_stats.extend(items)
            elif isinstance(data.get("data"), dict):
                # 单个概览对象，包装为列表
                all_stats.append(data["data"])

        if not all_stats and parsed:
            # 如果解析列表失败，把整个 data 部分存起来
            for resp in parsed:
                raw_data = resp.get("data", {}).get("data") or resp.get("data", {})
                if isinstance(raw_data, dict) and raw_data:
                    all_stats.append(raw_data)

        if all_stats:
            await self._save_raw(all_stats, "qnh_store_metrics")

        return SyncResult(
            syncer="metrics",
            success=True,
            records=len(all_stats),
            pages=1 if all_stats else 0,
        )

    # ── 退款 ──────────────────────────────────────────────────────────────

    async def sync_refunds(self) -> SyncResult:
        """从首页/订单页 CDP 拦截退款统计数据；也回退从订单中提取。"""
        if not self.pool:
            return SyncResult(syncer="refunds", success=False, records=0, error="DB pool unavailable")

        await self._ensure_refunds_table()

        refund_items: list[dict[str, Any]] = []
        pages = 0

        # 方式1: 导航到首页，拦截退款相关响应
        captured = await self.client.intercept_navigate(
            PAGE_HOME,
            PATTERNS_REFUNDS,
            timeout=25.0,
            wait_after_load=8.0,
        )

        parsed = _parse_intercepted_json(captured)
        for resp in parsed:
            data = resp.get("data", {})
            items = _extract_list_from_response(data)
            if items:
                refund_items.extend(items)
                pages += 1

        # 方式2: 导航到订单页拦截退款
        if not refund_items:
            captured2 = await self.client.intercept_navigate(
                PAGE_ORDERS,
                PATTERNS_REFUNDS,
                timeout=25.0,
                wait_after_load=8.0,
            )
            parsed2 = _parse_intercepted_json(captured2)
            for resp in parsed2:
                data = resp.get("data", {})
                items = _extract_list_from_response(data)
                if items:
                    refund_items.extend(items)
                    pages += 1

        # 方式3: 从已存储的订单数据回退提取
        if not refund_items:
            logger.warning("退款 CDP 拦截无数据，回退为订单退款状态提取")
            refund_items = await self._extract_refunds_from_orders_raw()
            pages = 1 if refund_items else 0

        saved = await self._save_refunds(refund_items)
        return SyncResult(syncer="refunds", success=True, records=saved, pages=pages)

    # ── 日报指标 ETL ─────────────────────────────────────────────────────

    async def sync_daily_metrics(self) -> SyncResult:
        """从 qnh_store_metrics_raw 解析写入 qnh_daily_metrics + qnh_dataset_records。"""
        if not self.pool:
            return SyncResult(syncer="daily_metrics", success=False, records=0, error="DB pool unavailable")

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_daily_metrics (
                    id SERIAL PRIMARY KEY,
                    date DATE UNIQUE NOT NULL,
                    order_count INTEGER DEFAULT 0,
                    gmv NUMERIC(12,2) DEFAULT 0,
                    actual_revenue NUMERIC(12,2) DEFAULT 0,
                    avg_order_value NUMERIC(10,2) DEFAULT 0,
                    refund_count INTEGER DEFAULT 0,
                    refund_rate NUMERIC(5,4) DEFAULT 0,
                    new_customers INTEGER DEFAULT 0,
                    synced_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_dataset_records (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    metric_name VARCHAR(100) NOT NULL,
                    metric_value NUMERIC(12,2),
                    source VARCHAR(50) DEFAULT 'yiyao_sync',
                    synced_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(date, metric_name)
                )
                """
            )

            latest_synced_at = await conn.fetchval(
                "SELECT synced_at FROM qnh_store_metrics_raw ORDER BY created_at DESC LIMIT 1"
            )
            if not latest_synced_at:
                return SyncResult(syncer="daily_metrics", success=True, records=0, pages=0)

            rows = await conn.fetch(
                """
                SELECT raw_data
                FROM qnh_store_metrics_raw
                WHERE synced_at = $1
                ORDER BY id ASC
                """,
                latest_synced_at,
            )
            if not rows:
                return SyncResult(syncer="daily_metrics", success=True, records=0, pages=0)

            metric_rows: list[tuple[Any, ...]] = []
            dataset_rows: list[tuple[Any, ...]] = []

            for row in rows:
                raw = row["raw_data"] or {}
                metric_date = self._parse_date(raw.get("date") or raw.get("statDate") or raw.get("day"))
                if not metric_date:
                    continue
                order_count = self._to_int(raw.get("orderCount") or raw.get("validOrderCount") or raw.get("orderNum"))
                gmv = self._to_float(raw.get("gmv") or raw.get("validOrderAmount") or raw.get("saleAmount"))
                actual_revenue = self._to_float(
                    raw.get("actualRevenue") or raw.get("paidAmount") or raw.get("actualPayAmount")
                )
                avg_order_value = self._to_float(
                    raw.get("avgOrderValue") or raw.get("customerPrice") or raw.get("客单价")
                )
                refund_count = self._to_int(raw.get("refundCount") or raw.get("refundNum"))
                refund_rate = self._to_float(raw.get("refundRate") or raw.get("stockoutRefundRate"))
                new_customers = self._to_int(raw.get("newCustomers") or raw.get("newCustomerCount"))

                metric_rows.append(
                    (
                        metric_date,
                        order_count,
                        gmv,
                        actual_revenue,
                        avg_order_value,
                        refund_count,
                        refund_rate,
                        new_customers,
                    )
                )
                dataset_rows.extend(
                    [
                        (metric_date, "order_count", order_count),
                        (metric_date, "gmv", gmv),
                        (metric_date, "actual_revenue", actual_revenue),
                        (metric_date, "avg_order_value", avg_order_value),
                        (metric_date, "refund_count", refund_count),
                        (metric_date, "refund_rate", refund_rate),
                        (metric_date, "new_customers", new_customers),
                    ]
                )

            if metric_rows:
                await conn.executemany(
                    """
                    INSERT INTO qnh_daily_metrics
                        (date, order_count, gmv, actual_revenue, avg_order_value, refund_count, refund_rate, new_customers, synced_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())
                    ON CONFLICT (date) DO UPDATE SET
                        order_count = EXCLUDED.order_count,
                        gmv = EXCLUDED.gmv,
                        actual_revenue = EXCLUDED.actual_revenue,
                        avg_order_value = EXCLUDED.avg_order_value,
                        refund_count = EXCLUDED.refund_count,
                        refund_rate = EXCLUDED.refund_rate,
                        new_customers = EXCLUDED.new_customers,
                        synced_at = NOW()
                    """,
                    metric_rows,
                )
            if dataset_rows:
                await conn.executemany(
                    """
                    INSERT INTO qnh_dataset_records (date, metric_name, metric_value, source, synced_at)
                    VALUES ($1, $2, $3, 'yiyao_sync', NOW())
                    ON CONFLICT (date, metric_name) DO UPDATE SET
                        metric_value = EXCLUDED.metric_value,
                        source = EXCLUDED.source,
                        synced_at = NOW()
                    """,
                    dataset_rows,
                )

        return SyncResult(syncer="daily_metrics", success=True, records=len(metric_rows), pages=1)

    # ── 销售历史 ETL ─────────────────────────────────────────────────────

    async def sync_sales_history(self) -> SyncResult:
        """从 qnh_orders_raw 聚合每天每商品销量和销售额。"""
        if not self.pool:
            return SyncResult(syncer="sales_history", success=False, records=0, error="DB pool unavailable")

        rows_to_upsert: list[tuple[Any, ...]] = []

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_sales_history (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    spu_id VARCHAR(100) NOT NULL,
                    product_name TEXT,
                    quantity_sold INTEGER DEFAULT 0,
                    revenue NUMERIC(12,2) DEFAULT 0,
                    synced_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(date, spu_id)
                )
                """
            )
            rows = await conn.fetch(
                """
                SELECT raw_data
                FROM qnh_orders_raw
                ORDER BY created_at DESC
                LIMIT 5000
                """
            )

            aggregate: dict[tuple[date, str], dict[str, Any]] = {}
            for row in rows:
                raw = row["raw_data"] or {}
                order_date = self._parse_date(raw.get("orderTime") or raw.get("createTime") or raw.get("orderDate"))
                if not order_date:
                    continue
                for item in self._extract_order_items(raw):
                    spu_id = str(
                        item.get("spuId")
                        or item.get("skuId")
                        or item.get("productId")
                        or item.get("id")
                        or ""
                    ).strip()
                    if not spu_id:
                        continue
                    product_name = str(item.get("name") or item.get("skuName") or item.get("productName") or "")
                    qty = self._to_int(item.get("qty") or item.get("count") or item.get("quantity") or item.get("num"))
                    line_amount = self._to_float(
                        item.get("amount")
                        or item.get("totalAmount")
                        or item.get("lineAmount")
                        or item.get("payAmount")
                    )
                    if line_amount <= 0:
                        unit_price = self._to_float(item.get("price") or item.get("unitPrice"))
                        line_amount = unit_price * qty

                    key = (order_date, spu_id)
                    if key not in aggregate:
                        aggregate[key] = {
                            "product_name": product_name,
                            "quantity_sold": 0,
                            "revenue": 0.0,
                        }
                    aggregate[key]["quantity_sold"] += qty
                    aggregate[key]["revenue"] += line_amount
                    if not aggregate[key]["product_name"] and product_name:
                        aggregate[key]["product_name"] = product_name

            rows_to_upsert = [
                (d, spu_id, data["product_name"], data["quantity_sold"], data["revenue"])
                for (d, spu_id), data in aggregate.items()
            ]
            if rows_to_upsert:
                await conn.executemany(
                    """
                    INSERT INTO qnh_sales_history (date, spu_id, product_name, quantity_sold, revenue, synced_at)
                    VALUES ($1,$2,$3,$4,$5,NOW())
                    ON CONFLICT (date, spu_id) DO UPDATE SET
                        product_name = EXCLUDED.product_name,
                        quantity_sold = EXCLUDED.quantity_sold,
                        revenue = EXCLUDED.revenue,
                        synced_at = NOW()
                    """,
                    rows_to_upsert,
                )

        return SyncResult(syncer="sales_history", success=True, records=len(rows_to_upsert), pages=1)

    # ── 促销（stub） ─────────────────────────────────────────────────────

    async def sync_promotions(self) -> SyncResult:
        """促销活动接口暂不稳定，先保留空表 + stub。"""
        if not self.pool:
            return SyncResult(syncer="promotions", success=False, records=0, error="DB pool unavailable")

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_promotions (
                    id SERIAL PRIMARY KEY,
                    promotion_id VARCHAR(100) UNIQUE NOT NULL,
                    promotion_type VARCHAR(50),
                    title TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    product_ids JSONB,
                    discount_rule TEXT,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
        logger.info("qnh_promotions 当前为 stub，同步暂不支持公开 API")
        return SyncResult(syncer="promotions", success=True, records=0, pages=0)

    # ── 评价分析 ETL ─────────────────────────────────────────────────────

    async def sync_review_analysis(self) -> SyncResult:
        """从 qnh_reviews_raw 提取评价文本做关键词情感分析。"""
        if not self.pool:
            return SyncResult(syncer="review_analysis", success=False, records=0, error="DB pool unavailable")

        positive_words = ["好", "快", "准时", "新鲜", "划算", "满意", "不错", "推荐", "方便", "专业"]
        negative_words = ["差", "慢", "破损", "过期", "贵", "态度差", "错发", "少发", "假", "投诉"]

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_review_analysis (
                    id SERIAL PRIMARY KEY,
                    review_id VARCHAR(100) UNIQUE,
                    product_id VARCHAR(100),
                    product_name TEXT,
                    rating INTEGER,
                    content TEXT,
                    sentiment VARCHAR(20),
                    keywords TEXT[],
                    analyzed_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            rows = await conn.fetch(
                """
                SELECT raw_data
                FROM qnh_reviews_raw
                ORDER BY created_at DESC
                LIMIT 3000
                """
            )

            upserts: list[tuple[Any, ...]] = []
            for row in rows:
                raw = row["raw_data"] or {}
                review_id = str(raw.get("reviewId") or raw.get("id") or raw.get("evaluateId") or "").strip()
                if not review_id:
                    continue
                product_id = str(raw.get("skuId") or raw.get("spuId") or raw.get("productId") or "")
                product_name = str(raw.get("skuName") or raw.get("productName") or raw.get("name") or "")
                rating = self._to_int(raw.get("rating") or raw.get("star") or raw.get("score"))
                content = str(raw.get("content") or raw.get("comment") or raw.get("evaluateContent") or "").strip()

                pos_hits = [w for w in positive_words if w in content]
                neg_hits = [w for w in negative_words if w in content]
                if len(pos_hits) > len(neg_hits):
                    sentiment = "positive"
                elif len(neg_hits) > len(pos_hits):
                    sentiment = "negative"
                elif rating >= 4:
                    sentiment = "positive"
                elif rating <= 2:
                    sentiment = "negative"
                else:
                    sentiment = "neutral"
                keywords = list(dict.fromkeys(pos_hits + neg_hits))

                upserts.append(
                    (review_id, product_id or None, product_name or None, rating, content, sentiment, keywords)
                )

            if upserts:
                await conn.executemany(
                    """
                    INSERT INTO qnh_review_analysis
                        (review_id, product_id, product_name, rating, content, sentiment, keywords, analyzed_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
                    ON CONFLICT (review_id) DO UPDATE SET
                        product_id = EXCLUDED.product_id,
                        product_name = EXCLUDED.product_name,
                        rating = EXCLUDED.rating,
                        content = EXCLUDED.content,
                        sentiment = EXCLUDED.sentiment,
                        keywords = EXCLUDED.keywords,
                        analyzed_at = NOW()
                    """,
                    upserts,
                )

        return SyncResult(syncer="review_analysis", success=True, records=len(upserts), pages=1)

    # ── DB 写入 ───────────────────────────────────────────────────────────

    async def _save_products(self, items: list[dict]) -> None:
        """商品数据结构化写入 qnh_products。"""
        if not self.pool or not items:
            return
        now = datetime.now(UTC)
        rows = []
        for item in items:
            spu_id = str(item.get("id") or item.get("spuId") or "")
            if not spu_id:
                continue
            sku_id = str(item.get("skuId") or "")

            # 解析状态
            sale_status = item.get("saleStatus") or item.get("status")
            if sale_status == 1 or sale_status == "on":
                status = "on"
            elif sale_status == 0 or sale_status == "off":
                status = "off"
            else:
                status = str(sale_status) if sale_status is not None else "unknown"

            rows.append((
                spu_id,
                sku_id,
                str(item.get("name") or item.get("spuName") or ""),
                str(item.get("brandName") or item.get("brand") or ""),
                str(item.get("spec") or item.get("skuSpec") or ""),
                float(item.get("price") or item.get("retailPrice") or 0),
                int(item.get("stock") or item.get("stockNum") or item.get("stockQuantity") or 0),
                str(item.get("categoryName") or item.get("category") or ""),
                str(item.get("imageUrl") or item.get("pic") or ""),
                str(item.get("barcode") or item.get("upc") or ""),
                status,
                json.dumps(item, ensure_ascii=False, default=str),
                now,
            ))

        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO qnh_products
                    (spu_id, sku_id, name, brand, spec, retail_price, stock,
                     category, image_url, barcode, status, extra, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13)
                ON CONFLICT (spu_id, sku_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    brand = EXCLUDED.brand,
                    spec = EXCLUDED.spec,
                    retail_price = EXCLUDED.retail_price,
                    stock = EXCLUDED.stock,
                    category = EXCLUDED.category,
                    image_url = EXCLUDED.image_url,
                    barcode = EXCLUDED.barcode,
                    status = EXCLUDED.status,
                    extra = EXCLUDED.extra,
                    synced_at = EXCLUDED.synced_at
                """,
                rows,
            )
        logger.info("商品写入完成: %d 条", len(rows))

    # raw 表白名单（防止 SQL 注入）
    _ALLOWED_RAW_TABLES = {
        "qnh_orders", "qnh_reviews", "qnh_store_metrics",
        "qnh_refunds", "qnh_inventory", "qnh_traffic",
    }

    async def _save_raw(self, items: list[dict], table: str) -> None:
        """原始 JSON 写入 raw 表（MD5 去重，避免重复插入）。"""
        if not self.pool or not items:
            return
        if table not in self._ALLOWED_RAW_TABLES:
            logger.error("非法表名: %s，跳过写入", table)
            return

        import hashlib

        now = datetime.now(UTC).isoformat()
        raw_table = f"{table}_raw"
        async with self.pool.acquire() as conn:
            # 确保表存在（含去重用的 content_hash 列）
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {raw_table} (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR(50) DEFAULT 'yiyao_sync',
                    raw_data JSONB,
                    content_hash VARCHAR(32),
                    synced_at TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            # 确保 content_hash 唯一索引存在
            await conn.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{raw_table}_hash
                ON {raw_table} (content_hash)
            """)

            inserted = 0
            for item in items:
                raw_json = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                content_hash = hashlib.md5(raw_json.encode()).hexdigest()  # noqa: S324
                try:
                    await conn.execute(
                        f"""
                        INSERT INTO {raw_table} (source, raw_data, content_hash, synced_at)
                        VALUES ('yiyao_sync', $1::jsonb, $2, $3)
                        ON CONFLICT (content_hash) DO NOTHING
                        """,
                        raw_json, content_hash, now,
                    )
                    inserted += 1
                except Exception:
                    pass

        logger.info("%s 写入完成: %d/%d 条（去重后）", raw_table, inserted, len(items))

    async def _ensure_refunds_table(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS qnh_refunds (
                    id SERIAL PRIMARY KEY,
                    tenant_id VARCHAR(100),
                    refund_id VARCHAR(100) UNIQUE NOT NULL,
                    order_id VARCHAR(100),
                    channel VARCHAR(50) DEFAULT 'meituan',
                    sku_id VARCHAR(100),
                    sku_name TEXT,
                    refund_reason TEXT,
                    refund_amount NUMERIC(10,2) DEFAULT 0,
                    refund_status VARCHAR(50),
                    refund_time TIMESTAMP,
                    resolved_time TIMESTAMP,
                    extra JSONB,
                    synced_at TIMESTAMP DEFAULT NOW()
                )
                """
            )

    async def _save_refunds(self, items: list[dict[str, Any]]) -> int:
        if not items or not self.pool:
            return 0
        rows: list[tuple[Any, ...]] = []
        for item in items:
            refund_id = str(item.get("refund_id") or item.get("refundId") or item.get("id") or "").strip()
            if not refund_id:
                continue
            rows.append(
                (
                    "meituan",
                    refund_id,
                    str(item.get("order_id") or item.get("orderId") or item.get("bizOrderId") or ""),
                    "meituan",
                    str(item.get("sku_id") or item.get("skuId") or item.get("spuId") or ""),
                    str(item.get("sku_name") or item.get("skuName") or item.get("productName") or ""),
                    str(item.get("refund_reason") or item.get("reason") or item.get("refundReason") or ""),
                    self._to_float(item.get("refund_amount") or item.get("refundAmount") or item.get("amount")),
                    str(item.get("refund_status") or item.get("status") or item.get("refundStatus") or ""),
                    self._parse_datetime(
                        item.get("refund_time") or item.get("refundTime") or item.get("applyTime")
                    ),
                    self._parse_datetime(
                        item.get("resolved_time") or item.get("resolvedTime") or item.get("finishTime")
                    ),
                    json.dumps(item, ensure_ascii=False, default=str),
                )
            )
        if not rows:
            return 0

        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO qnh_refunds (tenant_id, refund_id, order_id, channel, sku_id, sku_name,
                    refund_reason, refund_amount, refund_status, refund_time, resolved_time, extra, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,NOW())
                ON CONFLICT (refund_id) DO UPDATE SET
                    order_id = EXCLUDED.order_id,
                    channel = EXCLUDED.channel,
                    sku_id = EXCLUDED.sku_id,
                    sku_name = EXCLUDED.sku_name,
                    refund_reason = EXCLUDED.refund_reason,
                    refund_amount = EXCLUDED.refund_amount,
                    refund_status = EXCLUDED.refund_status,
                    refund_time = EXCLUDED.refund_time,
                    resolved_time = EXCLUDED.resolved_time,
                    extra = EXCLUDED.extra,
                    synced_at = NOW()
                """,
                rows,
            )
        return len(rows)

    async def _extract_refunds_from_orders_raw(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT raw_data
                FROM qnh_orders_raw
                WHERE raw_data IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 5000
                """
            )

        results: list[dict[str, Any]] = []
        for row in rows:
            raw = row["raw_data"] or {}
            status = str(raw.get("status") or raw.get("orderStatus") or "").lower()
            if status not in {"refunded", "refund", "已退款"}:
                continue
            order_id = str(raw.get("orderId") or raw.get("id") or "")
            refund_id = str(raw.get("refundId") or "").strip() or f"order-refund-{order_id}"
            items = self._extract_order_items(raw)
            if not items:
                items = [{}]
            for item in items:
                results.append(
                    {
                        "refund_id": refund_id,
                        "order_id": order_id,
                        "sku_id": str(item.get("skuId") or item.get("spuId") or ""),
                        "sku_name": str(
                            item.get("name") or item.get("skuName") or item.get("productName") or ""
                        ),
                        "refund_reason": str(
                            raw.get("refundReason") or raw.get("cancelReason") or "status=refunded"
                        ),
                        "refund_amount": (
                            raw.get("refundAmount")
                            or raw.get("paidAmount")
                            or raw.get("totalAmount")
                            or 0
                        ),
                        "refund_status": str(raw.get("refundStatus") or "completed"),
                        "refund_time": (
                            raw.get("refundTime") or raw.get("updateTime") or raw.get("orderTime")
                        ),
                        "resolved_time": raw.get("resolvedTime") or raw.get("updateTime"),
                        "source": "orders_fallback",
                    }
                )
        return results

    @staticmethod
    def _extract_order_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("items", "orderItems", "productList", "goodsList", "skuList"):
            val = raw.get(key)
            if isinstance(val, list):
                return [v for v in val if isinstance(v, dict)]
        for outer in ("detail", "extInfo", "data"):
            val = raw.get(outer)
            if isinstance(val, dict):
                nested = YiyaoFullSyncer._extract_order_items(val)
                if nested:
                    return nested
        return []

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=UTC)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            text = text.replace("Z", "+00:00")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.replace(tzinfo=UTC)
                except ValueError:
                    continue
            try:
                dt = datetime.fromisoformat(text)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                return None
        return None

    @classmethod
    def _parse_date(cls, value: Any) -> date | None:
        dt = cls._parse_datetime(value)
        if dt:
            return dt.date()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    @staticmethod
    def _to_int(value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
