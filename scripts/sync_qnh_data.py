#!/usr/bin/env python3
"""本地 QNH 数据同步脚本。

功能：
1. 直接使用 QNH cookie 调用可访问的基础 API（分类、渠道、模块）。
2. 通过 nodriver 浏览器客户端调用 goldengateway API（热销、趋势、门店排行、消费排行、渠道分布）。
3. 将结果写入本地 SQLite（data/qnh_sync.db）并可选同步到远程 PostgreSQL（DATABASE_URL）。
4. 支持 --dry-run 仅抓取不落库，幂等 upsert。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path
from typing import Any

import asyncpg

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.sync.browser_client import BrowserClient
from src.sync.qnh_client import (
    API_STORE_CATEGORY,
    API_TENANT_CHANNELS,
    API_TENANT_MODULES,
    QNHClient,
)

DEFAULT_TENANT_ID = "1011766"
DEFAULT_POI_IDS = [1175006, 1221411, 1232550]
DEFAULT_SQLITE_PATH = ROOT_DIR / "data" / "qnh_sync.db"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS qnh_dataset_records (
    dataset TEXT NOT NULL,
    record_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (dataset, record_key)
);
CREATE INDEX IF NOT EXISTS idx_qnh_dataset_records_dataset
    ON qnh_dataset_records(dataset);
"""

PG_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS qnh_dataset_records (
        dataset TEXT NOT NULL,
        record_key TEXT NOT NULL,
        payload JSONB NOT NULL,
        content_hash TEXT NOT NULL,
        synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (dataset, record_key)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_qnh_dataset_records_dataset
        ON qnh_dataset_records(dataset);
    """,
]

DATASET_KEY_FIELDS: dict[str, Sequence[str]] = {
    "store_categories": ("categoryId", "id"),
    "tenant_channels": ("channelId", "id", "channelCode"),
    "tenant_modules": ("moduleCode", "moduleId", "id"),
    "hotsale_goods": ("goodsSpuId", "spuId", "goodsId", "skuId"),
    "sales_trend": ("date", "bizDate", "period"),
    "store_rank": ("poiId", "poiCode", "storeId"),
    "customer_rank": ("customerId", "userId", "wmUserId"),
    "channel_distribute": ("channelId", "channel", "channelName"),
}

GENERIC_KEY_FIELDS = (
    "id",
    "ID",
    "code",
    "Code",
    "name",
    "date",
    "bizDate",
    "poiId",
    "spuId",
    "skuId",
    "goodsId",
    "channelId",
    "rank",
)

logger = logging.getLogger("sync_qnh_data")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("python scripts/sync_qnh_data.py", description=__doc__)
    parser.add_argument(
        "--tenant-id", default=DEFAULT_TENANT_ID, help="Tenant ID (default: 1011766)"
    )
    parser.add_argument(
        "--poi-ids",
        help="Comma separated poiIds (default: 1175006,1221411,1232550)",
    )
    parser.add_argument(
        "--start-date",
        help="开始日期 YYYY-MM-DD 或 YYYYMMDD，默认今天",
    )
    parser.add_argument(
        "--end-date",
        help="结束日期 YYYY-MM-DD 或 YYYYMMDD，默认与开始日期相同",
    )
    parser.add_argument(
        "--date-type",
        choices=("d", "w", "m"),
        default="d",
        help="日期粒度：d=日 w=周 m=月 (默认 d)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="goldengateway 查询每页条数 (默认 100)",
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help="SQLite 文件路径 (默认 data/qnh_sync.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="远程 PostgreSQL DATABASE_URL（可选）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅抓取不写库",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="日志等级 (默认 INFO)",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="跳过需要浏览器的 goldengateway API（仅同步基础 API）",
    )
    return parser.parse_args()


def normalize_date(value: str | None, default: datetime) -> str:
    """Convert CLI date into YYYYMMDD."""
    if not value:
        return default.strftime("%Y%m%d")
    val = value.strip()
    fmt = "%Y%m%d" if len(val) == 8 and val.isdigit() else "%Y-%m-%d"
    dt = datetime.strptime(val, fmt)
    return dt.strftime("%Y%m%d")


def chunked(seq: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def as_list(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


def extract_direct_records(resp: dict[str, Any]) -> list[dict[str, Any]]:
    data = resp.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "dataList", "records", "rows", "modules"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        return [data]
    return []


def extract_table_records(resp: dict[str, Any], page_size: int) -> tuple[list[dict[str, Any]], int]:
    data = resp.get("data", {})
    if isinstance(data, list):
        return data, 1
    if not isinstance(data, dict):
        return [], 0

    for key in ("dataList", "valueList", "list", "records", "rows"):
        val = data.get(key)
        if isinstance(val, list):
            total_pages = _infer_total_pages(data, len(val), page_size)
            return val, total_pages
    return [], _infer_total_pages(data, 0, page_size)


def _infer_total_pages(meta: dict[str, Any], current_count: int, page_size: int) -> int:
    for key in ("totalPage", "totalPages", "pages"):
        value = meta.get(key)
        if isinstance(value, int) and value > 0:
            return value
    total = meta.get("total", meta.get("totalCount"))
    if isinstance(total, int) and total > 0 and page_size > 0:
        return max(1, math.ceil(total / page_size))
    if page_size > 0 and current_count < page_size:
        return 1
    return 0


def normalize_record(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    return {"value": record}


def extract_field(record: dict[str, Any], field_name: str) -> Any:
    if not field_name:
        return None
    parts = field_name.split(".")
    current: Any = record
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def make_record_key(dataset: str, record: dict[str, Any], payload: str) -> str:
    for field in DATASET_KEY_FIELDS.get(dataset, ()):
        value = extract_field(record, field)
        if value not in (None, ""):
            return str(value)
    for field in GENERIC_KEY_FIELDS:
        value = record.get(field)
        if value not in (None, ""):
            return str(value)
    return sha1(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class PreparedRecord:
    dataset: str
    key: str
    payload: str
    content_hash: str
    synced_at: datetime


class StorageManager:
    def __init__(self, sqlite_path: Path, database_url: str, dry_run: bool) -> None:
        self.sqlite_path = sqlite_path
        self.database_url = database_url
        self.dry_run = dry_run
        self._sqlite_conn: sqlite3.Connection | None = None
        self._pg_pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> StorageManager:
        await self._init()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _init(self) -> None:
        if self.dry_run:
            logger.info("Dry-run：跳过数据库初始化")
            return

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_conn = sqlite3.connect(self.sqlite_path)
        self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
        self._sqlite_conn.execute("PRAGMA foreign_keys=ON;")
        self._sqlite_conn.executescript(SQLITE_SCHEMA)
        logger.info("SQLite 初始化完成：%s", self.sqlite_path)

        if self.database_url:
            self._pg_pool = await asyncpg.create_pool(
                dsn=self.database_url,
                min_size=1,
                max_size=4,
                command_timeout=30,
            )
            async with self._pg_pool.acquire() as conn:
                for stmt in PG_SCHEMA_STATEMENTS:
                    await conn.execute(stmt)
            logger.info("PostgreSQL 初始化完成")
        else:
            logger.info("未配置 DATABASE_URL，跳过远程 PG")

    async def close(self) -> None:
        if self._sqlite_conn:
            self._sqlite_conn.close()
            self._sqlite_conn = None
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None

    async def persist(
        self, dataset: str, records: list[dict[str, Any]], synced_at: datetime
    ) -> int:
        if not records:
            return 0

        normalized: dict[str, PreparedRecord] = {}
        for record in records:
            normalized_record = normalize_record(record)
            payload = json.dumps(normalized_record, ensure_ascii=False, sort_keys=True, default=str)
            content_hash = sha1(payload.encode("utf-8")).hexdigest()
            record_key = make_record_key(dataset, normalized_record, payload)
            normalized[record_key] = PreparedRecord(
                dataset=dataset,
                key=record_key,
                payload=payload,
                content_hash=content_hash,
                synced_at=synced_at,
            )

        prepared = list(normalized.values())
        if self.dry_run:
            logger.info("Dry-run：跳过写入 %s (%d 条)", dataset, len(prepared))
            return len(prepared)

        self._write_sqlite(prepared)
        await self._write_postgres(prepared)
        return len(prepared)

    def _write_sqlite(self, rows: list[PreparedRecord]) -> None:
        if not self._sqlite_conn or not rows:
            return
        sql = """
            INSERT INTO qnh_dataset_records (dataset, record_key, payload, content_hash, synced_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dataset, record_key) DO UPDATE SET
                payload = excluded.payload,
                content_hash = excluded.content_hash,
                synced_at = excluded.synced_at
            WHERE qnh_dataset_records.content_hash <> excluded.content_hash;
        """
        data = [
            (row.dataset, row.key, row.payload, row.content_hash, row.synced_at.isoformat())
            for row in rows
        ]
        self._sqlite_conn.executemany(sql, data)
        self._sqlite_conn.commit()

    async def _write_postgres(self, rows: list[PreparedRecord]) -> None:
        if not self._pg_pool or not rows:
            return
        sql = """
            INSERT INTO qnh_dataset_records (dataset, record_key, payload, content_hash, synced_at)
            VALUES ($1, $2, $3::jsonb, $4, $5::timestamptz)
            ON CONFLICT (dataset, record_key) DO UPDATE SET
                payload = EXCLUDED.payload,
                content_hash = EXCLUDED.content_hash,
                synced_at = EXCLUDED.synced_at
            WHERE qnh_dataset_records.content_hash <> EXCLUDED.content_hash;
        """
        for chunk in chunked(rows, 500):
            await self._pg_pool.executemany(
                sql,
                [
                    (row.dataset, row.key, row.payload, row.content_hash, row.synced_at)
                    for row in chunk
                ],
            )


class QNHDataSync:
    def __init__(
        self,
        tenant_id: str,
        poi_ids: list[int],
        start_date: str,
        end_date: str,
        date_type: str,
        page_size: int,
        storage: StorageManager,
        skip_browser: bool = False,
    ) -> None:
        self.tenant_id = tenant_id
        self.poi_ids = poi_ids
        self.start_date = start_date
        self.end_date = end_date
        self.date_type = date_type
        self.page_size = page_size
        self.storage = storage
        self.skip_browser = skip_browser
        self.synced_at = datetime.now(UTC)
        self.browser_used = False
        self.summary: dict[str, int] = {}
        self.errors: dict[str, str] = {}

    async def run(self) -> int:
        logger.info(
            "开始同步：tenant=%s poiIds=%s 日期=%s→%s 粒度=%s dry-run=%s",
            self.tenant_id,
            ",".join(map(str, self.poi_ids)),
            self.start_date,
            self.end_date,
            self.date_type,
            self.storage.dry_run,
        )
        async with QNHClient(tenant_id=self.tenant_id, poi_ids=self.poi_ids) as client:
            await self._fetch_basic_datasets(client)
            if not self.skip_browser:
                await self._fetch_golden_datasets(client)
            else:
                logger.info("⏭️  跳过 goldengateway（--skip-browser）")

        if self.browser_used:
            browser = await BrowserClient.get_instance()
            await browser.close()

        self._log_summary()
        return 1 if self.errors else 0

    async def _fetch_basic_datasets(self, client: QNHClient) -> None:
        await self._run_fetch(
            dataset="store_categories",
            fetcher=lambda: client.get(API_STORE_CATEGORY),
            extractor=extract_direct_records,
        )
        await self._run_fetch(
            dataset="tenant_channels",
            fetcher=lambda: client.get(API_TENANT_CHANNELS),
            extractor=extract_direct_records,
        )
        await self._run_fetch(
            dataset="tenant_modules",
            fetcher=lambda: client.get(API_TENANT_MODULES),
            extractor=extract_direct_records,
        )

    async def _fetch_golden_datasets(self, client: QNHClient) -> None:
        self.browser_used = True
        await self._run_fetch(
            dataset="hotsale_goods",
            fetcher=lambda: self._fetch_golden_table(
                client, "homepage_hotsale_goods_rank_table_view_new"
            ),
        )
        await self._run_fetch(
            dataset="sales_trend",
            fetcher=lambda: self._fetch_golden_table(
                client,
                "homepage_date_trend_list_new",
                extra_param={"dateType": self.date_type},
            ),
        )
        await self._run_fetch(
            dataset="store_rank",
            fetcher=lambda: self._fetch_golden_table(
                client, "homepage_not_erp_poi_rank_table_view"
            ),
        )
        await self._run_fetch(
            dataset="customer_rank",
            fetcher=lambda: self._fetch_golden_table(
                client, "customer_consume_rank_table_view_new"
            ),
        )
        await self._run_fetch(
            dataset="channel_distribute",
            fetcher=lambda: self._fetch_channel_distribute(client),
        )

    async def _fetch_golden_table(
        self,
        client: QNHClient,
        view_code: str,
        extra_param: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        page = 1
        records: list[dict[str, Any]] = []

        while True:
            resp = await client.golden_query(
                view_code=view_code,
                start_date=self.start_date,
                end_date=self.end_date,
                date_type=self.date_type,
                page=page,
                page_size=self.page_size,
                extra_param=extra_param,
            )
            if resp.get("_error"):
                raise RuntimeError(f"{view_code} error: {resp['_error']}")
            code = resp.get("code")
            if code not in (None, 0):
                raise RuntimeError(f"{view_code} code {code}: {resp.get('msg')}")

            page_records, total_pages = extract_table_records(resp, self.page_size)
            records.extend(page_records)

            if not page_records or total_pages <= page or len(page_records) < self.page_size:
                break
            page += 1

        logger.debug("%s 返回 %d 条 (view=%s)", view_code, len(records), view_code)
        return records

    async def _fetch_channel_distribute(self, client: QNHClient) -> list[dict[str, Any]]:
        resp = await client.golden_channel_distribute(
            start_date=self.start_date,
            end_date=self.end_date,
            date_type=self.date_type,
        )
        if resp.get("_error"):
            raise RuntimeError(f"channel distribute error: {resp['_error']}")
        code = resp.get("code")
        if code not in (None, 0):
            raise RuntimeError(f"channel distribute code {code}: {resp.get('msg')}")
        records, _ = extract_table_records(resp, self.page_size)
        return records

    async def _run_fetch(
        self,
        dataset: str,
        fetcher,
        extractor: Any | None = None,
    ) -> None:
        try:
            raw = await fetcher()
            if extractor:
                records = extractor(raw)
            else:
                records = (
                    raw if isinstance(raw, list) else extract_table_records(raw, self.page_size)[0]
                )
            count = await self.storage.persist(dataset, records, self.synced_at)
            self.summary[dataset] = len(records)
            logger.info("✅ %s 获取 %d 条，写入 %d 条", dataset, len(records), count)
        except Exception as exc:
            self.errors[dataset] = str(exc)
            logger.error("❌ %s 抓取失败：%s", dataset, exc)

    def _log_summary(self) -> None:
        logger.info("同步完成：%d 成功，%d 失败", len(self.summary), len(self.errors))
        for dataset, total in sorted(self.summary.items()):
            logger.info("  - %s: %d 条", dataset, total)
        if self.errors:
            for dataset, reason in self.errors.items():
                logger.error("  - %s 失败：%s", dataset, reason)


async def async_main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    today = datetime.now().astimezone()
    start_date = normalize_date(args.start_date, today)
    end_date = normalize_date(
        args.end_date,
        today
        if not args.end_date
        else datetime.strptime(args.end_date, "%Y-%m-%d")
        if "-" in args.end_date
        else datetime.strptime(args.end_date, "%Y%m%d"),
    )
    if end_date < start_date:
        raise ValueError("end_date 不能早于 start_date")

    poi_ids = DEFAULT_POI_IDS
    if args.poi_ids:
        poi_ids = [int(pid.strip()) for pid in args.poi_ids.split(",") if pid.strip()]
        if not poi_ids:
            raise ValueError("poiIds 解析失败")

    async with StorageManager(Path(args.sqlite_path), args.database_url, args.dry_run) as storage:
        syncer = QNHDataSync(
            tenant_id=str(args.tenant_id),
            poi_ids=poi_ids,
            start_date=start_date,
            end_date=end_date,
            date_type=args.date_type,
            page_size=args.page_size,
            storage=storage,
            skip_browser=args.skip_browser,
        )
        return await syncer.run()


def main() -> None:
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.warning("收到中断信号，退出")
        exit_code = 1
    except Exception as exc:
        logger.exception("同步失败：%s", exc)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
