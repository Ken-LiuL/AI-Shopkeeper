"""QNH HTTP Client — session management, API calls, rate limiting."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .qnh_auth import QNHAuth

logger = logging.getLogger(__name__)

QNH_BASE = "https://qnh.meituan.com"
NEIXIN_BASE = "https://api.neixin.cn"

# Default csec security params required by QNH APIs
CSEC_PARAMS = {
    "yodaReady": "h5",
    "csecplatform": "4",
    "csecversion": "4.2.0",
}

# Default tenant & store config
DEFAULT_TENANT_ID = "1011766"
DEFAULT_POI_IDS = [1175006, 1221411, 1232550]

# Rate limiting
MIN_REQUEST_INTERVAL = 0.5  # seconds between requests
MAX_CONCURRENT = 3

# ── goldengateway 通用查询接口 ──────────────────────────────────────
# POST /goldengateway/empower/generic/table/query
# 推断的请求格式 (需根据实际抓包验证):
# {
#   "tenantId": "1011766",
#   "poiIds": [1175006, 1221411, 1232550],
#   "module": "xxx",        // e.g. hotProduct, customerRank, storeDetail, orderDetail, ...
#   "dateRange": {"start": "2026-02-24", "end": "2026-02-24"},
#   "pageNum": 1,
#   "pageSize": 50
# }
GOLDEN_GENERIC_QUERY = "/goldengateway/empower/generic/table/query"
GOLDEN_COMPLEX_QUERY = "/goldengateway/empower/complexModule/queryTable"
GOLDEN_CHANNEL_DIST = "/goldengateway/empower/homepage/channelDistributeList"
GOLDEN_HOME_MODE = "/goldengateway/empower/homepage/getMode"
GOLDEN_POI_TREE = "/goldengateway/poi/queryPoiTree"

# 基础 API
API_AUTH = "/api/v1/sac/account/auth"
API_STORE_CATEGORY = "/api/v1/merchant/storeCategory/queryAll"
API_POI_AGG = "/api/v1/common/poi/queryByTypeThenAggByType"
API_TENANT_CHANNELS = "/api/v1/tenant/channels"
API_CHANNEL_BATCH = "/api/v1/tenant/channel/batchQuery"
API_TENANT_LEVEL = "/api/v1/tenant/aggTenantLevelConfig"
API_TENANT_MODULES = "/api/v1/tenant/modules"
API_POI_TASKS = "/api/v2/assistant/getPoiTasksWithTotal"

# IM API (api.neixin.cn)
NEIXIN_CHATLIST_APP = "/msg/api/chat/v3/chatlist/appid"
NEIXIN_PUB_CHATLIST = "/msg/api/pub/v1/chatlist"
NEIXIN_PUB_CHATLIST_INFO = "/msg/api/pub/v1/chatlist/info"
NEIXIN_CHAT_HISTORY = "/msg/api/pub/v3/history/chat/range"
NEIXIN_OFFLINE = "/msg/api/data/v1/offline"
NEIXIN_CHAT_INFO = "/msg/api/chat/v3/chatlist/info"
NEIXIN_READ_LIST = "/read/api/v2/list"


class QNHClient:
    """HTTP client for QNH (牵牛花) APIs.

    Features:
    - Automatic session/cookie management via QNHAuth
    - csec security parameter injection
    - Rate limiting (min interval + max concurrency)
    - Auto-retry on auth failures
    - JSON response parsing with error detection
    - Support for goldengateway data queries and neixin IM APIs
    """

    def __init__(
        self,
        auth: QNHAuth | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
        poi_ids: list[int] | None = None,
    ) -> None:
        self.auth = auth or QNHAuth()
        self.tenant_id = tenant_id
        self.poi_ids = poi_ids or DEFAULT_POI_IDS
        self._session: aiohttp.ClientSession | None = None
        self._last_request_time: float = 0
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._request_count = 0

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def __aenter__(self) -> QNHClient:
        await self._ensure_session()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            cookies = await self.auth.get_cookies()
            self._session = aiohttp.ClientSession(
                cookies=cookies,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Origin": QNH_BASE,
                    "Referer": f"{QNH_BASE}/home.html",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    # ── Public API ──────────────────────────────────────────────────────

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """GET request with auth, csec params, and rate limiting."""
        return await self._request("GET", path, params=params, **kwargs)

    async def post(
        self,
        path: str,
        data: Any | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST request with auth, csec params, and rate limiting."""
        return await self._request("POST", path, json_data=data, params=params, **kwargs)

    # ── goldengateway 数据查询 ──────────────────────────────────────────

    async def golden_query(
        self,
        module: str,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        page_size: int = 50,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """通用 goldengateway 表格查询。

        POST /goldengateway/empower/generic/table/query

        NOTE: 参数格式为推断，需根据实际抓包验证。
        module 可能的值: hotProduct, customerRank, storeDetail, orderDetail,
                        reviewDetail, stockDetail, financeDetail, promotionDetail 等。
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "poiIds": self.poi_ids,
            "module": module,
            "pageNum": page,
            "pageSize": page_size,
        }
        if start_date or end_date:
            payload["dateRange"] = {
                "start": start_date or end_date,
                "end": end_date or start_date,
            }
        if extra:
            payload.update(extra)
        return await self.post(GOLDEN_GENERIC_QUERY, data=payload)

    async def golden_complex_query(
        self,
        module: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """复杂模块查询。

        POST /goldengateway/empower/complexModule/queryTable
        NOTE: 参数格式为推断，需根据实际抓包验证。
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "poiIds": self.poi_ids,
            "module": module,
        }
        payload.update(kwargs)
        return await self.post(GOLDEN_COMPLEX_QUERY, data=payload)

    async def golden_channel_distribute(self) -> dict[str, Any]:
        """渠道分布列表。

        POST /goldengateway/empower/homepage/channelDistributeList
        NOTE: 参数格式为推断，需根据实际抓包验证。
        """
        payload = {
            "tenantId": self.tenant_id,
            "poiIds": self.poi_ids,
        }
        return await self.post(GOLDEN_CHANNEL_DIST, data=payload)

    # ── neixin IM API ───────────────────────────────────────────────────

    async def neixin_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """GET request to neixin (api.neixin.cn)."""
        return await self._request("GET", path, params=params, base_url=NEIXIN_BASE, **kwargs)

    async def neixin_post(
        self,
        path: str,
        data: Any | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST request to neixin (api.neixin.cn)."""
        return await self._request(
            "POST", path, json_data=data, params=params, base_url=NEIXIN_BASE, **kwargs
        )

    async def neixin_chat_history(
        self,
        chat_id: str,
        start_time: int,
        end_time: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """获取聊天历史（按时间范围）。

        POST api.neixin.cn/msg/api/pub/v3/history/chat/range
        NOTE: 参数格式为推断，需根据实际抓包验证。
        """
        payload = {
            "chatId": chat_id,
            "startTime": start_time,
            "endTime": end_time,
        }
        payload.update(kwargs)
        return await self.neixin_post(NEIXIN_CHAT_HISTORY, data=payload)

    async def neixin_chatlist(self, **kwargs: Any) -> dict[str, Any]:
        """获取公开会话列表。

        POST api.neixin.cn/msg/api/pub/v1/chatlist
        """
        return await self.neixin_post(NEIXIN_PUB_CHATLIST, data=kwargs)

    async def neixin_chatlist_info(self, chat_ids: list[str], **kwargs: Any) -> dict[str, Any]:
        """获取会话详情。

        POST api.neixin.cn/msg/api/pub/v1/chatlist/info
        """
        payload = {"chatIds": chat_ids}
        payload.update(kwargs)
        return await self.neixin_post(NEIXIN_PUB_CHATLIST_INFO, data=payload)

    # ── Convenience methods ─────────────────────────────────────────────

    async def get_tenant_channels(self) -> list[dict[str, Any]]:
        """Get all channels for current tenant."""
        return (await self.post(API_TENANT_CHANNELS)).get("data", [])

    async def get_poi_tasks(self) -> dict[str, Any]:
        """Get pending tasks for all POIs."""
        return await self.post(API_POI_TASKS, data=self.poi_ids)

    async def get_store_categories(self) -> list[dict[str, Any]]:
        """Get all product categories.

        API: POST /api/v1/merchant/storeCategory/queryAll
        """
        resp = await self.post(API_STORE_CATEGORY, data={"tenantId": self.tenant_id})
        return resp.get("data", [])

    async def get_poi_tree(self) -> dict[str, Any]:
        """Get store tree.

        API: POST /goldengateway/poi/queryPoiTree
        """
        return await self.post(GOLDEN_POI_TREE, data={"tenantId": self.tenant_id})

    # ── Internal ────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        retry_on_auth: bool = True,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Core request method with rate limiting and auth retry."""
        async with self._semaphore:
            # Rate limiting
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < MIN_REQUEST_INTERVAL:
                await asyncio.sleep(MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

            session = await self._ensure_session()

            # Inject csec params
            merged_params = {**CSEC_PARAMS, **(params or {})}

            _base = base_url or QNH_BASE
            url = f"{_base}{path}" if path.startswith("/") else path

            try:
                if method == "GET":
                    async with session.get(url, params=merged_params, **kwargs) as resp:
                        return await self._handle_response(resp)
                else:
                    async with session.post(
                        url, params=merged_params, json=json_data, **kwargs
                    ) as resp:
                        return await self._handle_response(resp)
            except AuthExpiredError:
                if retry_on_auth:
                    logger.info("Auth expired, refreshing session...")
                    await self.auth.invalidate()
                    await self.close()
                    return await self._request(
                        method,
                        path,
                        params=params,
                        json_data=json_data,
                        retry_on_auth=False,
                        base_url=base_url,
                        **kwargs,
                    )
                raise
            finally:
                self._request_count += 1

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> dict[str, Any]:
        """Parse response and detect errors."""
        if resp.status == 401 or resp.status == 403:
            raise AuthExpiredError(f"HTTP {resp.status}")

        if resp.status == 302:
            location = resp.headers.get("Location", "")
            if "epassport" in location or "login" in location:
                raise AuthExpiredError("Redirected to login")

        resp.raise_for_status()

        try:
            data = await resp.json()
        except Exception as exc:
            text = await resp.text()
            if "login" in text.lower() or "epassport" in text.lower():
                raise AuthExpiredError("Response contains login redirect") from exc
            raise QNHAPIError(f"Non-JSON response: {text[:200]}") from exc

        # QNH API error codes
        code = data.get("code")
        if code is not None and code != 0:
            msg = data.get("msg", data.get("message", "Unknown error"))
            if code in (401, 403, -1001):
                raise AuthExpiredError(f"API auth error {code}: {msg}")
            raise QNHAPIError(f"API error {code}: {msg}")

        return data

    @property
    def stats(self) -> dict[str, Any]:
        return {"total_requests": self._request_count}


class QNHAPIError(Exception):
    """QNH API returned an error."""

    pass


class AuthExpiredError(QNHAPIError):
    """Session/auth has expired, need re-login."""

    pass
