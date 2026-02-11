"""代理池管理 — HTTP/SOCKS5 代理轮换、健康检查、粘性会话。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class ProxyInfo:
    """单个代理信息。"""
    url: str  # http://ip:port or socks5://ip:port
    protocol: str = "http"  # http | socks5
    alive: bool = True
    last_check: float = 0
    fail_count: int = 0
    latency_ms: float = 0
    _domain_locks: Dict[str, float] = field(default_factory=dict)

    @property
    def host(self) -> str:
        parsed = urlparse(self.url)
        return parsed.hostname or ""

    def mark_success(self) -> None:
        self.alive = True
        self.fail_count = 0
        self.last_check = time.time()

    def mark_failure(self) -> None:
        self.fail_count += 1
        if self.fail_count >= 3:
            self.alive = False
        self.last_check = time.time()


class ProxyPool:
    """代理池管理器。

    Features:
    - 从文件或 API 加载代理列表
    - 按域名轮换代理
    - 粘性会话：同一采集任务用同一 IP
    - 健康检查
    - 失败自动切换
    """

    def __init__(
        self,
        enabled: bool = False,
        provider: str = "file",
        file_path: Optional[str] = None,
        api_url: Optional[str] = None,
        health_check_interval: int = 300,
        check_url: str = "https://httpbin.org/ip",
    ):
        self.enabled = enabled
        self.provider = provider
        self.file_path = file_path
        self.api_url = api_url
        self.health_check_interval = health_check_interval
        self.check_url = check_url

        self._proxies: List[ProxyInfo] = []
        self._domain_sticky: Dict[str, ProxyInfo] = {}
        self._session_sticky: Dict[str, ProxyInfo] = {}
        self._loaded = False

    async def load(self) -> int:
        """加载代理列表。返回加载数量。"""
        if self.provider == "file" and self.file_path:
            self._proxies = self._load_from_file(self.file_path)
        elif self.provider == "api" and self.api_url:
            self._proxies = await self._load_from_api(self.api_url)

        self._loaded = True
        logger.info(f"Proxy pool loaded: {len(self._proxies)} proxies")
        return len(self._proxies)

    def _load_from_file(self, path: str) -> List[ProxyInfo]:
        """从文件加载代理列表。

        格式：每行一个代理 URL
        - http://ip:port
        - socks5://user:pass@ip:port
        - ip:port  (默认 http)
        """
        proxies = []
        p = Path(path)
        if not p.exists():
            logger.warning(f"Proxy file not found: {path}")
            return proxies

        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(("http://", "https://", "socks5://", "socks4://")):
                line = f"http://{line}"
            protocol = "socks5" if "socks5" in line else "http"
            proxies.append(ProxyInfo(url=line, protocol=protocol))

        return proxies

    async def _load_from_api(self, api_url: str) -> List[ProxyInfo]:
        """从 API 加载代理列表。"""
        proxies = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = await resp.text()
                    for line in text.strip().splitlines():
                        line = line.strip()
                        if line:
                            if not line.startswith(("http://", "socks5://")):
                                line = f"http://{line}"
                            protocol = "socks5" if "socks5" in line else "http"
                            proxies.append(ProxyInfo(url=line, protocol=protocol))
        except Exception as e:
            logger.error(f"Failed to load proxies from API: {e}")
        return proxies

    def get_proxy(
        self,
        domain: Optional[str] = None,
        session_key: Optional[str] = None,
    ) -> Optional[str]:
        """获取代理 URL。

        Args:
            domain: 按域名分配代理（不同域名用不同 IP）
            session_key: 粘性会话 key（同 key 返回同一代理）

        Returns:
            代理 URL 或 None（无可用代理/未启用）
        """
        if not self.enabled or not self._proxies:
            return None

        alive = [p for p in self._proxies if p.alive]
        if not alive:
            logger.warning("No alive proxies available")
            return None

        # 粘性会话优先
        if session_key and session_key in self._session_sticky:
            proxy = self._session_sticky[session_key]
            if proxy.alive:
                return proxy.url
            del self._session_sticky[session_key]

        # 域名粘性
        if domain and domain in self._domain_sticky:
            proxy = self._domain_sticky[domain]
            if proxy.alive:
                if session_key:
                    self._session_sticky[session_key] = proxy
                return proxy.url
            del self._domain_sticky[domain]

        # 轮换：选择失败次数最少的
        proxy = min(alive, key=lambda p: (p.fail_count, p.latency_ms or 9999))

        if domain:
            self._domain_sticky[domain] = proxy
        if session_key:
            self._session_sticky[session_key] = proxy

        return proxy.url

    def report_success(self, proxy_url: str) -> None:
        """报告代理使用成功。"""
        for p in self._proxies:
            if p.url == proxy_url:
                p.mark_success()
                return

    def report_failure(self, proxy_url: str) -> None:
        """报告代理使用失败，自动切换。"""
        for p in self._proxies:
            if p.url == proxy_url:
                p.mark_failure()
                if not p.alive:
                    logger.warning(f"Proxy marked dead: {proxy_url}")
                    # 从粘性缓存中清除
                    self._domain_sticky = {
                        k: v for k, v in self._domain_sticky.items() if v.url != proxy_url
                    }
                    self._session_sticky = {
                        k: v for k, v in self._session_sticky.items() if v.url != proxy_url
                    }
                return

    async def health_check(self) -> Dict[str, int]:
        """对所有代理执行健康检查。"""
        alive_count = 0
        dead_count = 0

        async def check_one(proxy: ProxyInfo):
            nonlocal alive_count, dead_count
            try:
                start = time.time()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.check_url,
                        proxy=proxy.url if proxy.protocol == "http" else None,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            proxy.latency_ms = (time.time() - start) * 1000
                            proxy.mark_success()
                            alive_count += 1
                            return
            except Exception:
                pass
            proxy.mark_failure()
            dead_count += 1

        tasks = [check_one(p) for p in self._proxies]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(f"Proxy health check: {alive_count} alive, {dead_count} dead")
        return {"alive": alive_count, "dead": dead_count}

    @property
    def stats(self) -> Dict[str, Any]:
        alive = sum(1 for p in self._proxies if p.alive)
        return {
            "total": len(self._proxies),
            "alive": alive,
            "dead": len(self._proxies) - alive,
            "enabled": self.enabled,
        }
