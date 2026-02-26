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
# 真实请求格式 (2026-02-24 Playwright 抓包验证):
# {
#   "viewCode": "homepage_hotsale_goods_rank_table_view_new",
#   "param": {
#     "poiIds": [1232550, 1221411, 1175006],
#     "channelIds": [],
#     "dateType": "d",       // d=日, w=周, m=月
#     "beginDate": "20260224",
#     "endDate": "20260224",
#     "page": 1,
#     "pageSize": 15,
#     "order": "",
#     "isSelectAllPoi": false
#   }
# }
#
# 已验证的 viewCode:
#   homepage_hotsale_goods_rank_table_view_new  — 热销商品排行
#   customer_consume_rank_table_view_new        — 消费排行
#   homepage_not_erp_poi_rank_table_view        — 门店排行
#   homepage_date_trend_list_new                — 趋势分析
#   homepage_trade_compare_table_view_new       — 行业对标 (仅周/月有数据)
#   homepage_data_overview_view_not_erp         — 数据概览 (complexModule)
#   homepage_channel_distribute_table_view_new  — 渠道分布 (channelDistributeList)
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

# 商品管理 API (qnh-gw3, 2026-02-27 抓包验证)
# ⚠️ qnh-gw3 路径需要 h5guard 签名，必须通过 browser_client 执行
API_SPU_PAGE = "/qnh-gw3/api/product/tenant/page-query"
API_SPU_DETAIL = "/qnh-gw3/api/product/tenant/detail"
API_STORE_SPU_PAGE = "/qnh-gw3/api/product/store/page-query-spu"
API_SKU_PAGE = "/qnh-gw3/api/product/tenant/page-query-sku"

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
    - goldengateway API 通过 Playwright 浏览器执行（需要 mtgsig 签名）
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
        # 浏览器客户端（lazy init），用于需要 mtgsig 签名的 goldengateway API
        self._browser_client = None

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
        # 注意：不关闭 browser_client，因为是单例，可能被其他 client 共用

    async def _get_browser(self):
        """获取浏览器客户端单例（lazy init）。"""
        if self._browser_client is None:
            from .browser_client import BrowserClient

            self._browser_client = await BrowserClient.get_instance()
        return self._browser_client

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
        view_code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        date_type: str = "d",
        page: int = 1,
        page_size: int = 15,
        extra_param: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """通用 goldengateway 表格查询 — 通过浏览器执行（需要 mtgsig 签名）。

        POST /goldengateway/empower/generic/table/query

        Args:
            view_code: 视图代码，如 homepage_hotsale_goods_rank_table_view_new
            start_date: 开始日期，格式 YYYYMMDD
            end_date: 结束日期，格式 YYYYMMDD
            date_type: 日期类型 d=日 w=周 m=月
            page: 页码
            page_size: 每页条数
            extra_param: 额外参数（合并到 param 对象中）
        """
        from datetime import date as _date

        today = _date.today().strftime("%Y%m%d")
        param: dict[str, Any] = {
            "poiIds": self.poi_ids,
            "channelIds": [],
            "dateType": date_type,
            "beginDate": start_date or today,
            "endDate": end_date or today,
            "page": page,
            "pageSize": page_size,
            "order": "",
            "isSelectAllPoi": False,
        }
        if extra_param:
            param.update(extra_param)
        payload = {"viewCode": view_code, "param": param}
        browser = await self._get_browser()
        return await browser.get_golden_data(GOLDEN_GENERIC_QUERY, payload)

    async def golden_complex_query(
        self,
        view_code: str = "homepage_data_overview_view_not_erp",
        start_date: str | None = None,
        end_date: str | None = None,
        date_type: str = "d",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """复杂模块查询 — 通过浏览器执行（需要 mtgsig 签名）。

        POST /goldengateway/empower/complexModule/queryTable
        """
        from datetime import date as _date

        today = _date.today().strftime("%Y%m%d")
        param: dict[str, Any] = {
            "poiIds": self.poi_ids,
            "channelIds": [],
            "dateType": date_type,
            "beginDate": start_date or today,
            "endDate": end_date or today,
        }
        param.update(kwargs)
        payload = {"viewCode": view_code, "param": param}
        browser = await self._get_browser()
        return await browser.get_golden_data(GOLDEN_COMPLEX_QUERY, payload)

    async def golden_channel_distribute(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        date_type: str = "d",
    ) -> dict[str, Any]:
        """渠道分布列表 — 通过浏览器执行（需要 mtgsig 签名）。

        POST /goldengateway/empower/homepage/channelDistributeList
        """
        from datetime import date as _date

        today = _date.today().strftime("%Y%m%d")
        payload = {
            "viewCode": "homepage_channel_distribute_table_view_new",
            "param": {
                "poiIds": self.poi_ids,
                "dateType": date_type,
                "beginDate": start_date or today,
                "endDate": end_date or today,
                "order": "",
                "pageSize": 100,
                "page": 1,
                "isSelectAllPoi": False,
            },
        }
        browser = await self._get_browser()
        return await browser.get_golden_data(GOLDEN_CHANNEL_DIST, payload)

    # ── neixin IM API ───────────────────────────────────────────────────

    async def neixin_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """GET request to neixin (api.neixin.cn)，403 时 fallback 到浏览器。"""
        try:
            return await self._request("GET", path, params=params, base_url=NEIXIN_BASE, **kwargs)
        except AuthExpiredError as e:
            if "403" in str(e):
                logger.info("neixin GET %s 返回 403，fallback 到浏览器执行", path)
                browser = await self._get_browser()
                return await browser.execute_api(path, method="GET", base_url=NEIXIN_BASE)
            raise

    async def neixin_post(
        self,
        path: str,
        data: Any | None = None,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST request to neixin (api.neixin.cn)，403 时 fallback 到浏览器。"""
        try:
            return await self._request(
                "POST", path, json_data=data, params=params, base_url=NEIXIN_BASE, **kwargs
            )
        except AuthExpiredError as e:
            if "403" in str(e):
                logger.info("neixin POST %s 返回 403，fallback 到浏览器执行", path)
                browser = await self._get_browser()
                return await browser.execute_api(
                    path, method="POST", body=data, base_url=NEIXIN_BASE
                )
            raise

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

    async def get_spu_page(
        self,
        page: int = 1,
        page_size: int = 20,
        category_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """获取 SPU 分页列表 — 通过浏览器执行（qnh-gw3 需要 h5guard 签名）。

        API: POST /qnh-gw3/api/product/tenant/page-query
        返回: {code, data: {list: [{tenantId, spuId, spuName, picUrlList, skus, brand, weightType, ...}], total, ...}}
        """
        payload: dict[str, Any] = {
            "page": page,
            "pageSize": page_size,
            "current": page,
        }
        if category_id:
            payload["categoryId"] = category_id
        if status:
            payload["status"] = status
        browser = await self._get_browser()
        return await browser.execute_api(API_SPU_PAGE, method="POST", body=payload)

    async def get_spu_detail(self, spu_id: str) -> dict[str, Any]:
        """获取 SPU 详情 — 通过浏览器执行（qnh-gw3 需要 h5guard 签名）。

        API: POST /qnh-gw3/api/product/tenant/detail
        """
        payload: dict[str, Any] = {"spuId": spu_id}
        browser = await self._get_browser()
        return await browser.execute_api(API_SPU_DETAIL, method="POST", body=payload)

    async def get_sku_page(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取 SKU 分页列表 — 通过浏览器执行（qnh-gw3 需要 h5guard 签名）。

        API: POST /qnh-gw3/api/product/tenant/page-query-sku
        """
        payload: dict[str, Any] = {"page": page, "pageSize": page_size, "current": page}
        browser = await self._get_browser()
        return await browser.execute_api(API_SKU_PAGE, method="POST", body=payload)

    async def get_poi_tree(self) -> dict[str, Any]:
        """Get store tree — 通过浏览器执行（goldengateway 需要 mtgsig）。

        API: POST /goldengateway/poi/queryPoiTree
        """
        browser = await self._get_browser()
        return await browser.get_golden_data(GOLDEN_POI_TREE, {"tenantId": self.tenant_id})

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
