"""Tests for data sync engine — BaseSyncer, ProductSyncer, OrderSyncer, SyncScheduler."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.sync.base import CST, BaseSyncer, SyncMode, SyncResult
from src.sync.orders import OrderSyncer, _detect_channel, _parse_time
from src.sync.products import ProductSyncer, _json_or_none
from src.sync.scheduler import INTERVAL_MAP, SyncScheduler

# ── Helpers ──────────────────────────────────────────────────────────────────


class DummySyncer(BaseSyncer):
    """Concrete implementation for testing BaseSyncer."""

    name = "dummy"
    full_sync_interval = timedelta(hours=1)
    max_retries = 2
    retry_base_delay = 0.01  # fast retries for tests

    def __init__(self, client=None, db_pool=None):
        super().__init__(client, db_pool)
        self.full_sync_called = 0
        self.incremental_sync_called = 0
        self._full_sync_result = SyncResult(
            syncer_name="dummy", mode=SyncMode.FULL, success=True, records_synced=10
        )
        self._incr_sync_result = SyncResult(
            syncer_name="dummy", mode=SyncMode.INCREMENTAL, success=True, records_synced=5
        )

    async def full_sync(self) -> SyncResult:
        self.full_sync_called += 1
        return self._full_sync_result

    async def incremental_sync(self, since: datetime) -> SyncResult:
        self.incremental_sync_called += 1
        return self._incr_sync_result


def make_pool():
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    return pool


def make_client(tenant_id="T001"):
    client = AsyncMock()
    client.tenant_id = tenant_id
    client.post = AsyncMock(return_value={"data": {"list": [], "totalPage": 1}})
    return client


# ── SyncResult ───────────────────────────────────────────────────────────────


class TestSyncResult:
    def test_summary_success(self):
        r = SyncResult(
            syncer_name="test", mode=SyncMode.FULL, success=True, records_synced=42, duration_ms=123
        )
        assert "✅" in r.summary
        assert "42" in r.summary

    def test_summary_failure(self):
        r = SyncResult(syncer_name="test", mode=SyncMode.INCREMENTAL, success=False, error="boom")
        assert "❌" in r.summary


# ── BaseSyncer.sync() ────────────────────────────────────────────────────────


class TestBaseSyncerSync:
    @pytest.mark.asyncio
    async def test_first_run_triggers_full_sync(self):
        pool = make_pool()
        s = DummySyncer(client=make_client(), db_pool=pool)
        result = await s.sync()
        assert s.full_sync_called == 1
        assert result.success

    @pytest.mark.asyncio
    async def test_no_full_sync_recorded_triggers_full(self):
        pool = make_pool()
        pool.fetchrow = AsyncMock(
            return_value={"last_full_sync": None, "last_incremental_sync": None}
        )
        s = DummySyncer(client=make_client(), db_pool=pool)
        await s.sync()
        assert s.full_sync_called == 1

    @pytest.mark.asyncio
    async def test_stale_full_sync_triggers_full(self):
        pool = make_pool()
        old_time = datetime.now(CST) - timedelta(hours=2)
        pool.fetchrow = AsyncMock(
            return_value={"last_full_sync": old_time, "last_incremental_sync": old_time}
        )
        s = DummySyncer(client=make_client(), db_pool=pool)
        s.full_sync_interval = timedelta(hours=1)
        await s.sync()
        assert s.full_sync_called == 1

    @pytest.mark.asyncio
    async def test_recent_full_sync_triggers_incremental(self):
        pool = make_pool()
        recent = datetime.now(CST) - timedelta(minutes=10)
        pool.fetchrow = AsyncMock(
            return_value={"last_full_sync": recent, "last_incremental_sync": recent}
        )
        s = DummySyncer(client=make_client(), db_pool=pool)
        await s.sync()
        assert s.incremental_sync_called == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        pool = make_pool()
        s = DummySyncer(client=make_client(), db_pool=pool)
        s._full_sync_result = SyncResult(
            syncer_name="dummy", mode=SyncMode.FULL, success=False, error="fail"
        )
        result = await s.sync()
        assert s.full_sync_called == 2  # max_retries=2
        assert not result.success

    @pytest.mark.asyncio
    async def test_retry_on_exception(self):
        pool = make_pool()
        s = DummySyncer(client=make_client(), db_pool=pool)
        call_count = 0

        async def exploding_full():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        s.full_sync = exploding_full
        result = await s.sync()
        assert call_count == 2
        assert not result.success
        assert "RuntimeError" in result.error

    @pytest.mark.asyncio
    async def test_sync_with_none_pool(self):
        s = DummySyncer(client=make_client(), db_pool=None)
        await s.sync()
        assert s.full_sync_called == 1  # no pool → state=None → full sync


# ── ProductSyncer ────────────────────────────────────────────────────────────


class TestProductSyncer:
    @pytest.mark.asyncio
    async def test_full_sync_pagination(self):
        client = make_client()
        pool = make_pool()
        pages = [
            {"data": {"list": [{"spuId": "1", "name": "Product1"}], "totalPage": 2}},
            {"data": {"list": [{"spuId": "2", "name": "Product2"}], "totalPage": 2}},
        ]
        client.post = AsyncMock(side_effect=pages)
        s = ProductSyncer(client, pool)
        result = await s.full_sync()
        assert result.success
        assert result.records_synced == 2

    @pytest.mark.asyncio
    async def test_full_sync_empty(self):
        client = make_client()
        pool = make_pool()
        s = ProductSyncer(client, pool)
        result = await s.full_sync()
        assert result.success
        assert result.records_synced == 0

    @pytest.mark.asyncio
    async def test_full_sync_exception(self):
        client = make_client()
        client.post = AsyncMock(side_effect=RuntimeError("network"))
        pool = make_pool()
        s = ProductSyncer(client, pool)
        result = await s.full_sync()
        assert not result.success
        assert "network" in result.error

    @pytest.mark.asyncio
    async def test_incremental_sync(self):
        client = make_client()
        pool = make_pool()
        client.post = AsyncMock(return_value={"data": {"list": [{"spuId": "3"}], "totalPage": 1}})
        s = ProductSyncer(client, pool)
        since = datetime.now(CST) - timedelta(hours=1)
        result = await s.incremental_sync(since)
        assert result.success
        assert result.records_synced == 1

    @pytest.mark.asyncio
    async def test_upsert_no_pool(self):
        client = make_client()
        s = ProductSyncer(client, None)
        await s._upsert_products([{"spuId": "1"}])  # should not raise


class TestJsonOrNone:
    def test_dict(self):
        assert _json_or_none({"a": 1}) == '{"a": 1}'

    def test_list(self):
        assert _json_or_none([1, 2]) == "[1, 2]"

    def test_none(self):
        assert _json_or_none(None) is None

    def test_string(self):
        assert _json_or_none("hello") is None


# ── OrderSyncer ──────────────────────────────────────────────────────────────


class TestOrderSyncer:
    @pytest.mark.asyncio
    async def test_full_sync(self):
        client = make_client()
        pool = make_pool()
        client.post = AsyncMock(
            return_value={
                "data": {"list": [{"orderId": "O1", "platform": "meituan"}], "totalPage": 1}
            }
        )
        s = OrderSyncer(client, pool)
        result = await s.full_sync()
        assert result.success
        assert result.records_synced == 1

    @pytest.mark.asyncio
    async def test_incremental_sync(self):
        client = make_client()
        pool = make_pool()
        client.post = AsyncMock(return_value={"data": {"list": [], "totalPage": 1}})
        s = OrderSyncer(client, pool)
        result = await s.incremental_sync(datetime.now(CST) - timedelta(hours=1))
        assert result.success
        assert result.records_synced == 0

    @pytest.mark.asyncio
    async def test_upsert_no_pool(self):
        client = make_client()
        s = OrderSyncer(client, None)
        await s._upsert_orders([{"orderId": "O1"}])  # no-op


class TestDetectChannel:
    def test_meituan(self):
        assert _detect_channel({"platform": "meituan"}) == "meituan"
        assert _detect_channel({"channelName": "美团闪购"}) == "meituan"

    def test_eleme(self):
        assert _detect_channel({"platform": "eleme"}) == "eleme"
        assert _detect_channel({"channelName": "饿了么"}) == "eleme"

    def test_jddj(self):
        assert _detect_channel({"platform": "jddj"}) == "jddj"
        assert _detect_channel({"channelName": "京东到家"}) == "jddj"

    def test_unknown(self):
        assert _detect_channel({}) == "unknown"
        assert _detect_channel({"platform": "taobao"}) == "taobao"


class TestParseTime:
    def test_none(self):
        assert _parse_time(None) is None

    def test_datetime_passthrough(self):
        dt = datetime.now()
        assert _parse_time(dt) is dt

    def test_epoch_seconds(self):
        result = _parse_time(1700000000)
        assert isinstance(result, datetime)

    def test_epoch_millis(self):
        result = _parse_time(1700000000000)
        assert isinstance(result, datetime)

    def test_iso_string(self):
        result = _parse_time("2024-01-01T00:00:00")
        assert isinstance(result, datetime)

    def test_invalid_string(self):
        assert _parse_time("not-a-date") is None


# ── SyncScheduler ────────────────────────────────────────────────────────────


class TestSyncScheduler:
    def test_register(self):
        sched = SyncScheduler()
        syncer = DummySyncer()
        sched.register(syncer)
        assert "dummy" in sched.syncers

    @pytest.mark.asyncio
    async def test_run_once_no_syncers(self):
        sched = SyncScheduler()
        results = await sched.run_once()
        assert results == []

    @pytest.mark.asyncio
    async def test_run_once_due_interval(self):
        sched = SyncScheduler(schedule={"dummy": {"incremental": "every_15min"}})
        syncer = DummySyncer(client=make_client(), db_pool=None)
        sched.register(syncer)
        results = await sched.run_once()
        assert len(results) == 1
        assert results[0].success

    @pytest.mark.asyncio
    async def test_run_once_not_due(self):
        sched = SyncScheduler(schedule={"dummy": {"incremental": "every_4h"}})
        syncer = DummySyncer(client=make_client(), db_pool=None)
        sched.register(syncer)
        sched._last_run["dummy"] = datetime.now(CST)  # just ran
        results = await sched.run_once()
        assert results == []

    @pytest.mark.asyncio
    async def test_run_all_now(self):
        sched = SyncScheduler()
        syncer = DummySyncer(client=make_client(), db_pool=None)
        sched.register(syncer)
        results = await sched.run_all_now()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_stop(self):
        sched = SyncScheduler()
        sched._running = True
        await sched.stop()
        assert not sched._running

    def test_status(self):
        sched = SyncScheduler()
        syncer = DummySyncer()
        sched.register(syncer)
        status = sched.status
        assert "dummy" in status["syncers"]
        assert status["running"] is False

    def test_is_due_fixed_time_not_matching(self):
        sched = SyncScheduler()
        now = datetime.now(CST).replace(hour=12, minute=0)
        assert not sched._is_due("test", {"full": "06:00"}, now)

    @pytest.mark.asyncio
    async def test_run_once_exception_handled(self):
        sched = SyncScheduler(schedule={"dummy": {"incremental": "every_15min"}})
        syncer = DummySyncer(client=make_client(), db_pool=None)
        syncer.sync = AsyncMock(side_effect=RuntimeError("boom"))
        sched.register(syncer)
        results = await sched.run_once()
        assert len(results) == 1
        assert not results[0].success

    def test_interval_map_completeness(self):
        expected = [
            "every_15min",
            "every_30min",
            "every_1h",
            "every_2h",
            "every_4h",
            "every_6h",
            "every_12h",
        ]
        for k in expected:
            assert k in INTERVAL_MAP
