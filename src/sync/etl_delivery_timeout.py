from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SH_TZ = ZoneInfo("Asia/Shanghai")

_DELIVERY_TIMEOUT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS delivery_timeouts (
    id SERIAL PRIMARY KEY,
    order_id TEXT,
    create_time TIMESTAMPTZ,
    complete_time TIMESTAMPTZ,
    duration_min INT,
    timeout_type TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(order_id)
);
"""


def _normalize_payload(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if isinstance(payload, dict):
        return payload
    return None


def _extract_nested(data: Any, *paths: tuple[str, ...]) -> Any:
    if not isinstance(data, dict):
        return None
    for path in paths:
        cur: Any = data
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return None


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=SH_TZ)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except Exception:
            return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_time(int(text))

    normalized = text.replace("/", "-").replace("T", " ")
    normalized = normalized.rstrip("Z").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.replace(tzinfo=SH_TZ)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=SH_TZ)
    except Exception:
        return None


def _extract_order_id(payload: dict[str, Any]) -> str | None:
    order_id = _extract_nested(
        payload,
        ("order_id",),
        ("orderId",),
        ("id",),
        ("data", "order_id"),
        ("data", "orderId"),
        ("order", "order_id"),
        ("order", "orderId"),
    )
    if order_id is None:
        return None
    text = str(order_id).strip()
    return text or None


def _extract_create_complete(payload: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    create_raw = _extract_nested(
        payload,
        ("create_time",),
        ("createTime",),
        ("created_at",),
        ("createdAt",),
        ("order_time",),
        ("orderTime",),
        ("pay_time",),
        ("payTime",),
        ("data", "create_time"),
        ("data", "createTime"),
        ("data", "created_at"),
        ("order", "create_time"),
        ("order", "createTime"),
    )
    complete_raw = _extract_nested(
        payload,
        ("complete_time",),
        ("completeTime",),
        ("completed_at",),
        ("completedAt",),
        ("finish_time",),
        ("finishTime",),
        ("delivered_time",),
        ("deliveredTime",),
        ("delivery_time",),
        ("deliveryTime",),
        ("data", "complete_time"),
        ("data", "completeTime"),
        ("order", "complete_time"),
        ("order", "completeTime"),
    )
    return _parse_time(create_raw), _parse_time(complete_raw)


def _timeout_threshold(payload: dict[str, Any]) -> tuple[int, str]:
    mode = _extract_nested(
        payload,
        ("delivery_type",),
        ("deliveryType",),
        ("distribution_type",),
        ("delivery_mode",),
        ("data", "delivery_type"),
        ("order", "delivery_type"),
    )
    text = str(mode or "").lower()
    if any(tag in text for tag in ("即时", "immediate", "flash", "快送", "急送")):
        return 45, "instant_delivery_timeout"
    return 90, "normal_delivery_timeout"


async def run_delivery_timeout_etl(pool) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(_DELIVERY_TIMEOUT_TABLE_SQL)

            rows = await conn.fetch(
                """
                SELECT content
                FROM qnh_orders_raw
                WHERE content IS NOT NULL
                """
            )

            records: list[tuple[str, datetime, datetime, int, str]] = []
            for row in rows:
                payload = _normalize_payload(row["content"])
                if not payload:
                    continue

                order_id = _extract_order_id(payload)
                if not order_id:
                    continue

                create_time, complete_time = _extract_create_complete(payload)
                if not create_time or not complete_time:
                    continue
                if complete_time <= create_time:
                    continue

                duration_min = int((complete_time - create_time).total_seconds() // 60)
                threshold, timeout_type = _timeout_threshold(payload)
                if duration_min <= threshold:
                    continue

                records.append(
                    (
                        order_id,
                        create_time,
                        complete_time,
                        duration_min,
                        timeout_type,
                    )
                )

            if not records:
                logger.info("Delivery timeout ETL done: no timeout records found")
                return

            await conn.executemany(
                """
                INSERT INTO delivery_timeouts (
                    order_id,
                    create_time,
                    complete_time,
                    duration_min,
                    timeout_type,
                    detected_at
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (order_id) DO UPDATE SET
                    create_time = EXCLUDED.create_time,
                    complete_time = EXCLUDED.complete_time,
                    duration_min = EXCLUDED.duration_min,
                    timeout_type = EXCLUDED.timeout_type,
                    detected_at = NOW()
                """,
                records,
            )
            logger.info("Delivery timeout ETL done: upserted=%d", len(records))
    except Exception:
        logger.exception("Delivery timeout ETL failed")
