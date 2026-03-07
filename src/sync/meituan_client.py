"""MeituanBrowserClient — 专为美团买药商家中心(yiyao.meituan.com)构建的 nodriver 客户端。

特点：
  * 在真实浏览器上下文中执行 API 调用，自动注入 mtgsig/h5guard 签名
  * 读取 config/yiyao_cookies.json 或自定义 cookie 文件/JSON，支持多门店
  * 兼容 nodriver.evaluate 的限制，使用 window.__api_result 中转获取响应
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
    """轻量浏览器客户端，每个门店(POI)可实例化各自的对象。"""

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
    ) -> Any:
        """在浏览器上下文中调用 yiyao API (支持 application/x-www-form-urlencoded)。"""

        await self.ensure_ready()
        assert self._page is not None

        url = self._build_url(path, base_url)
        method_upper = method.upper()
        params = dict(body_params or {})
        if method_upper == "POST" and self.default_wm_poi_id and "wmPoiId" not in params:
            params["wmPoiId"] = self.default_wm_poi_id

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        body_payload: str | None = None

        if method_upper == "POST":
            body_payload = urlencode({k: "" if v is None else v for k, v in params.items()})
        elif params:
            # GET/others: 将参数拼接到 URL
            parsed = urlparse(url)
            qs = urlencode({k: "" if v is None else v for k, v in params.items()})
            url = urlunparse(
                parsed._replace(query=qs if not parsed.query else f"{parsed.query}&{qs}")
            )

        result_key = f"__meituan_api_result_{int(time.time() * 1000)}"
        headers_literal = json.dumps(headers)
        body_literal = f", body: {json.dumps(body_payload)}" if body_payload is not None else ""

        js = f"""
            window.{result_key} = 'pending';
            fetch('{url}', {{
                method: '{method_upper}',
                credentials: 'include',
                headers: {headers_literal}{body_literal}
            }})
            .then(function(r) {{ return r.text(); }})
            .then(function(text) {{ window.{result_key} = text; }})
            .catch(function(err) {{ window.{result_key} = JSON.stringify({{"error": true, "message": err.message}}); }});
        """

        await self._page.evaluate(js)
        await asyncio.sleep(2)
        result_str = await self._page.evaluate(f"window.{result_key}")
        if result_str == "pending":
            await asyncio.sleep(2)
            result_str = await self._page.evaluate(f"window.{result_key}")

        self._request_count += 1
        if not result_str or result_str == "pending":
            raise RuntimeError("Browser request timed out")

        try:
            return json.loads(result_str)
        except json.JSONDecodeError:
            logger.debug("非 JSON 响应，返回原始字符串")
            return result_str

    async def close(self) -> None:
        await self._cleanup()

    # ── Internal helpers ─────────────────────────────────────

    async def _start_browser(self) -> None:
        try:
            import nodriver
            import nodriver.cdp.network as cdp_network

            headless = os.environ.get("HEADLESS", "false").lower() == "true"
            logger.info("启动 nodriver Chrome (headless=%s)...", headless)

            chrome_path = os.environ.get("CHROME_EXECUTABLE_PATH", None)
            self._browser = await nodriver.start(
                headless=True,  # Docker 必须 headless
                browser_executable_path=chrome_path,
                browser_args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-setuid-sandbox",
                    "--single-process",
                ],
            )

            page = await self._browser.get(self.base_url)
            cookies_dict = self._load_cookies_dict()
            for name, value in cookies_dict.items():
                await page.send(
                    cdp_network.set_cookie(
                        name=str(name),
                        value=str(value),
                        domain=".meituan.com",
                        path="/",
                    )
                )
            logger.info("载入 %d 个 cookies", len(cookies_dict))

            self._page = await self._browser.get(f"{self.base_url}/")
            await self._page.sleep(8)
            self._initialized = True
            logger.info("MeituanBrowserClient 初始化完成")
        except Exception:
            logger.exception("启动美团浏览器客户端失败")
            await self._cleanup()
            raise

    def _load_cookies_dict(self) -> dict[str, str]:
        if self.cookie_json:
            return self._normalize_cookie_blob(self.cookie_json)

        if self.cookie_file and self.cookie_file.exists():
            try:
                data = json.loads(self.cookie_file.read_text())
                return self._normalize_cookie_blob(data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("解析 %s 失败: %s", self.cookie_file, exc)

        env_val = os.environ.get("YIYAO_COOKIES_JSON", "").strip()
        if env_val:
            try:
                return self._normalize_cookie_blob(json.loads(env_val))
            except Exception as exc:  # noqa: BLE001
                logger.warning("解析 YIYAO_COOKIES_JSON 失败: %s", exc)

        raise RuntimeError("未找到美团买药 cookies，请提供 cookie_file 或 cookie_json")

    @staticmethod
    def _normalize_cookie_blob(blob: Any) -> dict[str, str]:
        if isinstance(blob, dict):
            return {str(k): str(v) for k, v in blob.items()}
        if isinstance(blob, str):
            try:
                raw = json.loads(blob)
                return MeituanBrowserClient._normalize_cookie_blob(raw)
            except json.JSONDecodeError as exc:  # noqa: BLE001
                raise ValueError(f"无法解析 cookie JSON: {exc}") from exc
        if isinstance(blob, list):
            cookies: dict[str, str] = {}
            for item in blob:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    cookies[str(item["name"])] = str(item["value"])
            if cookies:
                return cookies
        raise ValueError("cookie_json 必须是 dict/list/JSON 字符串")

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
        except Exception:  # noqa: BLE001
            pass
        self._browser = None
        self._page = None

    @property
    def stats(self) -> dict[str, Any]:
        return {"initialized": self._initialized, "request_count": self._request_count}
