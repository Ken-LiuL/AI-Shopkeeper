"""Tests for src/sync/utils.py — cookies, RateLimitedSession."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sync.utils import (
    RateLimitedSession,
    load_cookies_from_file,
    save_cookies_to_file,
)

# ── Cookie Tests ─────────────────────────────────────────────────────────────


class TestLoadCookies:
    def test_json_dict(self, tmp_path):
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps({"sid": "abc", "token": "xyz"}))
        result = load_cookies_from_file(f)
        assert result == {"sid": "abc", "token": "xyz"}

    def test_json_array(self, tmp_path):
        f = tmp_path / "cookies.json"
        data = [{"name": "sid", "value": "abc"}, {"name": "token", "value": "xyz"}]
        f.write_text(json.dumps(data))
        result = load_cookies_from_file(f)
        assert result == {"sid": "abc", "token": "xyz"}

    def test_netscape_format(self, tmp_path):
        f = tmp_path / "cookies.txt"
        f.write_text(
            "# Netscape cookies\n"
            ".example.com\tTRUE\t/\tFALSE\t0\tsid\tabc\n"
            ".example.com\tTRUE\t/\tFALSE\t0\ttoken\txyz\n"
        )
        result = load_cookies_from_file(f)
        assert result == {"sid": "abc", "token": "xyz"}

    def test_missing_file(self):
        result = load_cookies_from_file("/nonexistent/path")
        assert result == {}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "cookies.json"
        f.write_text("")
        result = load_cookies_from_file(f)
        assert result == {}


class TestSaveCookies:
    def test_save_and_permissions(self, tmp_path):
        f = tmp_path / "sub" / "cookies.json"
        save_cookies_to_file({"sid": "abc"}, f)
        assert f.exists()
        assert json.loads(f.read_text()) == {"sid": "abc"}
        assert oct(f.stat().st_mode & 0o777) == "0o600"


# ── RateLimitedSession Tests ────────────────────────────────────────────────


class TestRateLimitedSession:
    @pytest.mark.asyncio
    async def test_get_json(self):
        session = RateLimitedSession(min_interval=0, max_retries=1)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"ok": True})

        mock_session = AsyncMock()
        mock_session.request = AsyncMock(return_value=mock_resp)
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async with session as s:
                result = await s.get_json("http://example.com/api")
                assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_retry_on_500(self):
        session = RateLimitedSession(min_interval=0, max_retries=2, base_delay=0.01)

        resp_500 = AsyncMock()
        resp_500.status = 500
        resp_500.request_info = MagicMock()
        resp_500.history = ()

        resp_200 = AsyncMock()
        resp_200.status = 200

        mock_session = AsyncMock()
        mock_session.request = AsyncMock(side_effect=[resp_500, resp_200])
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async with session as s:
                result = await s.get("http://example.com")
                assert result.status == 200
                assert mock_session.request.call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        session = RateLimitedSession(min_interval=0, max_retries=2, base_delay=0.01)

        resp_500 = AsyncMock()
        resp_500.status = 500
        resp_500.request_info = MagicMock()
        resp_500.history = ()

        mock_session = AsyncMock()
        mock_session.request = AsyncMock(return_value=resp_500)
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async with session as s:
                with pytest.raises(Exception):
                    await s.get("http://example.com")

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        session = RateLimitedSession(min_interval=0.1, max_retries=1)

        resp = AsyncMock()
        resp.status = 200

        mock_session = AsyncMock()
        mock_session.request = AsyncMock(return_value=resp)
        mock_session.closed = False
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            async with session as s:
                t0 = time.monotonic()
                await s.get("http://example.com/1")
                await s.get("http://example.com/2")
                elapsed = time.monotonic() - t0
                # Second request should have waited ~0.1s
                assert elapsed >= 0.08  # allow small tolerance

    def test_stats(self):
        session = RateLimitedSession()
        assert session.stats == {"total_requests": 0}
