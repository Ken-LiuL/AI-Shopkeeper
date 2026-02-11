"""美团 App 自动化客户端 — 基于 uiautomator2 控制搜索、翻页、进店。

配合 mitmproxy 拦截 API 响应，实现搜索→抓包→解析的自动化流程。
反检测：随机延迟、贝塞尔曲线滑动、操作间隔抖动。
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MEITUAN_PACKAGE = "com.sankuai.meituan"
MEITUAN_ACTIVITY = "com.meituan.android.pt.homepage.activity.MainActivity"

# 医疗器械相关搜索关键词
DEFAULT_KEYWORDS = [
    "血压计", "血糖仪", "体温计", "血糖试纸", "雾化器", "制氧机",
    "创可贴", "医用口罩", "退烧贴", "酒精棉片", "碘伏", "纱布",
    "轮椅", "拐杖", "护腰带", "颈椎枕", "热敷贴", "艾灸贴",
]


def _random_delay(min_s: float = 1.5, max_s: float = 4.0) -> float:
    """生成符合正态分布的随机延迟。"""
    mean = (min_s + max_s) / 2
    std = (max_s - min_s) / 4
    delay = random.gauss(mean, std)
    return max(min_s, min(max_s, delay))


def _bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int = 20,
) -> list[tuple[int, int]]:
    """生成贝塞尔曲线轨迹点，模拟自然滑动。"""
    # 随机控制点（制造弧度）
    cx = (start[0] + end[0]) / 2 + random.uniform(-50, 50)
    cy = (start[1] + end[1]) / 2 + random.uniform(-30, 30)

    points = []
    for i in range(steps + 1):
        t = i / steps
        # 非线性时间（慢快慢）
        t = t * t * (3 - 2 * t)  # smoothstep
        x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * cx + t ** 2 * end[0]
        y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * cy + t ** 2 * end[1]
        points.append((int(x), int(y)))
    return points


@dataclass
class ScrollConfig:
    """滑动配置。"""
    direction: str = "up"  # up=向上滑（看更多内容）
    distance_ratio: float = 0.5  # 滑动距离占屏幕比例
    duration_ms: int = 800
    pause_after_s: float = 2.0


class MeituanClient:
    """美团 App 自动化客户端。

    Usage:
        import uiautomator2 as u2
        d = u2.connect("emulator-5554")
        client = MeituanClient(d)

        await client.launch_app()
        await client.search("血压计")
        await client.scroll_results(pages=3)
        stores = await client.get_visible_stores()
        await client.enter_store(stores[0])
    """

    def __init__(
        self,
        device: Any,  # uiautomator2.Device
        on_api_response: Optional[Callable] = None,
    ):
        self.d = device
        self.on_api_response = on_api_response
        self._screen_width = 0
        self._screen_height = 0

    async def _init_screen_size(self) -> None:
        if not self._screen_width:
            info = await asyncio.to_thread(self.d.info)
            self._screen_width = info.get("displayWidth", 1080)
            self._screen_height = info.get("displayHeight", 1920)

    async def _delay(self, min_s: float = 1.5, max_s: float = 4.0) -> None:
        """反检测：随机等待。"""
        await asyncio.sleep(_random_delay(min_s, max_s))

    async def _natural_swipe(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        duration_ms: int = 800,
    ) -> None:
        """贝塞尔曲线自然滑动。"""
        points = _bezier_points(start, end, steps=random.randint(15, 25))
        step_duration = duration_ms / len(points) / 1000

        # uiautomator2 的 swipe_points
        await asyncio.to_thread(
            self.d.swipe_points, points, duration_ms / 1000
        )

    # ── App Lifecycle ────────────────────────────────────────────────

    async def launch_app(self) -> bool:
        """启动美团 App 并等待主页加载。"""
        logger.info("Launching Meituan App...")
        await asyncio.to_thread(self.d.app_start, MEITUAN_PACKAGE, MEITUAN_ACTIVITY)
        await self._delay(3.0, 5.0)
        await self._init_screen_size()

        # 等待主页加载（检测搜索框）
        for _ in range(10):
            if await self._find_element_exists(resourceId="com.sankuai.meituan:id/search_bar"):
                logger.info("Meituan App launched successfully")
                return True
            if await self._find_element_exists(text="搜索"):
                return True
            await asyncio.sleep(1)

        logger.warning("Meituan App launch: search bar not found, proceeding anyway")
        return True

    async def stop_app(self) -> None:
        await asyncio.to_thread(self.d.app_stop, MEITUAN_PACKAGE)

    async def restart_app(self) -> bool:
        await self.stop_app()
        await self._delay(2.0, 3.0)
        return await self.launch_app()

    # ── Navigation ───────────────────────────────────────────────────

    async def navigate_to_category(self, category: str = "医疗器械") -> bool:
        """导航到指定品类页面。"""
        logger.info(f"Navigating to category: {category}")

        # 尝试点击分类入口
        for text in ["分类", "全部分类", "更多"]:
            if await self._click_text(text):
                await self._delay(2.0, 3.0)
                break

        # 在分类页面查找目标品类
        for attempt in range(3):
            if await self._click_text(category):
                await self._delay(2.0, 3.0)
                logger.info(f"Navigated to {category}")
                return True
            # 向下滑动查找更多分类
            await self._scroll_down(ratio=0.3)
            await self._delay(1.0, 2.0)

        logger.warning(f"Category '{category}' not found")
        return False

    # ── Search ───────────────────────────────────────────────────────

    async def search(self, keyword: str) -> bool:
        """在美团 App 中执行搜索。"""
        logger.info(f"Searching: {keyword}")

        # 点击搜索框
        clicked = (
            await self._click_resource_id("com.sankuai.meituan:id/search_bar")
            or await self._click_text("搜索")
            or await self._click_description("搜索")
        )
        if not clicked:
            logger.warning("Search bar not found")
            return False

        await self._delay(1.0, 2.0)

        # 清空并输入关键词
        search_input = await self._find_element(
            resourceId="com.sankuai.meituan:id/search_edit",
            className="android.widget.EditText",
        )
        if search_input:
            await asyncio.to_thread(search_input.clear_text)
            await self._delay(0.3, 0.6)
            # 逐字符输入（模拟真人打字）
            for char in keyword:
                await asyncio.to_thread(search_input.send_keys, char)
                await asyncio.sleep(random.uniform(0.05, 0.15))
        else:
            # fallback: 直接使用 shell input
            await asyncio.to_thread(self.d.shell, f"input text '{keyword}'")

        await self._delay(0.5, 1.0)

        # 点击搜索按钮或回车
        await asyncio.to_thread(self.d.press, "enter")
        await self._delay(2.0, 4.0)

        logger.info(f"Search completed: {keyword}")
        return True

    async def search_multiple(
        self,
        keywords: Optional[list[str]] = None,
        pages_per_keyword: int = 3,
    ) -> None:
        """批量搜索多个关键词，每个翻若干页。"""
        keywords = keywords or DEFAULT_KEYWORDS

        for i, keyword in enumerate(keywords):
            logger.info(f"[{i+1}/{len(keywords)}] Searching: {keyword}")
            success = await self.search(keyword)
            if not success:
                continue

            # 翻页浏览结果
            await self.scroll_results(pages=pages_per_keyword)

            # 返回搜索页
            await asyncio.to_thread(self.d.press, "back")
            await self._delay(1.5, 3.0)

            # 关键词间增加额外延迟
            if i < len(keywords) - 1:
                await self._delay(2.0, 5.0)

    # ── Scrolling ────────────────────────────────────────────────────

    async def scroll_results(self, pages: int = 3) -> None:
        """滑动浏览搜索结果页。"""
        for page in range(pages):
            logger.debug(f"Scrolling page {page + 1}/{pages}")
            await self._scroll_down(ratio=random.uniform(0.4, 0.6))
            await self._delay(1.5, 3.5)

            # 偶尔停顿更久（模拟阅读）
            if random.random() < 0.3:
                await self._delay(3.0, 6.0)

    async def _scroll_down(self, ratio: float = 0.5) -> None:
        """自然向下滑动。"""
        await self._init_screen_size()
        w, h = self._screen_width, self._screen_height

        start_x = w // 2 + random.randint(-30, 30)
        start_y = int(h * (0.5 + ratio / 2)) + random.randint(-20, 20)
        end_x = start_x + random.randint(-10, 10)
        end_y = int(h * (0.5 - ratio / 2)) + random.randint(-20, 20)

        await self._natural_swipe(
            (start_x, start_y),
            (end_x, end_y),
            duration_ms=random.randint(600, 1200),
        )

    # ── Store Operations ─────────────────────────────────────────────

    async def get_visible_stores(self) -> list[dict]:
        """获取当前屏幕上可见的店铺列表（从 UI 元素提取）。"""
        # 这里从 UI 获取基础信息；详细数据由 mitmproxy 从 API 响应中提取
        stores = []
        try:
            # 美团搜索结果中的店铺卡片
            elements = await asyncio.to_thread(
                self.d.xpath,
                '//*[contains(@resource-id, "poi_name") or contains(@resource-id, "shop_name")]',
            )
            items = await asyncio.to_thread(elements.all)
            for el in items:
                stores.append({
                    "name": el.text or "",
                    "bounds": el.bounds() if hasattr(el, "bounds") else None,
                })
        except Exception as e:
            logger.debug(f"get_visible_stores xpath failed: {e}")

        return stores

    async def enter_store(self, store: dict) -> bool:
        """进入指定店铺详情页。"""
        name = store.get("name", "")
        logger.info(f"Entering store: {name}")

        if name and await self._click_text(name):
            await self._delay(2.0, 4.0)
            return True

        # 尝试通过坐标点击
        bounds = store.get("bounds")
        if bounds:
            cx = (bounds[0] + bounds[2]) // 2
            cy = (bounds[1] + bounds[3]) // 2
            await asyncio.to_thread(self.d.click, cx, cy)
            await self._delay(2.0, 4.0)
            return True

        return False

    async def browse_store_products(self, max_scrolls: int = 5) -> None:
        """在店铺详情页浏览商品列表（触发 API 请求供 mitmproxy 拦截）。"""
        logger.info("Browsing store products...")
        for i in range(max_scrolls):
            await self._scroll_down(ratio=random.uniform(0.3, 0.5))
            await self._delay(1.5, 3.0)

            # 偶尔点击商品查看详情
            if random.random() < 0.2:
                await self._click_random_product()
                await self._delay(2.0, 4.0)
                await asyncio.to_thread(self.d.press, "back")
                await self._delay(1.0, 2.0)

    async def go_back(self) -> None:
        """返回上一页。"""
        await asyncio.to_thread(self.d.press, "back")
        await self._delay(1.0, 2.0)

    # ── Screenshot ───────────────────────────────────────────────────

    async def screenshot(self, path: str = "/tmp/meituan_screenshot.png") -> str:
        """截图保存。"""
        img = await asyncio.to_thread(self.d.screenshot)
        img.save(path)
        return path

    # ── Private Helpers ──────────────────────────────────────────────

    async def _find_element(self, **kwargs: Any) -> Any:
        """查找 UI 元素。"""
        try:
            el = await asyncio.to_thread(lambda: self.d(**kwargs))
            exists = await asyncio.to_thread(el.exists)
            return el if exists else None
        except Exception:
            return None

    async def _find_element_exists(self, **kwargs: Any) -> bool:
        el = await self._find_element(**kwargs)
        return el is not None

    async def _click_text(self, text: str) -> bool:
        el = await self._find_element(text=text)
        if el:
            await asyncio.to_thread(el.click)
            return True
        return False

    async def _click_description(self, desc: str) -> bool:
        el = await self._find_element(description=desc)
        if el:
            await asyncio.to_thread(el.click)
            return True
        return False

    async def _click_resource_id(self, rid: str) -> bool:
        el = await self._find_element(resourceId=rid)
        if el:
            await asyncio.to_thread(el.click)
            return True
        return False

    async def _click_random_product(self) -> None:
        """随机点击一个商品（增加行为真实性）。"""
        await self._init_screen_size()
        x = random.randint(
            self._screen_width // 4,
            self._screen_width * 3 // 4,
        )
        y = random.randint(
            self._screen_height // 3,
            self._screen_height * 2 // 3,
        )
        await asyncio.to_thread(self.d.click, x, y)
