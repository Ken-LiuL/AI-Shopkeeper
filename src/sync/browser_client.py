"""Playwright 浏览器客户端 — 通过浏览器执行需要 mtgsig 签名的 API。

为什么需要浏览器？
goldengateway 等核心 API 需要 mtgsig 签名（由 h5guard.js 在浏览器端生成），
纯 HTTP 请求无法携带该签名，服务端返回 403。
通过 Playwright 启动 Chromium，加载 QNH 页面让 h5guard.js 初始化后，
在浏览器上下文中用 fetch 发请求，浏览器会自动注入 mtgsig 签名。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    """Playwright 浏览器客户端，单例模式，多个 syncer 共用。

    通过浏览器上下文执行 fetch 请求，让 h5guard.js 自动注入 mtgsig 签名，
    绕过 goldengateway API 的 403 限制。
    """

    def __init__(self) -> None:
        self._browser = None
        self._context = None
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
            if self._initialized and self._page and not self._page.is_closed():
                return
            await self._start_browser()

    async def _start_browser(self) -> None:
        """启动浏览器。优先连接真实 Chrome（CDP），失败后 fallback 到 launch Chromium。

        为什么优先 CDP？
        美团 h5guard 能检测 Playwright 自带的 Chromium（即使 stealth 也拦），
        但连接真实 Chrome 实例可以完美绕过。
        """
        try:
            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            self._pw = pw
            self._stealth = None
            self._cdp_mode = False

            # 方案 1: 连接已运行的 Chrome（通过 CDP）
            cdp_url = os.environ.get("CHROME_CDP_URL", "")
            if cdp_url:
                try:
                    logger.info("尝试连接 Chrome CDP: %s", cdp_url)
                    self._browser = await pw.chromium.connect_over_cdp(cdp_url)
                    self._context = (
                        self._browser.contexts[0]
                        if self._browser.contexts
                        else await self._browser.new_context()
                    )
                    await self._load_cookies()
                    self._page = (
                        self._context.pages[0]
                        if self._context.pages
                        else await self._context.new_page()
                    )
                    self._cdp_mode = True
                    logger.info("✅ 已连接到真实 Chrome (CDP)")
                except Exception as e:
                    logger.warning("CDP 连接失败: %s，fallback 到启动 Chromium", e)
                    self._browser = None

            # 方案 2: 启动独立 Chrome（带 remote-debugging-port）
            if not self._browser:
                chrome_path = self._find_chrome()
                if chrome_path:
                    try:
                        logger.info("启动真实 Chrome: %s", chrome_path)
                        import subprocess

                        debug_port = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
                        self._chrome_proc = subprocess.Popen(
                            [
                                chrome_path,
                                f"--remote-debugging-port={debug_port}",
                                "--no-first-run",
                                "--no-default-browser-check",
                                "--user-data-dir=/tmp/qnh-chrome-profile",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        await asyncio.sleep(3)  # 等 Chrome 启动
                        self._browser = await pw.chromium.connect_over_cdp(
                            f"http://127.0.0.1:{debug_port}"
                        )
                        self._context = (
                            self._browser.contexts[0]
                            if self._browser.contexts
                            else await self._browser.new_context()
                        )
                        # CDP 模式也需要加载 cookies
                        await self._load_cookies()
                        self._page = await self._context.new_page()
                        self._cdp_mode = True
                        logger.info("✅ 已启动并连接真实 Chrome (port %d)", debug_port)
                    except Exception as e:
                        logger.warning(
                            "启动真实 Chrome 失败: %s，fallback 到 Playwright Chromium", e
                        )
                        self._browser = None

            # 方案 3: Fallback — Playwright 自带 Chromium（可能被 h5guard 拦截）
            if not self._browser:
                logger.info("启动 Playwright Chromium (fallback)...")
                headless = os.environ.get("HEADLESS", "true").lower() != "false"
                self._browser = await pw.chromium.launch(
                    headless=headless,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                )
                try:
                    from playwright_stealth import stealth_async

                    self._stealth = stealth_async
                except ImportError:
                    logger.warning("playwright-stealth 未安装，headless 可能被 h5guard 检测")

                self._context = await self._browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 720},
                )
                await self._load_cookies()
                self._page = await self._context.new_page()
                if self._stealth:
                    await self._stealth(self._page)

            # 导航到 QNH 首页，让 h5guard.js 初始化
            logger.info("导航到 QNH 首页，等待 h5guard.js 初始化...")
            await self._page.goto(
                f"{QNH_BASE}/home.html", wait_until="domcontentloaded", timeout=30000
            )

            # 等待 h5guard.js 完全加载
            await asyncio.sleep(8)

            self._initialized = True
            logger.info("浏览器客户端初始化完成 ✓")

        except Exception as e:
            logger.error("浏览器启动失败: %s", e, exc_info=True)
            await self._cleanup()
            raise

    @staticmethod
    def _find_chrome() -> str | None:
        """查找系统中的 Chrome 可执行文件。"""
        import platform

        candidates = []
        if platform.system() == "Darwin":
            candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        elif platform.system() == "Linux":
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium-browser",
            ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    async def _load_cookies(self) -> None:
        """从配置文件或环境变量加载 cookies 到浏览器上下文。"""
        cookies_dict: dict[str, str] = {}

        # 优先从配置文件加载
        if COOKIE_CONFIG_FILE.exists():
            try:
                cookies_dict = json.loads(COOKIE_CONFIG_FILE.read_text())
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

        # 转换为 Playwright cookie 格式
        playwright_cookies = []
        for name, value in cookies_dict.items():
            playwright_cookies.append(
                {
                    "name": str(name),
                    "value": str(value),
                    "domain": ".meituan.com",
                    "path": "/",
                }
            )

        await self._context.add_cookies(playwright_cookies)

    async def execute_api(
        self,
        path: str,
        method: str = "POST",
        body: Any | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """在浏览器上下文中执行 API 调用，自动带上 mtgsig 签名。

        通过 page.evaluate() 在浏览器中发 fetch 请求，
        h5guard.js 会自动拦截并注入 mtgsig 参数。
        """
        await self.ensure_ready()

        _base = base_url or QNH_BASE
        url = f"{_base}{path}" if path.startswith("/") else path

        # 构建 fetch 参数，带上 csec 安全参数
        separator = "&" if "?" in url else "?"
        full_url = f"{url}{separator}yodaReady=h5&csecplatform=4&csecversion=4.2.0"

        body_js = json.dumps(body) if body else "undefined"

        try:
            result = await self._page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch('{full_url}', {{
                            method: '{method}',
                            headers: {{'Content-Type': 'application/json'}},
                            credentials: 'include',
                            body: {body_js}
                        }});
                        if (!resp.ok) {{
                            return {{
                                _browser_error: true,
                                status: resp.status,
                                statusText: resp.statusText,
                                body: await resp.text()
                            }};
                        }}
                        return await resp.json();
                    }} catch (e) {{
                        return {{_browser_error: true, message: e.message}};
                    }}
                }}
            """)

            self._request_count += 1

            # 检查浏览器端错误
            if isinstance(result, dict) and result.get("_browser_error"):
                status = result.get("status", 0)
                if status in (401, 403):
                    logger.warning("浏览器请求认证失败 (HTTP %s)，尝试刷新...", status)
                    await self._refresh()
                    # 重试一次
                    return await self._execute_once(full_url, method, body_js)
                raise BrowserAPIError(f"浏览器请求失败: {result}")

            return result

        except Exception as e:
            if "browser_error" not in str(e):
                logger.error("浏览器 API 调用异常: %s", e)
            raise

    async def _execute_once(self, full_url: str, method: str, body_js: str) -> dict[str, Any]:
        """单次执行（重试用）。"""
        result = await self._page.evaluate(f"""
            async () => {{
                try {{
                    const resp = await fetch('{full_url}', {{
                        method: '{method}',
                        headers: {{'Content-Type': 'application/json'}},
                        credentials: 'include',
                        body: {body_js}
                    }});
                    return await resp.json();
                }} catch (e) {{
                    return {{_browser_error: true, message: e.message}};
                }}
            }}
        """)
        self._request_count += 1
        return result

    async def get_golden_data(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """goldengateway 数据查询便捷方法。"""
        return await self.execute_api(path, method="POST", body=payload)

    async def _refresh(self) -> None:
        """刷新浏览器状态：重新加载 cookies 并导航到首页。"""
        logger.info("刷新浏览器 cookies 和 h5guard 状态...")
        try:
            await self._load_cookies()
            await self._page.goto(
                f"{QNH_BASE}/home.html", wait_until="domcontentloaded", timeout=30000
            )
            await asyncio.sleep(5)
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
        # 关闭自己启动的 Chrome 进程
        if hasattr(self, "_chrome_proc") and self._chrome_proc:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc = None
            except Exception:
                pass
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_pw") and self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
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
