"""MeituanBrowserClient — 美团买药商家中心 nodriver 客户端。

策略：
  * Xvfb + 非 headless Chrome 绕过 h5guard 指纹检测
  * 注入 waimaie + yiyao cookies，让浏览器自动带 h5guard mtgsig 签名
  * 两种数据获取模式:
    - execute_api: 在页面上下文中发 XHR (h5guard 自动签名)
    - intercept_navigate: 导航到页面 + CDP 拦截网络响应
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://yiyao.meituan.com"
WAIMAIE_URL = "https://waimaie.meituan.com"
DEFAULT_COOKIE_FILE = (
    Path(__file__).resolve().parent.parent.parent / "config" / "waimaie_cookies.json"
)
YIYAO_COOKIE_FILE = (
    Path(__file__).resolve().parent.parent.parent / "config" / "yiyao_cookies.json"
)


class MeituanBrowserClient:
    """美团买药商家后台浏览器客户端（Xvfb + 非 headless）。"""

    def __init__(
        self,
        *,
        cookie_file: str | Path | None = None,
        cookie_json: str | dict[str, Any] | list[dict[str, Any]] | None = None,
        wm_poi_id: str | int | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.cookie_file = Path(cookie_file).expanduser() if cookie_file else DEFAULT_COOKIE_FILE
        self.cookie_json = cookie_json
        self.default_wm_poi_id = str(wm_poi_id) if wm_poi_id is not None else None
        self.base_url = base_url.rstrip("/")

        self._browser = None
        self._page = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._request_count = 0
        # CDP 拦截存储
        self._intercepted: dict[str, dict] = {}
        self._network_enabled = False

    async def ensure_ready(self) -> None:
        async with self._init_lock:
            if self._initialized and self._page:
                return
            await self._start_browser()

    async def execute_api(
        self,
        path: str,
        *,
        method: str = "POST",
        body_params: dict[str, Any] | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        content_type: str = "application/json",
    ) -> Any:
        """在浏览器上下文中发 XHR（h5guard 自动注入 mtgsig）。"""
        await self.ensure_ready()
        assert self._page is not None

        url = self._build_url(path, base_url)
        method_upper = method.upper()
        params = dict(body_params or {})
        if self.default_wm_poi_id and "wmPoiId" not in params:
            params["wmPoiId"] = self.default_wm_poi_id

        if content_type == "application/json":
            body_str = json.dumps(params)
        else:
            body_str = urlencode({k: "" if v is None else v for k, v in params.items()})

        result_key = f"__mt_api_{int(time.time() * 1000)}"
        body_escaped = json.dumps(body_str)

        js = f"""
            window.{result_key} = 'pending';
            (function() {{
                var xhr = new XMLHttpRequest();
                xhr.open('{method_upper}', '{url}', true);
                xhr.withCredentials = true;
                xhr.setRequestHeader('Content-Type', '{content_type}');
                xhr.onreadystatechange = function() {{
                    if (xhr.readyState === 4) {{
                        window.{result_key} = xhr.responseText || JSON.stringify({{error: true, message: 'empty', status: xhr.status}});
                    }}
                }};
                xhr.onerror = function() {{
                    window.{result_key} = JSON.stringify({{error: true, message: 'xhr error'}});
                }};
                xhr.send({body_escaped});
            }})();
        """

        await self._page.evaluate(js)

        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            result_str = await self._page.evaluate(f"window.{result_key}")
            if result_str and result_str != "pending":
                break
        else:
            raise RuntimeError(f"API 请求超时: {url}")

        self._request_count += 1

        try:
            return json.loads(result_str)
        except json.JSONDecodeError:
            logger.debug("非 JSON 响应: %s", result_str[:200])
            return result_str

    async def intercept_navigate(
        self,
        page_path: str,
        url_patterns: list[str],
        *,
        timeout: float = 30.0,
        wait_after_load: float = 5.0,
    ) -> list[dict[str, Any]]:
        """导航到页面，用 CDP 拦截匹配 url_patterns 的网络响应。

        Returns: list of {url, status, body} dicts
        """
        await self.ensure_ready()
        assert self._page is not None

        import nodriver.cdp.network as cdp_net

        captured: list[dict[str, Any]] = []
        pending_requests: dict[str, str] = {}  # request_id -> url

        async def on_request(event: cdp_net.RequestWillBeSent):
            url = event.request.url
            if any(pat in url for pat in url_patterns):
                pending_requests[str(event.request_id)] = url

        async def on_response(event: cdp_net.ResponseReceived):
            req_id = str(event.request_id)
            if req_id in pending_requests:
                pass  # wait for LoadingFinished

        async def on_finished(event: cdp_net.LoadingFinished):
            req_id = str(event.request_id)
            if req_id in pending_requests:
                url = pending_requests.pop(req_id)
                try:
                    body_result = await self._page.send(
                        cdp_net.get_response_body(event.request_id)
                    )
                    body_text = body_result[0] if body_result[0] else ""
                    captured.append({"url": url, "body": body_text})
                    logger.info("CDP 拦截: %s (%d bytes)", url[:80], len(body_text))
                except Exception as e:
                    logger.warning("CDP get_response_body 失败: %s %s", url[:60], e)

        # Enable network if not yet
        if not self._network_enabled:
            await self._page.send(cdp_net.enable())
            self._network_enabled = True

        self._page.add_handler(cdp_net.RequestWillBeSent, on_request)
        self._page.add_handler(cdp_net.ResponseReceived, on_response)
        self._page.add_handler(cdp_net.LoadingFinished, on_finished)

        # Navigate
        nav_url = self._build_url(page_path, None)
        logger.info("CDP 导航: %s (拦截 %s)", nav_url, url_patterns)
        self._page = await self._browser.get(nav_url)
        self._page.add_handler(cdp_net.RequestWillBeSent, on_request)
        self._page.add_handler(cdp_net.ResponseReceived, on_response)
        self._page.add_handler(cdp_net.LoadingFinished, on_finished)

        # Wait for page load + API responses
        await self._page.sleep(wait_after_load)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if captured:
                # Wait a bit more for additional responses
                await asyncio.sleep(3)
                break
            await asyncio.sleep(1)

        return captured

    async def click_and_intercept(
        self,
        js_click: str,
        url_patterns: list[str],
        *,
        timeout: float = 20.0,
        wait_after_click: float = 3.0,
    ) -> list[dict[str, Any]]:
        """在当前页面执行 JS 点击操作，同时用 CDP 拦截匹配的网络响应。

        用于翻页场景：第一页通过 intercept_navigate 获取，后续页通过此方法获取。

        Args:
            js_click: 触发翻页的 JavaScript 代码（如点击"下一页"按钮）
            url_patterns: 要拦截的 URL 子串列表
            timeout: 等待响应的超时时间
            wait_after_click: 点击后等待时间

        Returns: list of {url, body} dicts
        """
        await self.ensure_ready()
        assert self._page is not None

        import nodriver.cdp.network as cdp_net

        captured: list[dict[str, Any]] = []
        pending_requests: dict[str, str] = {}

        async def on_request(event: cdp_net.RequestWillBeSent):
            url = event.request.url
            if any(pat in url for pat in url_patterns):
                pending_requests[str(event.request_id)] = url

        async def on_response(event: cdp_net.ResponseReceived):
            pass

        async def on_finished(event: cdp_net.LoadingFinished):
            req_id = str(event.request_id)
            if req_id in pending_requests:
                url = pending_requests.pop(req_id)
                try:
                    body_result = await self._page.send(
                        cdp_net.get_response_body(event.request_id)
                    )
                    body_text = body_result[0] if body_result[0] else ""
                    captured.append({"url": url, "body": body_text})
                    logger.info("CDP 翻页拦截: %s (%d bytes)", url[:80], len(body_text))
                except Exception as e:
                    logger.warning("CDP get_response_body 失败: %s %s", url[:60], e)

        if not self._network_enabled:
            await self._page.send(cdp_net.enable())
            self._network_enabled = True

        self._page.add_handler(cdp_net.RequestWillBeSent, on_request)
        self._page.add_handler(cdp_net.ResponseReceived, on_response)
        self._page.add_handler(cdp_net.LoadingFinished, on_finished)

        # Execute the click JS
        logger.info("CDP 翻页点击: %s (拦截 %s)", js_click[:60], url_patterns)
        await self._page.evaluate(js_click)

        await asyncio.sleep(wait_after_click)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if captured:
                await asyncio.sleep(2)
                break
            await asyncio.sleep(1)

        return captured

    async def evaluate_js(self, js_code: str) -> Any:
        """在当前页面执行 JS 并返回结果。"""
        await self.ensure_ready()
        assert self._page is not None
        return await self._page.evaluate(js_code)

    async def navigate_to(self, path: str) -> None:
        """导航到指定页面。"""
        await self.ensure_ready()
        url = self._build_url(path, None)
        logger.info("导航到: %s", url)
        self._page = await self._browser.get(url)
        await self._page.sleep(8)
        for _ in range(15):
            ready_state = await self._page.evaluate("document.readyState")
            if ready_state == "complete":
                break
            await asyncio.sleep(1)
        current_url = self._page.url
        logger.info("导航完成: %s", current_url)

    async def close(self) -> None:
        await self._cleanup()

    # ── Internal ─────────────────────────────────────────────────────────

    async def _start_browser(self) -> None:
        try:
            import nodriver
            import nodriver.cdp.network as cdp_network

            chrome_path = os.environ.get("CHROME_EXECUTABLE_PATH", "/usr/bin/chromium")
            display = os.environ.get("DISPLAY", ":99")

            logger.info("启动 Chrome (DISPLAY=%s, chrome=%s)...", display, chrome_path)

            self._browser = await nodriver.start(
                headless=False,
                browser_executable_path=chrome_path,
                browser_args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    f"--display={display}",
                ],
            )

            # 先打开 waimaie 注入 cookie
            page = await self._browser.get(WAIMAIE_URL)
            await page.sleep(3)

            cookies_dict = self._load_cookies_dict()
            # 注入到所有相关域名
            domains = [
                ".meituan.com",
                "waimaie.meituan.com",
                ".waimaie.meituan.com",
                "yiyao.meituan.com",
                ".yiyao.meituan.com",
            ]
            injected = 0
            for name, value in cookies_dict.items():
                for domain in domains:
                    await page.send(
                        cdp_network.set_cookie(
                            name=str(name),
                            value=str(value),
                            domain=domain,
                            path="/",
                        )
                    )
                injected += 1
            logger.info("已注入 %d 个 cookies (x%d domains)", injected, len(domains))

            # 刷新让 cookie 生效
            self._page = await self._browser.get(f"{WAIMAIE_URL}/")
            await self._page.sleep(8)

            current_url = self._page.url
            logger.info("当前页面: %s", current_url)

            # yiyao 会重定向到 yiyao.meituan.com/main/frame — 这是成功
            if "login" in current_url and "epassport" in current_url:
                raise RuntimeError(f"登录态无效，页面跳转至: {current_url}")

            self._initialized = True
            logger.info("MeituanBrowserClient 初始化完成")

        except Exception:
            logger.exception("启动美团浏览器失败")
            await self._cleanup()
            raise

    def _load_cookies_dict(self) -> dict[str, str]:
        """合并 waimaie + yiyao cookies"""
        merged: dict[str, str] = {}

        # 1. 传入的 cookie_json（优先）
        if self.cookie_json:
            merged.update(self._normalize_cookie_blob(self.cookie_json))
            return merged

        # 2. 从文件加载
        for fpath in [self.cookie_file, YIYAO_COOKIE_FILE]:
            if fpath and Path(fpath).exists():
                try:
                    data = json.loads(Path(fpath).read_text())
                    merged.update(self._normalize_cookie_blob(data))
                    logger.info("从 %s 加载了 %d 个 cookies", fpath, len(data))
                except Exception as exc:
                    logger.warning("解析 %s 失败: %s", fpath, exc)

        if merged:
            return merged

        # 3. 环境变量
        env_val = os.environ.get("YIYAO_COOKIES_JSON", "").strip()
        if env_val:
            try:
                return self._normalize_cookie_blob(json.loads(env_val))
            except Exception as exc:
                logger.warning("解析 YIYAO_COOKIES_JSON 失败: %s", exc)

        raise RuntimeError("未找到美团 cookies，请配置 config/waimaie_cookies.json")

    @staticmethod
    def _normalize_cookie_blob(blob: Any) -> dict[str, str]:
        if isinstance(blob, dict):
            return {str(k): str(v) for k, v in blob.items()}
        if isinstance(blob, str):
            raw = json.loads(blob)
            return MeituanBrowserClient._normalize_cookie_blob(raw)
        if isinstance(blob, list):
            cookies: dict[str, str] = {}
            for item in blob:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    cookies[str(item["name"])] = str(item["value"])
            if cookies:
                return cookies
        raise ValueError("cookie 格式不支持")

    def _build_url(self, path: str, base_url: str | None) -> str:
        if path.startswith("http"):
            return path
        root = (base_url or self.base_url).rstrip("/")
        return urljoin(f"{root}/", path.lstrip("/"))

    async def _cleanup(self) -> None:
        self._initialized = False
        try:
            if self._browser:
                self._browser.stop()
        except Exception:
            pass
        self._browser = None
        self._page = None

    @property
    def stats(self) -> dict[str, Any]:
        return {"initialized": self._initialized, "request_count": self._request_count}
