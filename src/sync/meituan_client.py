"""MeituanBrowserClient — 美团买药商家中心(yiyao.meituan.com) nodriver 客户端。

运行方式：
  * 使用 Xvfb 虚拟显示器 + 非 headless Chrome，绕过 h5guard 指纹检测
  * 读取 config/yiyao_cookies.json，注入登录态
  * 支持自动翻页抓取全量数据
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

logger = logging.getLogger(__name__)

BASE_URL = "https://yiyao.meituan.com"
DEFAULT_COOKIE_FILE = (
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
    ) -> Any:
        """在浏览器上下文中调用 yiyao API（带 h5guard 自动签名）。"""
        await self.ensure_ready()
        assert self._page is not None

        url = self._build_url(path, base_url)
        method_upper = method.upper()
        params = dict(body_params or {})
        if method_upper == "POST" and self.default_wm_poi_id and "wmPoiId" not in params:
            params["wmPoiId"] = self.default_wm_poi_id

        body_payload: str | None = None

        if method_upper == "POST":
            body_payload = urlencode({k: "" if v is None else v for k, v in params.items()})
        elif params:
            parsed = urlparse(url)
            qs = urlencode({k: "" if v is None else v for k, v in params.items()})
            url = urlunparse(
                parsed._replace(query=qs if not parsed.query else f"{parsed.query}&{qs}")
            )

        result_key = f"__mt_api_{int(time.time() * 1000)}"
        body_str_escaped = json.dumps(body_payload) if body_payload is not None else "null"

        # Use XMLHttpRequest instead of fetch — h5guard hooks XHR to inject mtgsig
        js = f"""
            window.{result_key} = 'pending';
            (function() {{
                var xhr = new XMLHttpRequest();
                xhr.open('{method_upper}', '{url}', true);
                xhr.withCredentials = true;
                xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
                xhr.onreadystatechange = function() {{
                    if (xhr.readyState === 4) {{
                        window.{result_key} = xhr.responseText || JSON.stringify({{error: true, message: 'empty response', status: xhr.status}});
                    }}
                }};
                xhr.onerror = function() {{
                    window.{result_key} = JSON.stringify({{error: true, message: 'xhr error'}});
                }};
                xhr.send({body_str_escaped});
            }})();
        """

        await self._page.evaluate(js)

        # 轮询等待结果
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

    async def navigate_to(self, path: str) -> None:
        """在当前 tab 导航到指定页面（不开新 tab，避免内存泄漏）。"""
        await self.ensure_ready()
        url = self._build_url(path, None)
        logger.info("导航到: %s", url)
        # 用 browser.get 而非 evaluate（确保完整页面加载 + h5guard 初始化）
        self._page = await self._browser.get(url)
        await self._page.sleep(8)
        # 等待页面加载完成
        for _ in range(15):
            ready_state = await self._page.evaluate("document.readyState")
            if ready_state == "complete":
                break
            await asyncio.sleep(1)
        current_url = self._page.url
        logger.info("导航完成: %s (h5guard ready)", current_url)

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

            # 非 headless 模式，配合 Xvfb 绕过指纹检测
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

            # 导航到美团主域，注入 cookies
            page = await self._browser.get(self.base_url)
            await page.sleep(3)

            cookies_dict = self._load_cookies_dict()
            # Inject cookies for both .meituan.com and yiyao.meituan.com domains
            domains = [".meituan.com", "yiyao.meituan.com", ".yiyao.meituan.com"]
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

            # 刷新页面让 cookies 生效，等待 h5guard.js 初始化
            self._page = await self._browser.get(f"{self.base_url}/")
            await self._page.sleep(8)

            current_url = self._page.url
            logger.info("当前页面: %s", current_url)

            if "error" in current_url or "login" in current_url:
                raise RuntimeError(f"登录态无效，页面跳转至: {current_url}")

            self._initialized = True
            logger.info("MeituanBrowserClient 初始化完成")

        except Exception:
            logger.exception("启动美团浏览器失败")
            await self._cleanup()
            raise

    def _load_cookies_dict(self) -> dict[str, str]:
        if self.cookie_json:
            return self._normalize_cookie_blob(self.cookie_json)

        if self.cookie_file and self.cookie_file.exists():
            try:
                data = json.loads(self.cookie_file.read_text())
                return self._normalize_cookie_blob(data)
            except Exception as exc:
                logger.warning("解析 %s 失败: %s", self.cookie_file, exc)

        env_val = os.environ.get("YIYAO_COOKIES_JSON", "").strip()
        if env_val:
            try:
                return self._normalize_cookie_blob(json.loads(env_val))
            except Exception as exc:
                logger.warning("解析 YIYAO_COOKIES_JSON 失败: %s", exc)

        raise RuntimeError("未找到美团 cookies，请配置 config/yiyao_cookies.json")

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
