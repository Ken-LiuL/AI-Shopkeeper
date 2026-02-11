"""美团 H5 移动端竞品数据采集模块。

通过 ActionBook Extension 模式控制 Chrome 浏览器，
在美团外卖 H5 页面搜索并提取竞品商品、店铺、热搜词数据。

Usage:
    from src.skills.meituan_h5 import MeituanH5Scraper
    scraper = MeituanH5Scraper()
    products = await scraper.search_products("血压计", (114.43, 30.51))
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from src.skills.actionbook import CompetitorProduct, CompetitorStore, _ActionBookCLI
from src.anti_detect.fingerprint import FingerprintManager
from src.anti_detect.behavior import BehaviorSimulator, BehaviorConfig
from src.anti_detect.captcha import CaptchaHandler
from src.anti_detect.scheduler import SmartScheduler

logger = logging.getLogger(__name__)

# ── 加载 stealth.js ──────────────────────────────────────────────────────────
_STEALTH_JS_PATH = Path(__file__).parent.parent / "anti_detect" / "stealth.js"
_STEALTH_JS = _STEALTH_JS_PATH.read_text() if _STEALTH_JS_PATH.exists() else ""

# ── 默认定位：光谷 ──────────────────────────────────────────────────────────
DEFAULT_LOCATION = (114.43, 30.51)  # (lng, lat)

# ── URL 模板 ─────────────────────────────────────────────────────────────────
_SEARCH_URL = (
    "https://h5.waimai.meituan.com/waimai/mindex/search/list"
    "?query={keyword}&lat={lat}&lng={lng}"
)
_STORE_URL = (
    "https://h5.waimai.meituan.com/waimai/mindex/menu"
    "?dpShopId={store_id}&lat={lat}&lng={lng}"
)
_CATEGORY_URL = (
    "https://h5.waimai.meituan.com/waimai/mindex/category"
    "?category={category}&lat={lat}&lng={lng}"
)

# ── XHR 拦截器 JS ────────────────────────────────────────────────────────────
_JS_INJECT_XHR_INTERCEPTOR = """(() => {
    if (window.__mt_captured) return 'already_injected';
    window.__mt_captured = [];
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._url = url;
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        this.addEventListener('load', function() {
            if (this._url && (
                this._url.includes('/search') ||
                this._url.includes('/poi') ||
                this._url.includes('/hot_search') ||
                this._url.includes('/category')
            )) {
                try {
                    window.__mt_captured.push({
                        url: this._url,
                        data: JSON.parse(this.responseText)
                    });
                } catch(e) {}
            }
        });
        return origSend.apply(this, arguments);
    };
    // Also intercept fetch
    const origFetch = window.fetch;
    window.fetch = function(input, init) {
        const url = typeof input === 'string' ? input : input?.url || '';
        return origFetch.apply(this, arguments).then(resp => {
            if (url.includes('/search') || url.includes('/poi') ||
                url.includes('/hot_search') || url.includes('/category')) {
                resp.clone().text().then(text => {
                    try {
                        window.__mt_captured.push({url, data: JSON.parse(text)});
                    } catch(e) {}
                });
            }
            return resp;
        });
    };
    return 'injected';
})()"""

_JS_GET_CAPTURED = """(() => {
    const data = window.__mt_captured || [];
    window.__mt_captured = [];
    return JSON.stringify(data);
})()"""

# ── 页面文本提取 JS（降级方案）────────────────────────────────────────────────
_JS_EXTRACT_SEARCH_RESULTS = """(() => {
    const items = [];
    // 美团 H5 搜索结果通常在列表容器中
    const selectors = [
        '[class*="search-result"] [class*="poi-item"]',
        '[class*="SearchResult"] [class*="item"]',
        '[class*="food-item"]',
        '[class*="shopItem"]',
        '[class*="poi-card"]',
    ];
    let elements = [];
    for (const sel of selectors) {
        elements = document.querySelectorAll(sel);
        if (elements.length > 0) break;
    }
    // 如果选择器都不匹配，尝试通用方案
    if (elements.length === 0) {
        elements = document.querySelectorAll('a[href*="shopId"], a[href*="poiId"]');
    }
    for (const el of Array.from(elements).slice(0, 30)) {
        try {
            const nameEl = el.querySelector(
                '[class*="name"], [class*="title"], h3, h4'
            );
            const name = nameEl ? nameEl.textContent.trim() : '';
            const priceEl = el.querySelector('[class*="price"], [class*="Price"]');
            const priceText = priceEl ? priceEl.textContent : '0';
            const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
            const salesEl = el.querySelector(
                '[class*="sale"], [class*="month"], [class*="sold"]'
            );
            const salesText = salesEl ? salesEl.textContent : '';
            let sales = parseInt(salesText.replace(/[^0-9]/g, '')) || 0;
            const ratingEl = el.querySelector(
                '[class*="score"], [class*="rating"], [class*="star"]'
            );
            const rating = ratingEl
                ? parseFloat(ratingEl.textContent.replace(/[^0-9.]/g, '')) || 0
                : 0;
            const distEl = el.querySelector(
                '[class*="distance"], [class*="dist"]'
            );
            const distText = distEl ? distEl.textContent : '';
            let distance = parseFloat(distText.replace(/[^0-9.]/g, '')) || 0;
            if (distText.includes('m') && !distText.includes('km')) {
                distance = distance / 1000;
            }
            const storeEl = el.querySelector(
                '[class*="shop"], [class*="store"], [class*="poi-name"]'
            );
            const storeName = storeEl ? storeEl.textContent.trim() : name;
            // Try to extract store ID from link
            const linkEl = el.querySelector('a[href]');
            const href = linkEl ? linkEl.href : '';
            const idMatch = href.match(/(?:shopId|poiId|dpShopId)=(\d+)/);
            const storeId = idMatch ? idMatch[1] : '';
            if (name) {
                items.push({name, price, sales, rating, distance, storeName, storeId});
            }
        } catch(e) {}
    }
    return JSON.stringify(items);
})()"""

_JS_EXTRACT_STORE_PRODUCTS = """(() => {
    const items = [];
    const selectors = [
        '[class*="food-item"]', '[class*="FoodItem"]',
        '[class*="product-item"]', '[class*="spu-item"]',
        '[class*="menu-item"]',
    ];
    let elements = [];
    for (const sel of selectors) {
        elements = document.querySelectorAll(sel);
        if (elements.length > 0) break;
    }
    for (const el of Array.from(elements).slice(0, 50)) {
        try {
            const nameEl = el.querySelector('[class*="name"], [class*="title"]');
            const name = nameEl ? nameEl.textContent.trim() : '';
            const priceEl = el.querySelector('[class*="price"]');
            const price = priceEl
                ? parseFloat(priceEl.textContent.replace(/[^0-9.]/g, '')) || 0
                : 0;
            const salesEl = el.querySelector('[class*="sale"], [class*="month"]');
            const sales = salesEl
                ? parseInt(salesEl.textContent.replace(/[^0-9]/g, '')) || 0
                : 0;
            if (name) items.push({name, price, sales});
        } catch(e) {}
    }
    return JSON.stringify(items);
})()"""

_JS_EXTRACT_HOT_KEYWORDS = """(() => {
    const words = [];
    const selectors = [
        '[class*="hot-word"]', '[class*="HotWord"]',
        '[class*="search-word"]', '[class*="suggest"]',
        '[class*="history"] [class*="tag"]',
        '[class*="hot"] [class*="item"]',
    ];
    let elements = [];
    for (const sel of selectors) {
        elements = document.querySelectorAll(sel);
        if (elements.length > 0) break;
    }
    for (const el of elements) {
        const text = el.textContent.trim();
        if (text && text.length < 20) words.push(text);
    }
    return JSON.stringify([...new Set(words)]);
})()"""


async def _random_delay(min_s: float = 2.0, max_s: float = 5.0):
    """随机延迟，防止被反爬检测。"""
    await asyncio.sleep(random.uniform(min_s, max_s))


class MeituanH5Scraper:
    """美团 H5 移动端数据采集器。

    通过 ActionBook Extension 模式控制 Chrome 浏览器，
    在美团外卖 H5 页面搜索并提取数据。
    集成反检测模块：指纹伪装、行为模拟、验证码处理、智能调度。

    所有方法采集失败时返回空列表，不抛异常。
    """

    def __init__(
        self,
        cli: Optional[_ActionBookCLI] = None,
        default_location: Tuple[float, float] = DEFAULT_LOCATION,
        fingerprint_mgr: Optional[FingerprintManager] = None,
        behavior_sim: Optional[BehaviorSimulator] = None,
        captcha_handler: Optional[CaptchaHandler] = None,
        scheduler: Optional[SmartScheduler] = None,
    ):
        self._cli = cli or _ActionBookCLI(use_extension=True, timeout=30)
        self._default_location = default_location
        self._fp_mgr = fingerprint_mgr or FingerprintManager()
        self._behavior = behavior_sim or BehaviorSimulator()
        self._captcha = captcha_handler or CaptchaHandler()
        self._scheduler = scheduler or SmartScheduler()

    async def _inject_anti_detect(self, session_key: str = "meituan") -> None:
        """注入反检测脚本：stealth.js + 指纹伪装。"""
        try:
            # 注入 stealth.js
            if _STEALTH_JS:
                await self._cli.browser_eval(_STEALTH_JS)
            # 注入指纹
            fp = self._fp_mgr.get_fingerprint(session_key)
            await self._cli.browser_eval(fp.generate_inject_js())
        except Exception as e:
            logger.debug(f"Anti-detect injection error: {e}")

    async def _smart_delay(self, content_length: int = 0) -> None:
        """基于行为模型的智能延迟（替代固定延迟）。"""
        stay_ms = self._behavior.estimate_page_stay(content_length)
        # 加入随机性
        jitter = random.uniform(0.8, 1.3)
        await asyncio.sleep(stay_ms * jitter / 1000)

    async def _check_and_handle_captcha(self) -> bool:
        """检测并处理验证码。返回 True 表示已处理/无验证码。"""
        result = await self._captcha.detect_and_handle(self._cli.browser_eval)
        if result is None:
            return True  # 无验证码
        return result.success

    def _build_search_url(self, keyword: str, location: Optional[Tuple[float, float]] = None) -> str:
        lng, lat = location or self._default_location
        return _SEARCH_URL.format(keyword=quote(keyword), lat=lat, lng=lng)

    def _build_store_url(self, store_id: str, location: Optional[Tuple[float, float]] = None) -> str:
        lng, lat = location or self._default_location
        return _STORE_URL.format(store_id=store_id, lat=lat, lng=lng)

    async def search_products(
        self,
        keyword: str,
        location: Optional[Tuple[float, float]] = None,
        limit: int = 20,
    ) -> List[CompetitorProduct]:
        """搜索美团 H5 页面的商品/店铺。

        Args:
            keyword: 搜索关键词（如 "血压计"）
            location: (经度, 纬度)，默认光谷
            limit: 最大返回数量

        Returns:
            CompetitorProduct 列表，采集失败返回空列表
        """
        try:
            # 智能调度：等待可用时隙
            if not await self._scheduler.wait_for_slot("meituan"):
                logger.warning("Scheduler: meituan daily limit reached")
                return []

            url = self._build_search_url(keyword, location)
            logger.info(f"H5 search: '{keyword}' at {url}")

            await self._cli.browser_open(url)
            await asyncio.sleep(1)

            # 注入反检测脚本
            await self._inject_anti_detect(f"meituan_search_{keyword}")

            # 注入 XHR 拦截器
            await self._cli.browser_eval(_JS_INJECT_XHR_INTERCEPTOR)

            # 检测验证码
            await self._check_and_handle_captcha()

            # 基于行为模型的等待（替代固定 3-5s）
            await self._smart_delay()

            # 策略 1：尝试从拦截的 XHR 中提取
            products = await self._extract_from_xhr(limit)
            if products:
                logger.info(f"H5 search '{keyword}': got {len(products)} from XHR")
                return products

            # 策略 2：JS DOM 提取
            products = await self._extract_from_dom(limit)
            if products:
                logger.info(f"H5 search '{keyword}': got {len(products)} from DOM")
                return products

            # 策略 3：页面文本解析（最后手段）
            products = await self._extract_from_text(keyword, limit)
            if products:
                logger.info(f"H5 search '{keyword}': got {len(products)} from text")
                return products

            logger.warning(f"H5 search '{keyword}': no results from any strategy")
            self._scheduler.report_failure("meituan", is_anti_crawl=False)
            return []

        except Exception as e:
            logger.error(f"H5 search '{keyword}' failed: {e}")
            self._scheduler.report_failure("meituan", is_anti_crawl="403" in str(e) or "验证" in str(e))
            return []
        finally:
            try:
                await self._cli.browser_close()
            except Exception:
                pass
            await self._smart_delay()

    async def _extract_from_xhr(self, limit: int) -> List[CompetitorProduct]:
        """从拦截的 XHR 响应中提取数据。"""
        try:
            raw = await self._cli.browser_eval(_JS_GET_CAPTURED)
            if not raw:
                return []
            captured = json.loads(raw)
            if not captured:
                return []

            products = []
            for entry in captured:
                data = entry.get("data", {})
                # 美团 API 响应结构：data.poiList 或 data.searchResult
                poi_list = (
                    data.get("data", {}).get("poiList")
                    or data.get("data", {}).get("searchResult")
                    or data.get("poiList")
                    or data.get("searchResult")
                    or []
                )
                for poi in poi_list:
                    # 店铺级别的数据
                    store_name = poi.get("name", "")
                    store_id = str(poi.get("poiId", poi.get("dpShopId", "")))
                    rating = float(poi.get("wmPoiScore", poi.get("wm_poi_score", 0)) or 0)
                    distance_text = poi.get("distance", "0")
                    distance = self._parse_distance(distance_text)
                    monthly_sales = self._parse_monthly_sales(
                        poi.get("monthSaleTip", poi.get("month_sale_tip", ""))
                    )

                    # 商品列表
                    spus = poi.get("foodSpuTags", poi.get("food_spu_tags", []))
                    if isinstance(spus, list):
                        for spu in spus:
                            if isinstance(spu, dict):
                                for food in spu.get("spus", [spu]):
                                    products.append(CompetitorProduct(
                                        product_id=str(food.get("spuId", food.get("id", store_id))),
                                        name=food.get("name", food.get("spuName", store_name)),
                                        price=float(food.get("price", food.get("currentPrice", 0)) or 0) / 100
                                            if food.get("price", 0) > 1000
                                            else float(food.get("price", food.get("currentPrice", 0)) or 0),
                                        monthly_sales=int(food.get("monthSale", food.get("month_sale", monthly_sales)) or 0),
                                        store_name=store_name,
                                    ))

                    # 如果没有商品细节，至少记录店铺
                    if not spus:
                        products.append(CompetitorProduct(
                            product_id=store_id,
                            name=store_name,
                            price=0.0,
                            monthly_sales=monthly_sales,
                            store_name=store_name,
                        ))

            return products[:limit]
        except Exception as e:
            logger.debug(f"XHR extraction failed: {e}")
            return []

    async def _extract_from_dom(self, limit: int) -> List[CompetitorProduct]:
        """从 DOM 提取搜索结果。"""
        try:
            raw = await self._cli.browser_eval(_JS_EXTRACT_SEARCH_RESULTS)
            if not raw:
                return []
            items = json.loads(raw)
            if not items:
                return []

            products = []
            for item in items[:limit]:
                products.append(CompetitorProduct(
                    product_id=item.get("storeId", ""),
                    name=item.get("name", ""),
                    price=float(item.get("price", 0)),
                    monthly_sales=int(item.get("sales", 0)),
                    store_name=item.get("storeName", item.get("name", "")),
                ))
            return products
        except Exception as e:
            logger.debug(f"DOM extraction failed: {e}")
            return []

    async def _extract_from_text(self, keyword: str, limit: int) -> List[CompetitorProduct]:
        """从页面纯文本中解析数据（最后手段）。"""
        try:
            text = await self._cli.browser_text()
            if not text or len(text) < 50:
                return []

            products = []
            # 尝试匹配 "店名 评分 月售xxx 距离"模式
            lines = text.split("\n")
            current_store = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                sales_match = re.search(r"月售\s*(\d+)", line)
                price_match = re.search(r"[¥￥]\s*(\d+\.?\d*)", line)
                rating_match = re.search(r"(\d\.\d)\s*分?", line)

                if sales_match and current_store:
                    products.append(CompetitorProduct(
                        product_id="",
                        name=current_store,
                        price=float(price_match.group(1)) if price_match else 0.0,
                        monthly_sales=int(sales_match.group(1)),
                        store_name=current_store,
                    ))
                    current_store = ""
                elif len(line) > 4 and not sales_match and not price_match:
                    # 可能是店名/商品名
                    if keyword in line or len(line) < 30:
                        current_store = line

            return products[:limit]
        except Exception as e:
            logger.debug(f"Text extraction failed: {e}")
            return []

    async def get_store_products(
        self,
        store_id: str,
        location: Optional[Tuple[float, float]] = None,
    ) -> List[CompetitorProduct]:
        """获取指定店铺的商品列表。

        Args:
            store_id: 美团店铺ID（dpShopId）
            location: (经度, 纬度)

        Returns:
            CompetitorProduct 列表
        """
        try:
            if not await self._scheduler.wait_for_slot("meituan"):
                return []

            url = self._build_store_url(store_id, location)
            logger.info(f"H5 store products: store_id={store_id}")

            await self._cli.browser_open(url)
            await self._inject_anti_detect(f"meituan_store_{store_id}")
            await self._check_and_handle_captcha()
            await self._smart_delay()

            # JS DOM 提取
            raw = await self._cli.browser_eval(_JS_EXTRACT_STORE_PRODUCTS)
            if raw:
                items = json.loads(raw)
                products = []
                for item in items:
                    products.append(CompetitorProduct(
                        product_id=store_id,
                        name=item.get("name", ""),
                        price=float(item.get("price", 0)),
                        monthly_sales=int(item.get("sales", 0)),
                        store_name="",
                    ))
                if products:
                    logger.info(f"Store {store_id}: got {len(products)} products")
                    return products

            logger.warning(f"Store {store_id}: no products extracted")
            return []

        except Exception as e:
            logger.error(f"Store {store_id} products failed: {e}")
            self._scheduler.report_failure("meituan", is_anti_crawl="403" in str(e))
            return []
        finally:
            try:
                await self._cli.browser_close()
            except Exception:
                pass
            await self._smart_delay()

    async def get_category_ranking(
        self,
        category: str,
        location: Optional[Tuple[float, float]] = None,
        limit: int = 20,
    ) -> List[dict]:
        """获取品类页热门排行。

        Args:
            category: 品类名称（如 "医疗器械"）
            location: (经度, 纬度)
            limit: 最大返回数

        Returns:
            排行数据列表 [{"name": ..., "sales": ..., "rating": ..., ...}]
        """
        try:
            # 品类页用搜索代替（H5 没有独立品类入口）
            products = await self.search_products(category, location, limit)
            ranking = []
            for i, p in enumerate(products):
                ranking.append({
                    "rank": i + 1,
                    "name": p.name,
                    "price": p.price,
                    "monthly_sales": p.monthly_sales,
                    "store_name": p.store_name,
                })
            return ranking
        except Exception as e:
            logger.error(f"Category ranking '{category}' failed: {e}")
            return []

    async def search_hot_keywords(
        self,
        category: str = "",
    ) -> List[str]:
        """获取搜索框热搜词/联想词。

        Args:
            category: 可选品类过滤

        Returns:
            热搜词列表
        """
        try:
            lng, lat = self._default_location
            url = f"https://h5.waimai.meituan.com/waimai/mindex/search?lat={lat}&lng={lng}"
            logger.info(f"H5 hot keywords: category={category or 'all'}")

            await self._cli.browser_open(url)
            await _random_delay(2.0, 4.0)

            # 提取热搜词
            raw = await self._cli.browser_eval(_JS_EXTRACT_HOT_KEYWORDS)
            keywords = []
            if raw:
                try:
                    keywords = json.loads(raw)
                except json.JSONDecodeError:
                    pass

            # 如果有 category 过滤，输入触发联想词
            if category and not keywords:
                try:
                    await self._cli.browser_eval(f"""
                        const input = document.querySelector(
                            'input[type="search"], input[placeholder*="搜索"], input[class*="search"]'
                        );
                        if (input) {{
                            input.value = '{category}';
                            input.dispatchEvent(new Event('input', {{bubbles: true}}));
                        }}
                    """)
                    await _random_delay(1.5, 3.0)

                    # 提取联想词
                    raw2 = await self._cli.browser_eval("""(() => {
                        const words = [];
                        const els = document.querySelectorAll(
                            '[class*="suggest"] [class*="item"], [class*="auto-complete"] li'
                        );
                        for (const el of els) {
                            const t = el.textContent.trim();
                            if (t && t.length < 20) words.push(t);
                        }
                        return JSON.stringify(words);
                    })()""")
                    if raw2:
                        keywords = json.loads(raw2)
                except Exception:
                    pass

            if keywords:
                logger.info(f"Hot keywords: got {len(keywords)}")
            else:
                logger.warning("Hot keywords: none found")

            return keywords

        except Exception as e:
            logger.error(f"Hot keywords failed: {e}")
            return []
        finally:
            try:
                await self._cli.browser_close()
            except Exception:
                pass
            await _random_delay(2.0, 4.0)

    async def cleanup(self):
        """清理资源。"""
        await self._cli.cleanup()

    # ── 辅助方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_distance(text) -> float:
        """解析距离文本，返回 km。"""
        if isinstance(text, (int, float)):
            return float(text)
        text = str(text)
        m = re.search(r"([\d.]+)\s*(km|m|米|公里)?", text, re.IGNORECASE)
        if not m:
            return 0.0
        val = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in ("m", "米"):
            return val / 1000
        return val

    @staticmethod
    def _parse_monthly_sales(text) -> int:
        """解析月销文本，如 '月售1234'。"""
        if isinstance(text, (int, float)):
            return int(text)
        text = str(text)
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else 0
