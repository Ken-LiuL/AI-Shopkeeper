"""采集调度器 — 定时触发、账号轮换、频率控制、重试。

协调 DeviceManager + MeituanClient + MeituanProxy + DataExtractor 的完整采集流程。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class TaskType(str, Enum):
    SEARCH_KEYWORDS = "search_keywords"
    COMPETITOR_STORES = "competitor_stores"
    STORE_PRODUCTS = "store_products"
    CATEGORY_RANKING = "category_ranking"


@dataclass
class TaskConfig:
    """采集任务配置。"""
    task_type: TaskType
    keywords: list[str] = field(default_factory=list)
    store_ids: list[str] = field(default_factory=list)
    pages_per_keyword: int = 3
    max_stores: int = 5
    max_retries: int = 2


@dataclass
class TaskResult:
    task_type: TaskType
    success: bool
    device_serial: str = ""
    stores_collected: int = 0
    products_collected: int = 0
    keywords_searched: int = 0
    error: str = ""
    duration_seconds: float = 0.0


# 默认采集计划（参考 docs/competitor-data-rpc.md §7）
DEFAULT_SCHEDULE = [
    # (hour, minute, task_type)
    (6, 0, TaskType.COMPETITOR_STORES),
    (10, 0, TaskType.SEARCH_KEYWORDS),
    (14, 0, TaskType.STORE_PRODUCTS),
    (20, 0, TaskType.SEARCH_KEYWORDS),
]

DEFAULT_KEYWORDS = [
    "血压计", "血糖仪", "体温计", "血糖试纸", "雾化器", "制氧机",
    "创可贴", "医用口罩", "退烧贴", "酒精棉片", "碘伏", "纱布",
    "轮椅", "拐杖", "护腰带", "颈椎枕", "热敷贴", "艾灸贴",
]


class CollectionScheduler:
    """采集调度器。

    Usage:
        from src.rpc import DeviceManager, CollectionScheduler

        device_mgr = DeviceManager()
        device_mgr.add_device("emulator-5554", name="emu1")

        scheduler = CollectionScheduler(device_mgr, db_pool=pool, proxy_port=8080)
        await scheduler.run_once(TaskType.SEARCH_KEYWORDS)  # 手动触发
        await scheduler.start()  # 按计划自动运行
    """

    def __init__(
        self,
        device_manager: Any,  # DeviceManager
        db_pool: Any = None,
        proxy_port: int = 8080,
        proxy_host: str = "10.0.2.2",  # Android 虚拟机访问宿主机
        cooldown_seconds: int = 14400,  # 设备冷却 4 小时
    ):
        self.device_mgr = device_manager
        self.db_pool = db_pool
        self.proxy_port = proxy_port
        self.proxy_host = proxy_host
        self.cooldown_seconds = cooldown_seconds
        self._running = False
        self._task_history: list[TaskResult] = []

    async def run_once(
        self,
        task_type: TaskType,
        config: Optional[TaskConfig] = None,
    ) -> TaskResult:
        """执行单次采集任务。"""
        if config is None:
            config = TaskConfig(
                task_type=task_type,
                keywords=DEFAULT_KEYWORDS,
            )

        start_time = asyncio.get_event_loop().time()

        # 1. 获取可用设备
        device = self.device_mgr.acquire_device()
        if not device:
            return TaskResult(
                task_type=task_type, success=False,
                error="No available device",
            )

        logger.info(f"Task {task_type} starting on device {device.serial}")

        try:
            # 2. 设置代理
            await self.device_mgr.set_proxy(device.serial, self.proxy_host, self.proxy_port)

            # 3. 创建客户端
            import uiautomator2 as u2
            d = u2.connect(device.serial)

            from src.rpc.meituan_client import MeituanClient
            from src.rpc.data_extractor import DataExtractor

            extractor = DataExtractor(db_pool=self.db_pool)
            client = MeituanClient(d)

            # 4. 启动 App
            await client.launch_app()

            # 5. 执行任务
            result = await self._execute_task(client, extractor, config)
            result.device_serial = device.serial

            # 6. 清理
            await client.stop_app()
            await self.device_mgr.clear_proxy(device.serial)

            elapsed = asyncio.get_event_loop().time() - start_time
            result.duration_seconds = elapsed
            logger.info(
                f"Task {task_type} completed in {elapsed:.0f}s: "
                f"stores={result.stores_collected}, products={result.products_collected}"
            )

            self._task_history.append(result)
            return result

        except Exception as e:
            logger.error(f"Task {task_type} failed: {e}")
            self.device_mgr.mark_error(device.serial)
            return TaskResult(
                task_type=task_type, success=False,
                device_serial=device.serial, error=str(e),
            )
        finally:
            self.device_mgr.release_device(
                device.serial, cooldown_seconds=self.cooldown_seconds
            )

    async def _execute_task(
        self,
        client: Any,  # MeituanClient
        extractor: Any,  # DataExtractor
        config: TaskConfig,
    ) -> TaskResult:
        """分发执行具体任务。"""
        if config.task_type == TaskType.SEARCH_KEYWORDS:
            return await self._task_search_keywords(client, extractor, config)
        elif config.task_type == TaskType.COMPETITOR_STORES:
            return await self._task_competitor_stores(client, extractor, config)
        elif config.task_type == TaskType.STORE_PRODUCTS:
            return await self._task_store_products(client, extractor, config)
        elif config.task_type == TaskType.CATEGORY_RANKING:
            return await self._task_category_ranking(client, extractor, config)
        else:
            return TaskResult(task_type=config.task_type, success=False, error="Unknown task type")

    async def _task_search_keywords(
        self, client: Any, extractor: Any, config: TaskConfig,
    ) -> TaskResult:
        """搜索关键词任务：搜索每个关键词并翻页。"""
        keywords = config.keywords or DEFAULT_KEYWORDS
        searched = 0

        for keyword in keywords:
            success = await client.search(keyword)
            if success:
                await client.scroll_results(pages=config.pages_per_keyword)
                searched += 1
            await client.go_back()

        return TaskResult(
            task_type=TaskType.SEARCH_KEYWORDS,
            success=searched > 0,
            keywords_searched=searched,
        )

    async def _task_competitor_stores(
        self, client: Any, extractor: Any, config: TaskConfig,
    ) -> TaskResult:
        """竞品店铺任务：搜索关键词后进入每个店铺。"""
        # 搜索一个代表性关键词
        keyword = random.choice(config.keywords or DEFAULT_KEYWORDS)
        await client.search(keyword)
        await asyncio.sleep(3)

        stores = await client.get_visible_stores()
        entered = 0

        for store in stores[:config.max_stores]:
            if await client.enter_store(store):
                await client.browse_store_products(max_scrolls=3)
                entered += 1
                await client.go_back()

        return TaskResult(
            task_type=TaskType.COMPETITOR_STORES,
            success=entered > 0,
            stores_collected=entered,
        )

    async def _task_store_products(
        self, client: Any, extractor: Any, config: TaskConfig,
    ) -> TaskResult:
        """店铺商品任务：浏览指定店铺的商品列表。"""
        # TODO: 实现通过店铺 ID 直接导航
        return TaskResult(task_type=TaskType.STORE_PRODUCTS, success=True)

    async def _task_category_ranking(
        self, client: Any, extractor: Any, config: TaskConfig,
    ) -> TaskResult:
        """品类排行任务：浏览品类页面。"""
        success = await client.navigate_to_category("医疗器械")
        if success:
            await client.scroll_results(pages=5)
        return TaskResult(task_type=TaskType.CATEGORY_RANKING, success=success)

    # ── Scheduled Execution ──────────────────────────────────────────

    async def start(self, schedule: Optional[list] = None) -> None:
        """启动定时调度（阻塞运行）。"""
        schedule = schedule or DEFAULT_SCHEDULE
        self._running = True
        logger.info(f"Scheduler started with {len(schedule)} tasks/day")

        while self._running:
            now = datetime.now(CST)
            for hour, minute, task_type in schedule:
                # 检查是否到了执行时间（±2分钟窗口）
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                diff = abs((now - target).total_seconds())
                if diff < 120:  # 2 分钟窗口
                    logger.info(f"Scheduled task triggered: {task_type}")
                    await self.run_once(task_type)

            # 每分钟检查一次
            await asyncio.sleep(60)

    def stop(self) -> None:
        self._running = False
        logger.info("Scheduler stopped")

    @property
    def history(self) -> list[TaskResult]:
        return self._task_history
