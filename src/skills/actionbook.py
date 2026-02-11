"""ActionBook Skill — 数据采集（美团/1688/拼多多）with rate limiting and mock data."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Pydantic Models ──────────────────────────────────────────────────────────

class MeituanKeyword(BaseModel):
    keyword: str
    search_volume: int
    growth_rate: float = Field(description="环比增长率")
    conversion_rate: float = 0.0
    category: str = ""

class MeituanProduct(BaseModel):
    product_id: str
    name: str
    price: float
    monthly_sales: int
    rating: float = 0.0
    store_name: str = ""

class CompetitorStore(BaseModel):
    store_id: str
    name: str
    distance_km: float
    rating: float
    monthly_sales: int = 0
    product_count: int = 0
    threat_level: str = "medium"  # high/medium/low

class CompetitorProduct(BaseModel):
    product_id: str
    name: str
    price: float
    monthly_sales: int
    store_name: str = ""

class AlibabaProduct(BaseModel):
    product_id: str
    title: str
    price: float
    min_order_qty: int = 1
    sales_count: int = 0
    supplier_name: str = ""
    supplier_years: int = 0
    is_power_seller: bool = False
    shop_score: float = 0.0
    trade_level: str = ""  # gold/silver/bronze
    return_rate: float = 0.0
    url: str = ""
    images: List[str] = Field(default_factory=list)

class AlibabaSupplier(BaseModel):
    supplier_id: str
    name: str
    years: int = 0
    is_power_seller: bool = False
    shop_score: float = 0.0
    trade_level: str = ""
    return_rate: float = 0.0
    main_products: List[str] = Field(default_factory=list)
    location: str = ""

class PddProduct(BaseModel):
    product_id: str
    title: str
    price: float
    original_price: float = 0.0
    sales_count: int = 0
    shop_name: str = ""
    shop_score: float = 0.0
    url: str = ""
    images: List[str] = Field(default_factory=list)
    has_coupon: bool = False
    coupon_amount: float = 0.0
    review_count: int = 0

class PddShop(BaseModel):
    shop_id: str
    name: str
    score: float = 0.0
    product_count: int = 0
    sales_count: int = 0
    location: str = ""


# ── Rate Limiter ─────────────────────────────────────────────────────────────

@dataclass
class _RateBucket:
    max_calls: int
    period_seconds: int = 3600
    timestamps: list = field(default_factory=list)

    def acquire(self) -> bool:
        now = time.monotonic()
        cutoff = now - self.period_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) >= self.max_calls:
            return False
        self.timestamps.append(now)
        return True


# ── Rate limit config per SPEC ──────────────────────────────────────────────

_DEFAULT_LIMITS: dict[str, int] = {
    "meituan_keywords": 10,
    "meituan_rankings": 10,
    "competitor_stores": 20,
    "competitor_products": 50,
    "alibaba_search": 100,
    "alibaba_detail": 100,
    "alibaba_supplier": 50,
    "pdd_search": 100,
    "pdd_detail": 100,
    "pdd_shop": 50,
}


# ── Skill ────────────────────────────────────────────────────────────────────

class ActionBookSkill:
    """ActionBook RPA 采集技能（当前为 mock 实现，后续接入真实爬虫）。"""

    def __init__(self, rate_limits: Optional[dict[str, int]] = None):
        limits = {**_DEFAULT_LIMITS, **(rate_limits or {})}
        self._buckets: dict[str, _RateBucket] = {
            name: _RateBucket(max_calls=max_calls)
            for name, max_calls in limits.items()
        }

    def _check_rate(self, method: str) -> None:
        bucket = self._buckets.get(method)
        if bucket and not bucket.acquire():
            raise RuntimeError(f"Rate limit exceeded for {method}")

    # ── 美团 ─────────────────────────────────────────────────────────────

    async def meituan_keywords(
        self,
        store_id: str,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[MeituanKeyword]:
        """获取美团热搜词。"""
        self._check_rate("meituan_keywords")
        # Mock data
        mock = [
            MeituanKeyword(keyword="电子血压计", search_volume=12000, growth_rate=0.15, conversion_rate=0.12, category="血压监测"),
            MeituanKeyword(keyword="血糖试纸", search_volume=8500, growth_rate=0.22, conversion_rate=0.18, category="血糖监测"),
            MeituanKeyword(keyword="体温计", search_volume=35000, growth_rate=0.08, conversion_rate=0.25, category="体温监测"),
            MeituanKeyword(keyword="雾化器", search_volume=5200, growth_rate=0.35, conversion_rate=0.10, category="呼吸治疗"),
            MeituanKeyword(keyword="制氧机", search_volume=3800, growth_rate=0.28, conversion_rate=0.08, category="呼吸治疗"),
        ]
        return mock[:limit]

    async def meituan_rankings(
        self,
        store_id: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[MeituanProduct]:
        """获取美团商品排行榜。"""
        self._check_rate("meituan_rankings")
        mock = [
            MeituanProduct(product_id="MT001", name="鱼跃电子血压计YE680A", price=199.0, monthly_sales=520, rating=4.9, store_name="鱼跃旗舰店"),
            MeituanProduct(product_id="MT002", name="欧姆龙体温计MC-246", price=39.9, monthly_sales=1200, rating=4.8, store_name="欧姆龙旗舰店"),
            MeituanProduct(product_id="MT003", name="三诺血糖仪GA-3", price=89.0, monthly_sales=380, rating=4.7, store_name="三诺旗舰店"),
        ]
        return mock[:limit]

    async def competitor_stores(
        self,
        store_id: str,
        radius_km: float = 3.0,
    ) -> List[CompetitorStore]:
        """获取周边竞品店铺。"""
        self._check_rate("competitor_stores")
        mock = [
            CompetitorStore(store_id="CS001", name="健康大药房", distance_km=1.2, rating=4.6, monthly_sales=15000, product_count=320, threat_level="high"),
            CompetitorStore(store_id="CS002", name="百姓大药房", distance_km=2.1, rating=4.3, monthly_sales=8000, product_count=210, threat_level="medium"),
            CompetitorStore(store_id="CS003", name="仁和药房", distance_km=2.8, rating=4.1, monthly_sales=5000, product_count=150, threat_level="low"),
        ]
        return [s for s in mock if s.distance_km <= radius_km]

    async def competitor_products(
        self,
        store_id: str,
        competitor_store_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[CompetitorProduct]:
        """获取竞品商品列表。"""
        self._check_rate("competitor_products")
        mock = [
            CompetitorProduct(product_id="CP001", name="鱼跃血压计", price=189.0, monthly_sales=450, store_name="健康大药房"),
            CompetitorProduct(product_id="CP002", name="欧姆龙体温计", price=35.9, monthly_sales=980, store_name="健康大药房"),
        ]
        return mock[:limit]

    # ── 1688 ─────────────────────────────────────────────────────────────

    async def alibaba_search(
        self,
        keyword: str,
        sort_by: str = "sales",  # sales/price/credit
        limit: int = 10,
    ) -> List[AlibabaProduct]:
        """搜索1688商品。"""
        self._check_rate("alibaba_search")
        mock = [
            AlibabaProduct(
                product_id="AL001", title=f"{keyword} 医用级", price=45.0,
                min_order_qty=10, sales_count=5000, supplier_name="深圳康泰医疗",
                supplier_years=8, is_power_seller=True, shop_score=4.9,
                trade_level="gold", return_rate=0.35,
                url="https://detail.1688.com/mock/AL001",
            ),
            AlibabaProduct(
                product_id="AL002", title=f"{keyword} 家用款", price=32.0,
                min_order_qty=20, sales_count=3200, supplier_name="广州瑞康科技",
                supplier_years=5, is_power_seller=True, shop_score=4.7,
                trade_level="silver", return_rate=0.25,
                url="https://detail.1688.com/mock/AL002",
            ),
        ]
        return mock[:limit]

    async def alibaba_detail(self, url: str) -> AlibabaProduct:
        """获取1688商品详情。"""
        self._check_rate("alibaba_detail")
        return AlibabaProduct(
            product_id="AL001", title="鱼跃电子血压计 医用级",
            price=45.0, min_order_qty=10, sales_count=5000,
            supplier_name="深圳康泰医疗", supplier_years=8,
            is_power_seller=True, shop_score=4.9, trade_level="gold",
            return_rate=0.35, url=url,
            images=["https://img.1688.com/mock1.jpg"],
        )

    async def alibaba_supplier(self, supplier_id: str) -> AlibabaSupplier:
        """获取1688供应商信息。"""
        self._check_rate("alibaba_supplier")
        return AlibabaSupplier(
            supplier_id=supplier_id, name="深圳康泰医疗",
            years=8, is_power_seller=True, shop_score=4.9,
            trade_level="gold", return_rate=0.35,
            main_products=["电子血压计", "血糖仪", "体温计"],
            location="广东深圳",
        )

    # ── 拼多多 ───────────────────────────────────────────────────────────

    async def pdd_search(
        self,
        keyword: str,
        sort_by: str = "sales",  # sales/price
        limit: int = 10,
    ) -> List[PddProduct]:
        """搜索拼多多商品。"""
        self._check_rate("pdd_search")
        mock = [
            PddProduct(
                product_id="PDD001", title=f"{keyword} 家用精准",
                price=89.9, original_price=129.0, sales_count=10000,
                shop_name="鱼跃医疗旗舰店", shop_score=4.9,
                url="https://mobile.yangkeduo.com/mock/PDD001",
                has_coupon=True, coupon_amount=10, review_count=5200,
            ),
            PddProduct(
                product_id="PDD002", title=f"{keyword} 医用级",
                price=69.9, original_price=99.0, sales_count=6500,
                shop_name="欧姆龙官方店", shop_score=4.8,
                url="https://mobile.yangkeduo.com/mock/PDD002",
                has_coupon=False, coupon_amount=0, review_count=3100,
            ),
        ]
        return mock[:limit]

    async def pdd_detail(self, url: str) -> PddProduct:
        """获取拼多多商品详情。"""
        self._check_rate("pdd_detail")
        return PddProduct(
            product_id="PDD001", title="鱼跃电子血压计 家用精准",
            price=89.9, original_price=129.0, sales_count=10000,
            shop_name="鱼跃医疗旗舰店", shop_score=4.9, url=url,
            images=["https://img.pddpic.com/mock1.jpg"],
            has_coupon=True, coupon_amount=10, review_count=5200,
        )

    async def pdd_shop(self, shop_id: str) -> PddShop:
        """获取拼多多店铺信息。"""
        self._check_rate("pdd_shop")
        return PddShop(
            shop_id=shop_id, name="鱼跃医疗旗舰店",
            score=4.9, product_count=156, sales_count=85000,
            location="江苏南京",
        )
