"""智能调度 — 采集频率控制、时段模拟、失败退避。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DomainState:
    """每个域名的调度状态。"""

    request_count: int = 0
    daily_count: int = 0
    last_request: float = 0
    last_daily_reset: float = field(default_factory=time.time)
    failure_count: int = 0
    backoff_until: float = 0
    current_interval: float = 0  # 当前请求间隔（秒）


class SmartScheduler:
    """智能采集调度器。

    Features:
    - 每个域名独立限速
    - 模拟真实用户活跃时段
    - 失败退避（403/验证码自动降频）
    - 每日采集量上限
    - 随机化调度间隔
    """

    def __init__(
        self,
        active_hours: tuple = (8, 23),
        max_requests_per_hour: dict[str, int] | None = None,
        max_daily_requests: dict[str, int] | None = None,
        failure_backoff_multiplier: float = 2.0,
        base_interval: float = 5.0,
    ):
        self.active_hours = active_hours
        self.max_per_hour = max_requests_per_hour or {
            "meituan": 30,
            "alibaba": 20,
            "pdd": 20,
        }
        self.max_daily = max_daily_requests or {
            "meituan": 500,
            "alibaba": 300,
            "pdd": 300,
        }
        self.failure_backoff_multiplier = failure_backoff_multiplier
        self.base_interval = base_interval

        self._states: dict[str, DomainState] = defaultdict(DomainState)

    def _resolve_domain(self, domain: str) -> str:
        """将域名映射到限速 key。"""
        if "meituan" in domain:
            return "meituan"
        elif "1688" in domain or "alibaba" in domain:
            return "alibaba"
        elif "pdd" in domain or "yangkeduo" in domain or "pinduoduo" in domain:
            return "pdd"
        return domain

    async def wait_for_slot(self, domain: str) -> bool:
        """等待直到可以发起请求。

        Args:
            domain: 目标域名

        Returns:
            True = 可以请求，False = 超出每日限额/不在活跃时段
        """
        key = self._resolve_domain(domain)
        state = self._states[key]

        # 重置每日计数
        now = time.time()
        if now - state.last_daily_reset > 86400:
            state.daily_count = 0
            state.last_daily_reset = now

        # 检查每日限额
        daily_max = self.max_daily.get(key, 1000)
        if state.daily_count >= daily_max:
            logger.warning(f"Daily limit reached for {key}: {state.daily_count}/{daily_max}")
            return False

        # 检查时段（凌晨降频但不完全停止）
        from datetime import datetime, timedelta, timezone

        cst = timezone(timedelta(hours=8))
        hour = datetime.now(cst).hour
        lo, hi = self.active_hours

        if hour < lo or hour >= hi:
            # 非活跃时段：增加间隔 3-5x
            extra_wait = random.uniform(3, 5)
        else:
            extra_wait = 1.0

        # 检查退避
        if state.backoff_until > now:
            wait = state.backoff_until - now
            logger.info(f"Backing off {key} for {wait:.1f}s")
            await asyncio.sleep(wait)

        # 限速：计算最小间隔
        hourly_max = self.max_per_hour.get(key, 30)
        min_interval = 3600 / hourly_max  # 秒/请求

        # 随机化间隔（±30%）
        interval = min_interval * extra_wait * random.uniform(0.7, 1.3)
        interval = max(interval, self.base_interval)

        # 距上次请求的时间
        elapsed = now - state.last_request
        if elapsed < interval:
            wait = interval - elapsed
            # 加入微小随机偏移
            wait += random.uniform(0, 2)
            logger.debug(f"Scheduler: waiting {wait:.1f}s for {key}")
            await asyncio.sleep(wait)

        state.last_request = time.time()
        state.request_count += 1
        state.daily_count += 1
        state.current_interval = interval

        return True

    def report_success(self, domain: str) -> None:
        """报告请求成功，减少退避。"""
        key = self._resolve_domain(domain)
        state = self._states[key]
        state.failure_count = max(0, state.failure_count - 1)

    def report_failure(self, domain: str, is_anti_crawl: bool = False) -> None:
        """报告请求失败。

        Args:
            domain: 域名
            is_anti_crawl: 是否是反爬响应（403/验证码），会触发更长退避
        """
        key = self._resolve_domain(domain)
        state = self._states[key]
        state.failure_count += 1

        if is_anti_crawl:
            # 反爬响应：指数退避
            backoff = min(
                self.base_interval * (self.failure_backoff_multiplier**state.failure_count),
                600,  # 最大退避 10 分钟
            )
            # 随机化
            backoff *= random.uniform(0.8, 1.2)
            state.backoff_until = time.time() + backoff
            logger.warning(
                f"Anti-crawl detected for {key}, backing off {backoff:.0f}s (failures: {state.failure_count})"
            )
        else:
            # 普通失败：轻微退避
            backoff = self.base_interval * random.uniform(1, 2)
            state.backoff_until = time.time() + backoff

    def can_request(self, domain: str) -> bool:
        """检查当前是否可以请求（非阻塞）。"""
        key = self._resolve_domain(domain)
        state = self._states[key]
        now = time.time()

        # 日限额
        if now - state.last_daily_reset > 86400:
            state.daily_count = 0
            state.last_daily_reset = now

        daily_max = self.max_daily.get(key, 1000)
        if state.daily_count >= daily_max:
            return False

        # 退避中
        if state.backoff_until > now:
            return False

        # 间隔
        hourly_max = self.max_per_hour.get(key, 30)
        min_interval = 3600 / hourly_max
        elapsed = now - state.last_request
        return elapsed >= min_interval * 0.7

    @property
    def stats(self) -> dict[str, dict]:
        now = time.time()
        return {
            key: {
                "requests_today": s.daily_count,
                "failures": s.failure_count,
                "backing_off": s.backoff_until > now,
                "backoff_remaining": max(0, s.backoff_until - now),
                "current_interval": round(s.current_interval, 1),
            }
            for key, s in self._states.items()
        }
