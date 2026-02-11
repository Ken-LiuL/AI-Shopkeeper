"""ActionBook Skill — 数据采集（美团/1688/拼多多）with rate limiting.

## 方案：ActionBook Extension 模式 + Mock Fallback

通过 ActionBook CLI（Extension 模式）控制用户已登录的 Chrome 浏览器，
在真实页面上执行 snapshot/text 提取数据。采集失败时降级为 mock 数据。

### 使用方式
1. 安装 ActionBook Chrome 扩展：actionbook extension install
2. 在 Chrome 中加载扩展（chrome://extensions → Load unpacked）
3. 启动 WebSocket bridge：actionbook extension serve
4. 在 Chrome 中登录 1688 和拼多多
5. 调用 skill 方法即可获取真实数据

### 环境变量
- ACTIONBOOK_EXTENSION=1 — 默认使用 Extension 模式（默认开启）
- ACTIONBOOK_MODE=cdp — 切换到 CDP 模式
- ACTIONBOOK_TIMEOUT=30 — 命令超时秒数（默认30）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional
from urllib.parse import quote

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
    threat_level: str = "medium"

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
    trade_level: str = ""
    return_rate: float = 0.0
    url: str = ""
    images: List[str] = Field(default_factory=list)
    is_mock: bool = False

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
    is_mock: bool = False

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


# ── ActionBook CLI Helper ────────────────────────────────────────────────────

class _ActionBookCLI:
    """Manages ActionBook CLI calls via subprocess."""

    def __init__(self, use_extension: bool = True, timeout: int = 30):
        self.use_extension = use_extension
        self.timeout = timeout
        self._page_open = False

    def _base_args(self) -> list[str]:
        args = ["actionbook"]
        if self.use_extension:
            args.append("--extension")
        args.append("--json")
        return args

    async def _run(self, *args: str, timeout: Optional[int] = None) -> dict:
        """Run an actionbook CLI command and return parsed JSON output."""
        cmd = self._base_args() + list(args)
        to = timeout or self.timeout
        logger.debug(f"ActionBook CLI: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "ACTIONBOOK_EXTENSION": "1" if self.use_extension else "0"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=to)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"ActionBook command timed out after {to}s: {' '.join(args)}")

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"ActionBook command failed (rc={proc.returncode}): {stderr_str or stdout_str}"
            )

        # Try to parse JSON; fall back to raw text
        if stdout_str:
            try:
                return json.loads(stdout_str)
            except json.JSONDecodeError:
                return {"raw": stdout_str}
        return {}

    async def _run_text(self, *args: str, timeout: Optional[int] = None) -> str:
        """Run an actionbook CLI command and return raw text output."""
        cmd_base = ["actionbook"]
        if self.use_extension:
            cmd_base.append("--extension")
        cmd = cmd_base + list(args)
        to = timeout or self.timeout
        logger.debug(f"ActionBook CLI (text): {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "ACTIONBOOK_EXTENSION": "1" if self.use_extension else "0"},
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=to)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"ActionBook command timed out after {to}s")

        if proc.returncode != 0:
            stderr_str = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ActionBook command failed: {stderr_str}")

        return stdout.decode("utf-8", errors="replace").strip()

    async def check_extension(self) -> bool:
        """Check if extension bridge is running and connected."""
        try:
            result = await self._run("extension", "status", timeout=5)
            raw = result.get("raw", str(result))
            return "running" in raw.lower()
        except Exception as e:
            logger.warning(f"Extension status check failed: {e}")
            return False

    async def browser_open(self, url: str) -> dict:
        """Open a URL in the browser."""
        result = await self._run("browser", "open", url, timeout=self.timeout)
        self._page_open = True
        return result

    async def browser_text(self, selector: str = "") -> str:
        """Get text content from the page or a specific element."""
        args = ["browser", "text"]
        if selector:
            args.append(selector)
        return await self._run_text(*args, timeout=self.timeout)

    async def browser_snapshot(self) -> str:
        """Get accessibility tree snapshot of the current page."""
        return await self._run_text("browser", "snapshot", timeout=self.timeout)

    async def browser_eval(self, js: str) -> str:
        """Evaluate JavaScript on the current page."""
        return await self._run_text("browser", "eval", js, timeout=self.timeout)

    async def browser_wait_nav(self) -> dict:
        """Wait for navigation to complete."""
        return await self._run("browser", "wait-nav", timeout=self.timeout)

    async def browser_close(self) -> dict:
        """Close the current browser tab."""
        if self._page_open:
            self._page_open = False
            try:
                return await self._run("browser", "close", timeout=10)
            except Exception as e:
                logger.warning(f"browser close failed: {e}")
        return {}

    async def cleanup(self):
        """Release browser resources."""
        await self.browser_close()


# ── Data Extraction Helpers ──────────────────────────────────────────────────

def _parse_1688_text(text: str, limit: int = 10) -> list[dict]:
    """Parse 1688 search results from page text/snapshot.

    Attempts to extract product blocks from raw text.
    This is a best-effort parser; real DOM varies frequently.
    """
    products = []
    if not text:
        return products

    # Split by common product separators and look for price patterns
    # 1688 pages typically show: title, price (¥xx.xx), MOQ, supplier
    lines = text.split("\n")
    current: dict = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Price pattern: ¥xx.xx or xx.xx元
        price_match = re.search(r"[¥￥]?\s*(\d+\.?\d*)\s*(?:元|/件|/个)?", line)

        # If we see a substantial text line (potential title) and no current item
        if len(line) > 10 and not current.get("title") and not price_match:
            current["title"] = line[:100]
        elif price_match and current.get("title") and not current.get("price"):
            current["price"] = float(price_match.group(1))
        elif current.get("title") and current.get("price"):
            # Look for sales/supplier info
            sales_match = re.search(r"(\d+)\s*(?:件|笔|成交)", line)
            if sales_match:
                current["sales"] = int(sales_match.group(1))

            # Commit current product and start new one
            if len(line) > 10 and not sales_match:
                products.append(current)
                current = {"title": line[:100]}

    if current.get("title") and current.get("price"):
        products.append(current)

    return products[:limit]


def _parse_pdd_text(text: str, limit: int = 10) -> list[dict]:
    """Parse PDD search results from page text/snapshot."""
    products = []
    if not text:
        return products

    lines = text.split("\n")
    current: dict = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        price_match = re.search(r"[¥￥]?\s*(\d+\.?\d*)", line)
        sales_match = re.search(r"已拼?\s*(\d+(?:\.\d+)?)\s*万?\s*件?", line)

        if sales_match and current.get("title"):
            val = float(sales_match.group(1))
            if "万" in line:
                val *= 10000
            current["sales"] = int(val)

        if len(line) > 8 and not current.get("title") and not price_match:
            current["title"] = line[:100]
        elif price_match and current.get("title") and not current.get("price"):
            current["price"] = float(price_match.group(1))
        elif current.get("title") and current.get("price") and len(line) > 8:
            products.append(current)
            current = {"title": line[:100]}

    if current.get("title") and current.get("price"):
        products.append(current)

    return products[:limit]


# ── JS extraction scripts (more reliable than text parsing) ──────────────────

_JS_EXTRACT_1688 = """(() => {
    const items = [];
    // Try multiple selectors for 1688's frequently-changing DOM
    const selectors = [
        '.sm-offer-item', '[class*="OfferCard"]', '[class*="offer-card"]',
        '.offer-list-row-offer', '[data-spm*="offer"]',
    ];
    let elements = [];
    for (const sel of selectors) {
        elements = document.querySelectorAll(sel);
        if (elements.length > 0) break;
    }
    for (const el of Array.from(elements).slice(0, %d)) {
        try {
            const titleEl = el.querySelector(
                '[class*="title"] a, [class*="Title"] a, h4 a, h3 a, a[title]'
            );
            const title = titleEl
                ? (titleEl.getAttribute('title') || titleEl.textContent || '').trim()
                : '';
            const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
            const priceText = priceEl ? priceEl.textContent.trim() : '0';
            const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
            const linkEl = el.querySelector('a[href*="detail.1688.com"], a[href*="offer"]');
            const url = linkEl ? linkEl.href : '';
            const supplierEl = el.querySelector(
                '[class*="company"], [class*="supplier"], [class*="Company"]'
            );
            const supplier = supplierEl ? supplierEl.textContent.trim() : '';
            const moqEl = el.querySelector('[class*="moq"], [class*="order"]');
            const moq = moqEl ? parseInt(moqEl.textContent.replace(/[^0-9]/g, '')) || 1 : 1;
            const salesEl = el.querySelector('[class*="sale"], [class*="deal"]');
            const sales = salesEl
                ? parseInt(salesEl.textContent.replace(/[^0-9]/g, '')) || 0
                : 0;
            if (title) items.push({title, price, url, supplier, moq, sales});
        } catch (e) {}
    }
    return JSON.stringify(items);
})()"""

_JS_EXTRACT_PDD = """(() => {
    const items = [];
    const selectors = [
        '[class*="goods-item"]', '[class*="GoodsItem"]',
        '[class*="product-card"]', '[class*="search-item"]',
    ];
    let elements = [];
    for (const sel of selectors) {
        elements = document.querySelectorAll(sel);
        if (elements.length > 0) break;
    }
    for (const el of Array.from(elements).slice(0, %d)) {
        try {
            const titleEl = el.querySelector('[class*="title"], [class*="name"], h3, h4');
            const title = titleEl ? titleEl.textContent.trim() : '';
            const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
            const priceText = priceEl ? priceEl.textContent.trim() : '0';
            const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
            const linkEl = el.querySelector('a[href]');
            const rawHref = linkEl ? linkEl.href : '';
            const url = rawHref.startsWith('http') ? rawHref
                : rawHref ? 'https://mobile.yangkeduo.com' + rawHref : '';
            const salesEl = el.querySelector('[class*="sales"], [class*="sold"]');
            const salesText = salesEl ? salesEl.textContent : '';
            let sales = parseInt(salesText.replace(/[^0-9]/g, '')) || 0;
            if (salesText.includes('万'))
                sales = Math.round(parseFloat(salesText.replace(/[^0-9.]/g, '')) * 10000);
            const shopEl = el.querySelector('[class*="shop"], [class*="store"]');
            const shop = shopEl ? shopEl.textContent.trim() : '';
            if (title) items.push({title, price, url, sales, shop});
        } catch (e) {}
    }
    return JSON.stringify(items);
})()"""

_JS_EXTRACT_1688_DETAIL = """(() => {
    const title = document.querySelector(
        '[class*="title-text"], h1, .mod-detail-title'
    )?.textContent?.trim() || '';
    const priceEl = document.querySelector(
        '[class*="price-text"], .price, [class*="Price"]'
    );
    const price = priceEl
        ? parseFloat(priceEl.textContent.replace(/[^0-9.]/g, '')) || 0
        : 0;
    const moqEl = document.querySelector('[class*="moq"], [class*="min-order"]');
    const moq = moqEl
        ? parseInt(moqEl.textContent.replace(/[^0-9]/g, '')) || 1
        : 1;
    const salesEl = document.querySelector('[class*="sale-count"], [class*="deal"]');
    const sales = salesEl
        ? parseInt(salesEl.textContent.replace(/[^0-9]/g, '')) || 0
        : 0;
    const supplierEl = document.querySelector(
        '[class*="company-name"], .company-name, [class*="shop-name"]'
    );
    const supplier = supplierEl ? supplierEl.textContent.trim() : '';
    const imgs = Array.from(document.querySelectorAll(
        '.detail-gallery img, [class*="gallery"] img, .main-image img'
    )).map(i => i.src || i.dataset?.src || '').filter(Boolean).slice(0, 5);
    return JSON.stringify({title, price, moq, sales, supplier, images: imgs});
})()"""

_JS_EXTRACT_PDD_DETAIL = """(() => {
    const title = document.querySelector(
        '[class*="goods-name"], [class*="title"], h1'
    )?.textContent?.trim() || '';
    const priceEl = document.querySelector('[class*="price"], [class*="Price"]');
    const price = priceEl
        ? parseFloat(priceEl.textContent.replace(/[^0-9.]/g, '')) || 0
        : 0;
    const origEl = document.querySelector('[class*="origin"], [class*="market"]');
    const origPrice = origEl
        ? parseFloat(origEl.textContent.replace(/[^0-9.]/g, '')) || 0
        : 0;
    const salesEl = document.querySelector('[class*="sales"], [class*="sold"]');
    const salesText = salesEl ? salesEl.textContent : '';
    let sales = parseInt(salesText.replace(/[^0-9]/g, '')) || 0;
    if (salesText.includes('万'))
        sales = Math.round(parseFloat(salesText.replace(/[^0-9.]/g, '')) * 10000);
    const shopEl = document.querySelector('[class*="shop-name"], [class*="store-name"]');
    const shop = shopEl ? shopEl.textContent.trim() : '';
    const reviewEl = document.querySelector('[class*="review-count"], [class*="comment-num"]');
    const reviews = reviewEl
        ? parseInt(reviewEl.textContent.replace(/[^0-9]/g, '')) || 0
        : 0;
    const imgs = Array.from(document.querySelectorAll(
        '[class*="gallery"] img, [class*="slider"] img, .goods-img img'
    )).map(i => i.src || i.dataset?.src || '').filter(Boolean).slice(0, 5);
    return JSON.stringify({title, price, origPrice, sales, shop, reviews, images: imgs});
})()"""


# ── Mock Data ────────────────────────────────────────────────────────────────

def _mock_alibaba_search(keyword: str, limit: int) -> List[AlibabaProduct]:
    """返回 mock 数据，标记 is_mock=True。"""
    mock = [
        AlibabaProduct(
            product_id="AL001", title=f"{keyword} 医用级", price=45.0,
            min_order_qty=10, sales_count=5000, supplier_name="深圳康泰医疗",
            supplier_years=8, is_power_seller=True, shop_score=4.9,
            trade_level="gold", return_rate=0.35,
            url="https://detail.1688.com/mock/AL001", is_mock=True,
        ),
        AlibabaProduct(
            product_id="AL002", title=f"{keyword} 家用款", price=32.0,
            min_order_qty=20, sales_count=3200, supplier_name="广州瑞康科技",
            supplier_years=5, is_power_seller=True, shop_score=4.7,
            trade_level="silver", return_rate=0.25,
            url="https://detail.1688.com/mock/AL002", is_mock=True,
        ),
        AlibabaProduct(
            product_id="AL003", title=f"{keyword} 批发", price=28.0,
            min_order_qty=50, sales_count=8000, supplier_name="江苏鱼跃医疗",
            supplier_years=12, is_power_seller=True, shop_score=4.8,
            trade_level="gold", return_rate=0.40,
            url="https://detail.1688.com/mock/AL003", is_mock=True,
        ),
    ]
    return mock[:limit]


def _mock_pdd_search(keyword: str, limit: int) -> List[PddProduct]:
    """返回 mock 数据，标记 is_mock=True。"""
    mock = [
        PddProduct(
            product_id="PDD001", title=f"{keyword} 家用精准",
            price=89.9, original_price=129.0, sales_count=10000,
            shop_name="鱼跃医疗旗舰店", shop_score=4.9,
            url="https://mobile.yangkeduo.com/mock/PDD001",
            has_coupon=True, coupon_amount=10, review_count=5200, is_mock=True,
        ),
        PddProduct(
            product_id="PDD002", title=f"{keyword} 医用级",
            price=69.9, original_price=99.0, sales_count=6500,
            shop_name="欧姆龙官方店", shop_score=4.8,
            url="https://mobile.yangkeduo.com/mock/PDD002",
            has_coupon=False, coupon_amount=0, review_count=3100, is_mock=True,
        ),
    ]
    return mock[:limit]


def _mock_alibaba_detail(url: str) -> AlibabaProduct:
    return AlibabaProduct(
        product_id="AL001", title="鱼跃电子血压计 医用级",
        price=45.0, min_order_qty=10, sales_count=5000,
        supplier_name="深圳康泰医疗", supplier_years=8,
        is_power_seller=True, shop_score=4.9, trade_level="gold",
        return_rate=0.35, url=url,
        images=["https://img.1688.com/mock1.jpg"], is_mock=True,
    )


def _mock_pdd_detail(url: str) -> PddProduct:
    return PddProduct(
        product_id="PDD001", title="鱼跃电子血压计 家用精准",
        price=89.9, original_price=129.0, sales_count=10000,
        shop_name="鱼跃医疗旗舰店", shop_score=4.9, url=url,
        images=["https://img.pddpic.com/mock1.jpg"],
        has_coupon=True, coupon_amount=10, review_count=5200, is_mock=True,
    )


# ── Skill ────────────────────────────────────────────────────────────────────

class ActionBookSkill:
    """ActionBook RPA 采集技能。

    通过 ActionBook CLI（Extension 或 CDP 模式）控制浏览器采集数据。
    采集失败时自动降级为 mock 数据（标记 is_mock=True）。

    支持两种模式：
    1. Extension 模式（默认）：通过 Chrome 扩展控制用户已登录的浏览器
       - 需要先安装扩展并启动 bridge：actionbook extension serve
    2. CDP 模式：通过 Chrome DevTools Protocol 连接
       - 设置 ACTIONBOOK_MODE=cdp 和 CDP_URL

    美团数据始终使用 mock（需要商家后台权限）。
    """

    def __init__(
        self,
        rate_limits: Optional[dict[str, int]] = None,
        cdp_url: Optional[str] = None,
    ):
        limits = {**_DEFAULT_LIMITS, **(rate_limits or {})}
        self._buckets: dict[str, _RateBucket] = {
            name: _RateBucket(max_calls=max_calls)
            for name, max_calls in limits.items()
        }

        # Determine mode
        mode = os.environ.get("ACTIONBOOK_MODE", "extension").lower()
        use_extension = mode != "cdp"
        timeout = int(os.environ.get("ACTIONBOOK_TIMEOUT", "30"))

        self._cli = _ActionBookCLI(use_extension=use_extension, timeout=timeout)
        self._extension_checked = False
        self._extension_available = False

    def _check_rate(self, method: str) -> None:
        bucket = self._buckets.get(method)
        if bucket and not bucket.acquire():
            raise RuntimeError(f"Rate limit exceeded for {method}")

    async def _ensure_extension(self) -> bool:
        """Check extension availability (cached)."""
        if not self._extension_checked:
            self._extension_available = await self._cli.check_extension()
            self._extension_checked = True
            if self._extension_available:
                logger.info("ActionBook extension bridge is connected")
            else:
                logger.warning("ActionBook extension not available, will use mock fallback")
        return self._extension_available

    async def _scrape_with_actionbook(
        self,
        url: str,
        js_extract: str,
        wait_seconds: float = 3.0,
    ) -> list[dict]:
        """Generic scrape: open URL → wait → eval JS → close → return parsed items."""
        if not await self._ensure_extension():
            return []

        try:
            await self._cli.browser_open(url)
            # Wait for page to load
            await asyncio.sleep(wait_seconds)

            # Try JS extraction first (more structured)
            raw = await self._cli.browser_eval(js_extract)
            if raw:
                try:
                    items = json.loads(raw)
                    if isinstance(items, list) and items:
                        return items
                except json.JSONDecodeError:
                    pass

            # Fallback: get page text and try to parse
            text = await self._cli.browser_text()
            return []  # Text parsing is too unreliable as a secondary fallback

        except Exception as e:
            logger.warning(f"ActionBook scraping failed for {url}: {e}")
            return []
        finally:
            await self._cli.browser_close()

    async def _scrape_detail_with_actionbook(
        self,
        url: str,
        js_extract: str,
        wait_seconds: float = 3.0,
    ) -> Optional[dict]:
        """Scrape a single detail page."""
        if not await self._ensure_extension():
            return None

        try:
            await self._cli.browser_open(url)
            await asyncio.sleep(wait_seconds)

            raw = await self._cli.browser_eval(js_extract)
            if raw:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict) and data.get("title"):
                        return data
                except json.JSONDecodeError:
                    pass
            return None
        except Exception as e:
            logger.warning(f"ActionBook detail scraping failed for {url}: {e}")
            return None
        finally:
            await self._cli.browser_close()

    # ── 美团 (始终 mock，需要商家后台) ────────────────────────────────────

    async def meituan_keywords(
        self,
        store_id: str,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[MeituanKeyword]:
        """获取美团热搜词（mock - 需要美团商家后台权限）。"""
        self._check_rate("meituan_keywords")
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
        """获取美团商品排行榜（mock）。"""
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
        """获取周边竞品店铺（mock）。"""
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
        """获取竞品商品列表（mock）。"""
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
        sort_by: str = "sales",
        limit: int = 10,
    ) -> List[AlibabaProduct]:
        """搜索1688商品。通过 ActionBook 采集，失败时返回 mock。"""
        self._check_rate("alibaba_search")

        url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote(keyword)}"
        js = _JS_EXTRACT_1688 % limit
        raw_items = await self._scrape_with_actionbook(url, js, wait_seconds=4.0)

        if not raw_items:
            logger.info(f"1688 search '{keyword}': no results, using mock")
            return _mock_alibaba_search(keyword, limit)

        products = []
        for i, item in enumerate(raw_items):
            products.append(AlibabaProduct(
                product_id=f"AL{i+1:03d}",
                title=item.get("title", ""),
                price=item.get("price", 0.0),
                min_order_qty=item.get("moq", 1),
                sales_count=item.get("sales", 0),
                supplier_name=item.get("supplier", ""),
                url=item.get("url", ""),
                is_mock=False,
            ))
        logger.info(f"1688 search '{keyword}': got {len(products)} real results")
        return products

    async def alibaba_detail(self, url: str) -> AlibabaProduct:
        """获取1688商品详情。通过 ActionBook 采集，失败时返回 mock。"""
        self._check_rate("alibaba_detail")

        data = await self._scrape_detail_with_actionbook(
            url, _JS_EXTRACT_1688_DETAIL, wait_seconds=4.0
        )

        if not data:
            return _mock_alibaba_detail(url)

        return AlibabaProduct(
            product_id="AL001",
            title=data.get("title", ""),
            price=data.get("price", 0.0),
            min_order_qty=data.get("moq", 1),
            sales_count=data.get("sales", 0),
            supplier_name=data.get("supplier", ""),
            url=url,
            images=data.get("images", []),
            is_mock=False,
        )

    async def alibaba_supplier(self, supplier_id: str) -> AlibabaSupplier:
        """获取1688供应商信息（mock - 需要专门的供应商页面解析）。"""
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
        sort_by: str = "sales",
        limit: int = 10,
    ) -> List[PddProduct]:
        """搜索拼多多商品。通过 ActionBook 采集，失败时返回 mock。"""
        self._check_rate("pdd_search")

        url = f"https://mobile.yangkeduo.com/search_result.html?search_key={quote(keyword)}"
        js = _JS_EXTRACT_PDD % limit
        raw_items = await self._scrape_with_actionbook(url, js, wait_seconds=4.0)

        if not raw_items:
            logger.info(f"PDD search '{keyword}': no results, using mock")
            return _mock_pdd_search(keyword, limit)

        products = []
        for i, item in enumerate(raw_items):
            products.append(PddProduct(
                product_id=f"PDD{i+1:03d}",
                title=item.get("title", ""),
                price=item.get("price", 0.0),
                sales_count=item.get("sales", 0),
                shop_name=item.get("shop", ""),
                url=item.get("url", ""),
                is_mock=False,
            ))
        logger.info(f"PDD search '{keyword}': got {len(products)} real results")
        return products

    async def pdd_detail(self, url: str) -> PddProduct:
        """获取拼多多商品详情。通过 ActionBook 采集，失败时返回 mock。"""
        self._check_rate("pdd_detail")

        data = await self._scrape_detail_with_actionbook(
            url, _JS_EXTRACT_PDD_DETAIL, wait_seconds=4.0
        )

        if not data:
            return _mock_pdd_detail(url)

        return PddProduct(
            product_id="PDD001",
            title=data.get("title", ""),
            price=data.get("price", 0.0),
            original_price=data.get("origPrice", 0.0),
            sales_count=data.get("sales", 0),
            shop_name=data.get("shop", ""),
            url=url,
            images=data.get("images", []),
            review_count=data.get("reviews", 0),
            is_mock=False,
        )

    async def pdd_shop(self, shop_id: str) -> PddShop:
        """获取拼多多店铺信息（mock - 需要专门的店铺页面解析）。"""
        self._check_rate("pdd_shop")
        return PddShop(
            shop_id=shop_id, name="鱼跃医疗旗舰店",
            score=4.9, product_count=156, sales_count=85000,
            location="江苏南京",
        )

    async def cleanup(self):
        """清理 ActionBook 浏览器连接。"""
        await self._cli.cleanup()
