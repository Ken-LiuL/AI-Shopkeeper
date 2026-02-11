"""Sync utilities — cookie management, HTTP helpers, rate limiting."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


# ── Cookie Management ────────────────────────────────────────────────────────

def get_chrome_cookies_db_path(profile: str = "Default") -> Path:
    """Get the Chrome cookies database path for the current platform."""
    home = Path.home()
    system = os.uname().sysname

    if system == "Darwin":
        return home / "Library/Application Support/Google/Chrome" / profile / "Cookies"
    elif system == "Linux":
        return home / ".config/google-chrome" / profile / "Cookies"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def read_chrome_cookies(
    domain: str,
    profile: str = "Default",
    db_path: Optional[Path] = None,
) -> dict[str, str]:
    """Read cookies for a domain from Chrome's cookie database.

    NOTE: Chrome must be closed or the DB may be locked.
    On macOS, cookie values are encrypted — this returns encrypted blobs
    which won't work directly. Prefer CDP-based extraction instead.

    For development/testing, use load_cookies_from_file() with manually
    exported cookies.
    """
    path = db_path or get_chrome_cookies_db_path(profile)
    if not path.exists():
        logger.warning(f"Chrome cookies DB not found: {path}")
        return {}

    cookies = {}
    try:
        conn = sqlite3.connect(str(path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",),
        )
        for name, value, encrypted_value in cursor.fetchall():
            # On macOS, value is empty and encrypted_value has the real data
            # For now, only use plaintext values (works on Linux or older Chrome)
            if value:
                cookies[name] = value
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to read Chrome cookies: {e}")

    return cookies


def load_cookies_from_file(path: str | Path) -> dict[str, str]:
    """Load cookies from a JSON file.

    Expected format: {"cookie_name": "cookie_value", ...}
    Or Netscape format lines: domain\\tTRUE\\t/\\tFALSE\\t0\\tname\\tvalue
    """
    path = Path(path)
    if not path.exists():
        return {}

    text = path.read_text().strip()

    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        # Array of {name, value} objects (browser export format)
        if isinstance(data, list):
            return {
                item["name"]: item["value"]
                for item in data
                if "name" in item and "value" in item
            }
    except (json.JSONDecodeError, KeyError):
        pass

    # Try Netscape cookie format
    cookies = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]

    return cookies


def save_cookies_to_file(cookies: dict[str, str], path: str | Path) -> None:
    """Save cookies to a JSON file with restricted permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cookies, indent=2))
    path.chmod(0o600)


# ── HTTP Request Helpers ─────────────────────────────────────────────────────

class RateLimitedSession:
    """aiohttp session wrapper with retry and rate limiting.

    Features:
    - Configurable min interval between requests
    - Max concurrent requests via semaphore
    - Exponential backoff retry on transient errors
    - Automatic JSON response parsing
    """

    def __init__(
        self,
        min_interval: float = 0.5,
        max_concurrent: int = 3,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: int = 30,
        headers: Optional[dict[str, str]] = None,
    ):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self.default_headers = headers or {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request: float = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_count = 0

    async def __aenter__(self) -> "RateLimitedSession":
        self._session = aiohttp.ClientSession(
            headers=self.default_headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _wait_rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    async def get(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        return await self._request("POST", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("GET", url, **kwargs)
        return await resp.json()

    async def post_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("POST", url, **kwargs)
        return await resp.json()

    async def _request(self, method: str, url: str, **kwargs: Any) -> aiohttp.ClientResponse:
        """Execute request with rate limiting and retry."""
        assert self._session is not None, "Session not initialized. Use 'async with'."

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            async with self._semaphore:
                await self._wait_rate_limit()
                try:
                    resp = await self._session.request(method, url, **kwargs)
                    self._request_count += 1

                    if resp.status < 500:
                        return resp

                    # Server error — retry
                    last_exc = aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=resp.status
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_exc = e

            if attempt < self.max_retries:
                delay = self.base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Request {method} {url} attempt {attempt} failed: {last_exc}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)

        raise last_exc or RuntimeError(f"Request failed after {self.max_retries} attempts")

    @property
    def stats(self) -> dict[str, int]:
        return {"total_requests": self._request_count}
