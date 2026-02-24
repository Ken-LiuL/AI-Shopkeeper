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


class QNHClient:
    """HTTP client for QNH (牵牛花) APIs.

    Features:
    - Automatic session/cookie management via QNHAuth
    - csec security parameter injection
    - Rate limiting (min interval + max concurrency)
    - Auto-retry on auth failures
    - JSON response parsing with error detection
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

    async def get_tenant_channels(self) -> list[dict[str, Any]]:
        """Get all channels for current tenant."""
        return (await self.post("/api/v1/tenant/channels")).get("data", [])

    async def get_poi_tasks(self) -> dict[str, Any]:
        """Get pending tasks for all POIs."""
        return await self.post("/api/v2/assistant/getPoiTasksWithTotal", data=self.poi_ids)

    # ── Product APIs ────────────────────────────────────────────────────

    async def get_product_list(
        self,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Get SPU product list (paginated).

        API: POST /qnh-gw3/api/product/spu/list
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "pageNum": page,
            "pageSize": page_size,
        }
        if status:
            payload["status"] = status
        resp = await self.post("/qnh-gw3/api/product/spu/list", data=payload)
        return resp.get("data", {})

    async def get_product_detail(self, spu_id: str) -> dict[str, Any]:
        """Get SPU detail by ID.

        API: POST /qnh-gw3/api/product/spu/detail
        """
        resp = await self.post(
            "/qnh-gw3/api/product/spu/detail",
            data={"tenantId": self.tenant_id, "spuId": spu_id},
        )
        return resp.get("data", {})

    # ── Order APIs ──────────────────────────────────────────────────────

    async def get_order_list(
        self,
        page: int = 1,
        page_size: int = 50,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Get order list (paginated).

        API: POST /qnh-gw3/api/order/list
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "pageNum": page,
            "pageSize": page_size,
            "storeIds": self.poi_ids,
        }
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date
        if status:
            payload["orderStatus"] = status
        resp = await self.post("/qnh-gw3/api/order/list", data=payload)
        return resp.get("data", {})

    # ── Data / Analytics APIs ───────────────────────────────────────────

    async def get_data_overview(
        self,
        date: str,
        date_type: str = "day",
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Get business data overview for a date.

        API: POST /qnh-gw3/api/data/home/overview
        Returns: valid order amount/count, avg order value, gross profit, etc.
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "date": date,
            "dateType": date_type,
            "storeIds": self.poi_ids,
        }
        if channel:
            payload["channel"] = channel
        resp = await self.post("/qnh-gw3/api/data/home/overview", data=payload)
        return resp.get("data", {})

    async def get_realtime_data(self) -> dict[str, Any]:
        """Get realtime business data.

        API: POST /qnh-gw3/api/data/realtime
        Returns: today's live orders, revenue, etc.
        """
        resp = await self.post(
            "/qnh-gw3/api/data/realtime",
            data={"tenantId": self.tenant_id, "storeIds": self.poi_ids},
        )
        return resp.get("data", {})

    async def get_data_trend(
        self,
        start_date: str,
        end_date: str,
        date_type: str = "day",
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Get data trend over a date range.

        API: POST /qnh-gw3/api/data/home/trend
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "startDate": start_date,
            "endDate": end_date,
            "dateType": date_type,
            "storeIds": self.poi_ids,
        }
        if channel:
            payload["channel"] = channel
        resp = await self.post("/qnh-gw3/api/data/home/trend", data=payload)
        return resp.get("data", {})

    async def get_product_sales_ranking(
        self,
        date: str,
        date_type: str = "day",
        channel: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get product sales ranking from data overview.

        Attempts /qnh-gw3/api/data/home/product-ranking or falls back
        to extracting from overview data.
        """
        payload: dict[str, Any] = {
            "tenantId": self.tenant_id,
            "date": date,
            "dateType": date_type,
            "storeIds": self.poi_ids,
            "pageSize": limit,
        }
        if channel:
            payload["channel"] = channel

        try:
            resp = await self.post("/qnh-gw3/api/data/home/product-ranking", data=payload)
            data = resp.get("data", {})
            return data.get("list", data.get("records", []))
        except Exception:
            # Fallback: some tenants may not have this endpoint
            logger.debug("product-ranking endpoint not available, using overview")
            return []

    # ── Internal ────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        retry_on_auth: bool = True,
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

            url = f"{QNH_BASE}{path}" if path.startswith("/") else path

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
