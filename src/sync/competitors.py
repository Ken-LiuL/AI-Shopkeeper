"""竞品数据同步器 — 每天 2 次从美团 H5 采集竞品数据。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from src.sync.base import CST, BaseSyncer, SyncMode, SyncResult

logger = logging.getLogger(__name__)

# 预设搜索关键词
COMPETITOR_KEYWORDS = [
    "血压计",
    "体温计",
    "血糖仪",
    "口罩",
    "制氧机",
    "雾化器",
    "血氧仪",
    "轮椅",
    "护腰带",
    "助听器",
    "医用纱布",
    "消毒液",
    "退热贴",
    "创可贴",
    "酒精棉片",
]

# 默认定位：光谷
DEFAULT_LOCATION = (114.43, 30.51)


class CompetitorSyncer(BaseSyncer):
    """竞品数据同步器。

    每天 10:00 和 22:00 运行，搜索预设关键词列表，
    将结果存入 competitor_products / competitor_stores / competitor_keywords 表。
    """

    name = "competitors"
    full_sync_interval = timedelta(hours=12)  # 每天 2 次

    def __init__(
        self,
        db_pool: Any,
        location: tuple = DEFAULT_LOCATION,
        keywords: list[str] | None = None,
    ):
        super().__init__(client=None, db_pool=db_pool)
        self._db_pool = db_pool
        self._location = location
        self._keywords = keywords or COMPETITOR_KEYWORDS

    async def full_sync(self) -> SyncResult:
        """全量同步：搜索所有预设关键词。"""
        started = datetime.now(CST)
        total_products = 0
        total_stores = 0
        total_keywords = 0
        errors = []

        try:
            from src.skills.meituan_h5 import MeituanH5Scraper

            scraper = MeituanH5Scraper(default_location=self._location)

            # 1. 搜索每个关键词
            for kw in self._keywords:
                try:
                    products = await scraper.search_products(kw, self._location, limit=20)
                    if products:
                        await self._save_products(products, kw)
                        total_products += len(products)

                        # 聚合店铺
                        stores = self._aggregate_stores(products)
                        await self._save_stores(stores, kw)
                        total_stores += len(stores)
                except Exception as e:
                    errors.append(f"{kw}: {e}")
                    logger.error(f"Competitor sync failed for '{kw}': {e}")
                    await self._record_sync_error(kw, str(e))

            # 2. 采集热搜词
            try:
                hot_words = await scraper.search_hot_keywords()
                if hot_words:
                    await self._save_keywords(hot_words)
                    total_keywords += len(hot_words)
            except Exception as e:
                errors.append(f"hot_keywords: {e}")

            await scraper.cleanup()

        except ImportError:
            errors.append("MeituanH5Scraper not available")
        except Exception as e:
            errors.append(str(e))

        finished = datetime.now(CST)
        success = total_products > 0 or not errors

        return SyncResult(
            syncer_name=self.name,
            mode=SyncMode.FULL,
            success=success,
            records_synced=total_products + total_stores + total_keywords,
            records_failed=len(errors),
            started_at=started,
            finished_at=finished,
            duration_ms=int((finished - started).total_seconds() * 1000),
            error="; ".join(errors) if errors else None,
            details={
                "products": total_products,
                "stores": total_stores,
                "keywords": total_keywords,
            },
        )

    async def incremental_sync(self) -> SyncResult:
        """增量同步 = 全量同步（数据是快照式的）。"""
        return await self.full_sync()

    async def _save_products(self, products: list, keyword: str):
        """保存竞品商品到数据库。单条失败不中断批次。"""
        if not self._db_pool:
            return
        failed = 0
        for p in products:
            try:
                await self._db_pool.execute(
                    """
                    INSERT INTO competitor_products
                        (product_id, name, price, monthly_sales, store_name, keyword)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    p.product_id,
                    p.name,
                    p.price,
                    p.monthly_sales,
                    p.store_name,
                    keyword,
                )
            except Exception:
                logger.error("Failed to save competitor product %s (kw=%s)", getattr(p, "product_id", "?"), keyword, exc_info=True)
                failed += 1
        if failed:
            logger.warning("_save_products: %d/%d failed for keyword=%s", failed, len(products), keyword)

    async def _save_stores(self, stores: list[dict], keyword: str):
        """保存竞品店铺到数据库。单条失败不中断批次。"""
        if not self._db_pool:
            return
        failed = 0
        for s in stores:
            try:
                await self._db_pool.execute(
                    """
                    INSERT INTO competitor_stores
                        (store_id, name, monthly_sales, product_count, threat_level, keyword)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    s["store_id"],
                    s["name"],
                    s["monthly_sales"],
                    s["product_count"],
                    s["threat_level"],
                    keyword,
                )
            except Exception:
                logger.error("Failed to save competitor store %s (kw=%s)", s.get("store_id", "?"), keyword, exc_info=True)
                failed += 1
        if failed:
            logger.warning("_save_stores: %d/%d failed for keyword=%s", failed, len(stores), keyword)

    async def _save_keywords(self, keywords: list[str]):
        """保存热搜词到数据库。单条失败不中断批次。"""
        if not self._db_pool:
            return
        failed = 0
        for kw in keywords:
            try:
                await self._db_pool.execute(
                    """
                    INSERT INTO competitor_keywords (keyword) VALUES ($1)
                    """,
                    kw,
                )
            except Exception:
                logger.error("Failed to save competitor keyword %r", kw, exc_info=True)
                failed += 1
        if failed:
            logger.warning("_save_keywords: %d/%d failed", failed, len(keywords))

    async def _record_sync_error(self, keyword: str, error: str):
        """记录同步错误到 sync_state 表。"""
        if not self._db_pool:
            return
        try:
            await self._db_pool.execute(
                """
                INSERT INTO sync_state (syncer_name, status, error_message, keyword, updated_at)
                VALUES ($1, 'error', $2, $3, NOW())
                ON CONFLICT (syncer_name, keyword) DO UPDATE
                SET status = 'error', error_message = $2, updated_at = NOW()
                """,
                self.name,
                error,
                keyword,
            )
        except Exception as e:
            logger.error(f"Failed to record sync error: {e}")

    @staticmethod
    def _aggregate_stores(products: list) -> list[dict]:
        """将商品列表聚合为店铺维度。"""
        store_map: dict[str, dict] = {}
        for p in products:
            key = p.store_name or p.name
            if key not in store_map:
                store_map[key] = {
                    "store_id": p.product_id,
                    "name": key,
                    "monthly_sales": p.monthly_sales,
                    "product_count": 1,
                    "threat_level": "medium",
                }
            else:
                store_map[key]["monthly_sales"] += p.monthly_sales
                store_map[key]["product_count"] += 1

        stores = list(store_map.values())
        for s in stores:
            if s["monthly_sales"] > 500:
                s["threat_level"] = "high"
            elif s["monthly_sales"] < 100:
                s["threat_level"] = "low"
        return stores
