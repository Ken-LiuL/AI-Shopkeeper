"""nodriver 浏览器客户端 — 通过浏览器执行需要 mtgsig 签名的 API。

为什么需要浏览器？
goldengateway 等核心 API 需要 mtgsig 签名（由 h5guard.js 在浏览器端生成），
纯 HTTP 请求无法携带该签名，服务端返回 403。
通过 nodriver 启动真实 Chrome，加载 QNH 页面让 h5guard.js 初始化后，
在浏览器上下文中用 fetch 发请求，浏览器会自动注入 mtgsig 签名。

注意：nodriver 的 evaluate 不支持 async/Promise，必须用 window 变量中转 + sleep 等待。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Cookie 配置文件路径
COOKIE_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "qnh_cookies.json"

QNH_BASE = "https://qnh.meituan.com"

# 单例实例
_instance: BrowserClient | None = None
_instance_lock = asyncio.Lock()


class BrowserClient:
    """nodriver 浏览器客户端，单例模式，多个 syncer 共用。

    通过浏览器上下文执行 fetch 请求，让 h5guard.js 自动注入 mtgsig 签名，
    绕过 goldengateway API 的 403 限制。
    """

    def __init__(self) -> None:
        self._browser = None
        self._page = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._request_count = 0

    @staticmethod
    async def get_instance() -> BrowserClient:
        """获取单例实例（lazy init，第一次调用时才创建）。"""
        global _instance
        async with _instance_lock:
            if _instance is None:
                _instance = BrowserClient()
            return _instance

    async def ensure_ready(self) -> None:
        """确保浏览器已启动并完成 h5guard 初始化。"""
        async with self._init_lock:
            if self._initialized and self._page:
                return
            await self._start_browser()

    async def _start_browser(self) -> None:
        """启动 nodriver 浏览器，加载 cookies，等待 h5guard 初始化。"""
        try:
            import nodriver
            import nodriver.cdp.network

            headless = os.environ.get("HEADLESS", "false").lower() == "true"
            logger.info("启动 nodriver Chrome (headless=%s)...", headless)

            chrome_path = os.environ.get("CHROME_EXECUTABLE_PATH", None)
            self._browser = await nodriver.start(
                headless=True,  # Docker 必须 headless
                browser_executable_path=chrome_path,
                browser_args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-sandbox",              # Docker 必需
                    "--disable-dev-shm-usage",   # Docker 内存限制
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-setuid-sandbox",
                    "--single-process",
                ],
            )

            # 先导航到美团域名，然后设置 cookies
            page = await self._browser.get("https://qnh.meituan.com")

            # 加载 cookies
            cookies_dict = self._load_cookies_dict()
            for name, value in cookies_dict.items():
                await page.send(
                    nodriver.cdp.network.set_cookie(
                        name=str(name),
                        value=str(value),
                        domain=".meituan.com",
                        path="/",
                    )
                )
            logger.info("已加载 %d 个 cookies", len(cookies_dict))

            # 导航到 QNH 首页，等待 h5guard.js 初始化
            logger.info("导航到 QNH 首页，等待 h5guard.js 初始化...")
            self._page = await self._browser.get(f"{QNH_BASE}/home.html")
            await self._page.sleep(10)

            self._initialized = True
            logger.info("浏览器客户端初始化完成 ✓")

        except Exception as e:
            logger.error("浏览器启动失败: %s", e, exc_info=True)
            await self._cleanup()
            raise

    @staticmethod
    def _load_cookies_dict() -> dict[str, str]:
        """从配置文件或环境变量加载 cookies 字典。"""
        cookies_dict: dict[str, str] = {}

        # 优先从配置文件加载
        if COOKIE_CONFIG_FILE.exists():
            try:
                raw = json.loads(COOKIE_CONFIG_FILE.read_text())
                if isinstance(raw, list):
                    # nodriver format: [{name, value, ...}, ...]
                    cookies_dict = {
                        str(item["name"]): str(item["value"])
                        for item in raw
                        if "name" in item and "value" in item
                    }
                elif isinstance(raw, dict):
                    cookies_dict = raw
                logger.info("从 %s 加载了 %d 个 cookies", COOKIE_CONFIG_FILE, len(cookies_dict))
            except Exception as e:
                logger.warning("加载 cookie 配置文件失败: %s", e)

        # 其次从环境变量加载
        if not cookies_dict:
            env_val = os.environ.get("QNH_COOKIES_JSON", "").strip()
            if env_val:
                try:
                    cookies_dict = json.loads(env_val)
                    logger.info(
                        "从 QNH_COOKIES_JSON 环境变量加载了 %d 个 cookies", len(cookies_dict)
                    )
                except Exception as e:
                    logger.warning("解析 QNH_COOKIES_JSON 失败: %s", e)

        if not cookies_dict:
            raise RuntimeError(
                "没有可用的 QNH cookies，请配置 config/qnh_cookies.json 或 QNH_COOKIES_JSON 环境变量"
            )

        return cookies_dict

    async def execute_api(
        self,
        path: str,
        method: str = "POST",
        body: Any | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """在浏览器上下文中执行 API 调用，自动带上 mtgsig 签名。

        nodriver 的 evaluate 不支持 Promise，所以用 window 变量中转：
        1. 发起 fetch，结果存到 window.__api_result_N
        2. sleep 等待
        3. 读取 window.__api_result_N
        """
        await self.ensure_ready()

        _base = base_url or QNH_BASE
        url = f"{_base}{path}" if path.startswith("/") else path

        # 构建 fetch 参数，带上 csec 安全参数
        separator = "&" if "?" in url else "?"
        full_url = f"{url}{separator}yodaReady=h5&csecplatform=4&csecversion=4.2.0"

        body_json_escaped = json.dumps(json.dumps(body)) if body else "undefined"
        key = f"__api_result_{int(time.time() * 1000)}"

        js = f"""
            window.{key} = 'pending';
            fetch('{full_url}', {{
                method: '{method}',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: {body_json_escaped}
            }}).then(function(r) {{ return r.text(); }})
              .then(function(t) {{
                try {{ window.{key} = t; }}
                catch(e) {{ window.{key} = JSON.stringify({{_error: true, message: 'parse: ' + e.message}}); }}
              }})
              .catch(function(e) {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
        """

        try:
            await self._page.evaluate(js)
            await self._page.sleep(5)

            result_str = await self._page.evaluate(f"window.{key}")
            if result_str == "pending":
                await self._page.sleep(5)
                result_str = await self._page.evaluate(f"window.{key}")

            self._request_count += 1

            if not result_str or result_str == "pending":
                return {"_error": True, "message": "timeout"}

            result = json.loads(result_str)

            # 检查认证失败，尝试刷新后重试
            if isinstance(result, dict) and result.get("_error"):
                msg = result.get("message", "")
                if "401" in msg or "403" in msg:
                    logger.warning("API 认证失败，尝试刷新 cookies...")
                    await self._refresh()
                    return await self._execute_once(full_url, method, body_json_escaped)

            return result

        except Exception as e:
            logger.error("浏览器 API 调用异常: %s", e)
            raise

    async def _execute_once(
        self, full_url: str, method: str, body_json_escaped: str
    ) -> dict[str, Any]:
        """单次执行（重试用）。"""
        key = f"__api_result_{int(time.time() * 1000)}"

        js = f"""
            window.{key} = 'pending';
            fetch('{full_url}', {{
                method: '{method}',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'include',
                body: {body_json_escaped}
            }}).then(function(r) {{ return r.text(); }})
              .then(function(t) {{
                try {{ window.{key} = t; }}
                catch(e) {{ window.{key} = JSON.stringify({{_error: true, message: 'parse: ' + e.message}}); }}
              }})
              .catch(function(e) {{ window.{key} = JSON.stringify({{_error: true, message: e.message}}); }});
        """

        await self._page.evaluate(js)
        await self._page.sleep(5)

        result_str = await self._page.evaluate(f"window.{key}")
        if result_str == "pending":
            await self._page.sleep(5)
            result_str = await self._page.evaluate(f"window.{key}")

        self._request_count += 1

        if not result_str or result_str == "pending":
            return {"_error": True, "message": "timeout on retry"}

        return json.loads(result_str)

    async def get_golden_data(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """goldengateway 数据查询便捷方法。"""
        return await self.execute_api(path, method="POST", body=payload)

    async def _refresh(self) -> None:
        """刷新浏览器状态：重新加载 cookies 并导航到首页。"""
        import nodriver.cdp.network

        logger.info("刷新浏览器 cookies 和 h5guard 状态...")
        try:
            cookies_dict = self._load_cookies_dict()
            for name, value in cookies_dict.items():
                await self._page.send(
                    nodriver.cdp.network.set_cookie(
                        name=str(name),
                        value=str(value),
                        domain=".meituan.com",
                        path="/",
                    )
                )
            self._page = await self._browser.get(f"{QNH_BASE}/home.html")
            await self._page.sleep(8)
            logger.info("浏览器刷新完成 ✓")
        except Exception as e:
            logger.error("浏览器刷新失败: %s，尝试完全重启...", e)
            await self._cleanup()
            await self._start_browser()

    async def close(self) -> None:
        """关闭浏览器，释放资源。"""
        global _instance
        await self._cleanup()
        async with _instance_lock:
            _instance = None

    async def _cleanup(self) -> None:
        """清理浏览器资源。"""
        self._initialized = False
        self._page = None
        try:
            if self._browser:
                self._browser.stop()
        except Exception:
            pass
        self._browser = None

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "initialized": self._initialized,
            "request_count": self._request_count,
        }


class BrowserAPIError(Exception):
    """浏览器 API 调用错误。"""

    pass
