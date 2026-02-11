"""mitmproxy Addon — 拦截美团 API 响应，解析并存储竞品数据。

使用方式：
    # 独立运行 mitmproxy
    mitmdump -s src/rpc/proxy.py -p 8080

    # 或在 Python 中嵌入
    from src.rpc.proxy import MeituanProxy, start_proxy
    await start_proxy(port=8080, db_pool=pool)

Android 设备 HTTPS 证书安装：
    1. 启动 mitmproxy: mitmdump -p 8080
    2. 设备连接代理: adb shell settings put global http_proxy <host>:8080
    3. 设备浏览器访问 mitm.it，下载 CA 证书
    4. Android 7+: 需要将证书安装为系统级证书
       - adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /sdcard/
       - adb shell su -c "mount -o rw,remount /system"
       - 将 PEM 转为系统证书格式并复制到 /system/etc/security/cacerts/
    5. 或使用 Magisk 模块 MagiskTrustUserCerts 自动信任用户证书
    6. SSL Pinning 绕过: 安装 JustTrustMe / TrustMeAlready Xposed 模块
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# 拦截的美团 API 域名
MEITUAN_DOMAINS = [
    "waimai.meituan.com",
    "i.waimai.meituan.com",
    "apimobile.meituan.com",
    "api.meituan.com",
    "mapi.meituan.com",
    "img.meituan.net",  # 不拦截图片，但标记
]

# 需要拦截的 API 路径模式
INTERCEPT_PATTERNS = [
    "/api/v8/poi/food",
    "/api/v8/poi/detail",
    "/search/",
    "/poi/",
    "/food/",
    "/meituan.waimai.c.",
]

# 原始响应保存目录
RAW_RESPONSE_DIR = Path("data/meituan_raw")


class MeituanProxy:
    """mitmproxy addon：拦截美团 API 域名的响应。

    可作为 mitmproxy addon 直接使用，也可嵌入 Python 进程。
    """

    def __init__(
        self,
        on_response: Optional[Callable] = None,
        save_raw: bool = True,
        raw_dir: Optional[Path] = None,
    ):
        self.on_response = on_response  # async callback(url, json_data)
        self.save_raw = save_raw
        self.raw_dir = raw_dir or RAW_RESPONSE_DIR
        self._response_count = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        if self.save_raw:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _is_meituan_api(self, url: str) -> bool:
        """判断是否为需要拦截的美团 API 请求。"""
        # 检查域名
        is_meituan = any(domain in url for domain in MEITUAN_DOMAINS)
        if not is_meituan:
            return False

        # 跳过图片/静态资源
        if any(ext in url for ext in [".png", ".jpg", ".jpeg", ".gif", ".css", ".js", ".ico"]):
            return False

        # 检查路径模式
        return any(pattern in url for pattern in INTERCEPT_PATTERNS)

    def response(self, flow: Any) -> None:
        """mitmproxy hook: 拦截 HTTP 响应。

        注意：mitmproxy addon 的 response() 是同步方法。
        异步处理通过 asyncio.run_coroutine_threadsafe 调度。
        """
        url = flow.request.pretty_url
        if not self._is_meituan_api(url):
            return

        content_type = flow.response.headers.get("content-type", "")
        if "json" not in content_type and "text" not in content_type:
            return

        try:
            body = flow.response.get_text()
            if not body:
                return

            data = json.loads(body)
            self._response_count += 1

            logger.info(
                f"[INTERCEPT #{self._response_count}] {flow.request.method} {url} "
                f"({len(body)} bytes)"
            )

            # 保存原始响应
            if self.save_raw:
                self._save_raw_response(url, flow.request.method, body)

            # 回调处理
            if self.on_response:
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self.on_response(url, data), self._loop
                    )
                else:
                    # 尝试获取当前 loop
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.run_coroutine_threadsafe(
                                self.on_response(url, data), loop
                            )
                        else:
                            loop.run_until_complete(self.on_response(url, data))
                    except RuntimeError:
                        # 没有 event loop，用同步方式记录
                        logger.warning("No event loop for async callback, data saved to raw only")

        except json.JSONDecodeError:
            logger.debug(f"Non-JSON response from {url}")
        except Exception as e:
            logger.error(f"Error processing response from {url}: {e}")

    def _save_raw_response(self, url: str, method: str, body: str) -> None:
        """保存原始 API 响应到文件。"""
        now = datetime.now(CST)
        date_dir = self.raw_dir / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%H%M%S')}_{self._response_count:04d}.json"
        filepath = date_dir / filename

        record = {
            "timestamp": now.isoformat(),
            "method": method,
            "url": url,
            "response": json.loads(body) if body else None,
        }

        filepath.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        logger.debug(f"Raw response saved: {filepath}")

    @property
    def stats(self) -> dict:
        return {"intercepted_count": self._response_count}


# ── Embedded proxy server ────────────────────────────────────────────────────

async def start_proxy(
    port: int = 8080,
    db_pool: Any = None,
    save_raw: bool = True,
) -> None:
    """启动嵌入式 mitmproxy（需要 mitmproxy 库）。

    通常推荐直接用 mitmdump CLI 运行，这里提供编程式启动。
    """
    try:
        from mitmproxy.tools.dump import DumpMaster
        from mitmproxy.options import Options
    except ImportError:
        logger.error("mitmproxy not installed. Run: pip install mitmproxy")
        return

    from src.rpc.data_extractor import DataExtractor

    extractor = DataExtractor(db_pool=db_pool)

    async def handle_response(url: str, data: dict) -> None:
        await extractor.process_response(url, data)

    addon = MeituanProxy(on_response=handle_response, save_raw=save_raw)
    addon._loop = asyncio.get_event_loop()

    opts = Options(listen_port=port, ssl_insecure=True)
    master = DumpMaster(opts)
    master.addons.add(addon)

    logger.info(f"mitmproxy started on port {port}")
    logger.info("Configure device proxy and install CA certificate")

    try:
        await asyncio.to_thread(master.run)
    except KeyboardInterrupt:
        master.shutdown()


# ── mitmproxy addon entry point (for mitmdump -s) ───────────────────────────

# When run as: mitmdump -s src/rpc/proxy.py
# mitmproxy looks for an `addons` list at module level.

_addon_instance = MeituanProxy(save_raw=True)
addons = [_addon_instance]
