"""YiyaoFullSyncer — 美团买药全量数据同步（自动翻页）。

使用 Xvfb + 非 headless Chrome 绕过 h5guard，自动抓取：
  - 商品列表（全量）
  - 订单历史（过去 N 天，自动翻页）
  - 评价列表（过去 N 天）
  - 销售统计（按日汇总）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# API 路径
API_PRODUCTS   = "/reuse/health/product/retail/r/searchListPageV2"
API_ORDERS     = "/waimai/order/list"      # 将在初始化时自动探测
API_REVIEWS    = "/reuse/health/evaluate/r/pageQueryEvaluate"
API_STATS      = "/reuse/health/data/r/businessDataStat"


@dataclass
class SyncResult:
    syncer: str
    success: bool
    records: int
    error: str | None = None
    pages: int = 0


class YiyaoFullSyncer:
    """全量同步器，每次运行自动翻页拉取所有数据。"""

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
        ]
        for name, fn in tasks:
            logger.info("开始同步: %s", name)
            try:
                result = await fn()
                results.append(result)
                logger.info(
                    "完成同步: %s → %d 条，%d 页，success=%s",
                    name, result.records, result.pages, result.success
                )
            except Exception as exc:
                logger.exception("同步失败: %s", name)
                results.append(SyncResult(syncer=name, success=False, records=0, error=str(exc)))
        return results

    # ── 商品 ──────────────────────────────────────────────────────────────

    async def sync_products(self) -> SyncResult:
        """全量拉取商品列表，自动翻页。"""
        page_num = 1
        page_size = 50
        total = 0
        pages = 0
        all_items: list[dict] = []

        # 先导航到商品管理页，让 h5guard 初始化正确的上下文
        await self.client.navigate_to("/merch/product/list")

        while True:
            resp = await self.client.execute_api(
                API_PRODUCTS,
                method="POST",
                body_params={
                    "wmPoiId": self.wm_poi_id,
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "needTag": 0,
                    "state": 0,
                    "saleStatus": 0,
                    "limitSale": 0,
                    "needCombinationSpu": -1,
                    "noStockAutoClear": -1,
                    "problemType": 1,
                    "noSingleDeliveryType": 0,
                },
            )

            if not isinstance(resp, dict):
                logger.warning("商品 API 返回非 JSON，跳过此页: %s", str(resp)[:100])
                break

            code = resp.get("code", -1)
            if code not in (0, None):
                logger.error("商品 API 错误: code=%s msg=%s", code, resp.get("msg") or resp.get("message"))
                break

            data = resp.get("data") or {}
            items = data.get("productList") or data.get("list") or []
            total_count = int(data.get("totalCount") or data.get("total") or 0)

            if not items:
                break

            all_items.extend(items)
            total += len(items)
            pages += 1
            logger.info("商品 page=%d, 本页=%d, 累计=%d/%d", page_num, len(items), total, total_count)

            if total >= total_count or len(items) < page_size:
                break
            page_num += 1
            await asyncio.sleep(0.5)  # 礼貌性延迟

        if all_items:
            await self._save_products(all_items)

        return SyncResult(syncer="products", success=total > 0, records=total, pages=pages,
                          error=None if total > 0 else "未获取到商品数据")

    # ── 订单 ──────────────────────────────────────────────────────────────

    async def sync_orders(self) -> SyncResult:
        """拉取过去 days_back 天的订单，自动翻页。"""
        end_date = date.today()
        start_date = end_date - timedelta(days=self.days_back)

        # 导航到订单页，让 h5guard 初始化
        await self.client.navigate_to("/order/list")

        page_num = 1
        page_size = 50
        total = 0
        pages = 0
        all_orders: list[dict] = []

        # 尝试多个可能的订单 API 路径
        order_apis = [
            "/waimai/order/list",
            "/order/list/page/history",
            "/reuse/health/order/r/pageQueryOrder",
        ]
        working_api = None

        for api in order_apis:
            try:
                test_resp = await self.client.execute_api(
                    api,
                    method="POST",
                    body_params={
                        "wmPoiId": self.wm_poi_id,
                        "pageNum": 1,
                        "pageSize": 1,
                        "startTime": start_date.strftime("%Y-%m-%d"),
                        "endTime": end_date.strftime("%Y-%m-%d"),
                    },
                )
                if isinstance(test_resp, dict) and test_resp.get("code") in (0, None):
                    working_api = api
                    logger.info("订单 API 探测成功: %s", api)
                    break
            except Exception:
                continue

        if not working_api:
            return SyncResult(syncer="orders", success=False, records=0, error="未找到可用的订单 API")

        while True:
            resp = await self.client.execute_api(
                working_api,
                method="POST",
                body_params={
                    "wmPoiId": self.wm_poi_id,
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "startTime": start_date.strftime("%Y-%m-%d"),
                    "endTime": end_date.strftime("%Y-%m-%d"),
                    "status": "",  # 全部状态
                },
            )

            if not isinstance(resp, dict):
                logger.warning("订单 API 返回非 JSON: %s", str(resp)[:100])
                break

            code = resp.get("code", -1)
            if code not in (0, None):
                logger.error("订单 API 错误: code=%s", code)
                break

            data = resp.get("data") or {}
            orders = (
                data.get("list") or data.get("orders") or
                data.get("orderList") or data.get("items") or []
            )
            total_count = int(data.get("total") or data.get("totalCount") or 0)

            if not orders:
                break

            all_orders.extend(orders)
            total += len(orders)
            pages += 1
            logger.info("订单 page=%d, 本页=%d, 累计=%d/%d", page_num, len(orders), total, total_count)

            if total >= total_count or len(orders) < page_size:
                break
            page_num += 1
            await asyncio.sleep(0.8)

        if all_orders:
            await self._save_raw(all_orders, "qnh_orders")

        return SyncResult(syncer="orders", success=True, records=total, pages=pages)

    # ── 评价 ──────────────────────────────────────────────────────────────

    async def sync_reviews(self) -> SyncResult:
        """拉取评价列表。"""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        await self.client.navigate_to("/merch/evaluate/list")

        page_num = 1
        page_size = 20
        total = 0
        pages = 0
        all_reviews: list[dict] = []

        while True:
            resp = await self.client.execute_api(
                API_REVIEWS,
                method="POST",
                body_params={
                    "wmPoiId": self.wm_poi_id,
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "startTime": start_date.strftime("%Y-%m-%d"),
                    "endTime": end_date.strftime("%Y-%m-%d"),
                    "replyStatus": "",  # 全部
                    "starLevel": "",    # 全部评分
                },
            )

            if not isinstance(resp, dict):
                break

            code = resp.get("code", -1)
            if code not in (0, None):
                logger.warning("评价 API 错误: code=%s", code)
                break

            data = resp.get("data") or {}
            reviews = (
                data.get("list") or data.get("evaluateList") or
                data.get("commentList") or data.get("items") or []
            )
            total_count = int(data.get("total") or data.get("totalCount") or 0)

            if not reviews:
                break

            all_reviews.extend(reviews)
            total += len(reviews)
            pages += 1
            logger.info("评价 page=%d, 本页=%d, 累计=%d", page_num, len(reviews), total)

            if total >= total_count or len(reviews) < page_size:
                break
            page_num += 1
            await asyncio.sleep(0.5)

        if all_reviews:
            await self._save_raw(all_reviews, "qnh_reviews")

        return SyncResult(syncer="reviews", success=total > 0 or pages > 0, records=total, pages=pages)

    # ── 销售统计 ──────────────────────────────────────────────────────────

    async def sync_stats(self) -> SyncResult:
        """拉取过去 days_back 天的每日销售统计。"""
        end_date = date.today()
        start_date = end_date - timedelta(days=self.days_back)

        await self.client.navigate_to("/data/business")

        resp = await self.client.execute_api(
            API_STATS,
            method="POST",
            body_params={
                "wmPoiId": self.wm_poi_id,
                "startTime": start_date.strftime("%Y-%m-%d"),
                "endTime": end_date.strftime("%Y-%m-%d"),
                "timeType": "day",  # 按天汇总
            },
        )

        if not isinstance(resp, dict) or resp.get("code") not in (0, None):
            return SyncResult(syncer="metrics", success=False, records=0,
                              error=f"统计 API 错误: {str(resp)[:100]}")

        data = resp.get("data") or {}
        stat_list = data.get("list") or data.get("statList") or data.get("items") or []

        if stat_list:
            await self._save_raw(stat_list, "qnh_store_metrics")

        return SyncResult(syncer="metrics", success=True, records=len(stat_list), pages=1)

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
            skipped = 0
            for item in items:
                raw_json = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                content_hash = hashlib.md5(raw_json.encode()).hexdigest()
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
                    skipped += 1

        logger.info("%s 写入完成: %d 条新增, %d 条跳过（重复）", raw_table, inserted, skipped)
