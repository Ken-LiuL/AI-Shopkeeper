from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SH_TZ = ZoneInfo("Asia/Shanghai")
KEYWORDS = ["处罚", "扣分", "违规", "整改", "警告", "下架", "封禁", "罚款", "暂停营业", "限流"]
_SYSTEM_MESSAGE_HINTS = [
    "系统",
    "平台",
    "通知",
    "尊敬的商家",
    "美团",
    "规则",
    "申诉",
    "处罚",
    "违规",
]

_PENALTY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS platform_penalties (
    id SERIAL PRIMARY KEY,
    source TEXT,
    content TEXT,
    keyword_matched TEXT,
    original_time TIMESTAMPTZ,
    detected_at TIMESTAMPTZ DEFAULT NOW()
);
"""


def _quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _match_keyword(text: str) -> str | None:
    for keyword in KEYWORDS:
        if keyword in text:
            return keyword
    return None


def _looks_like_system_message(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if any(hint in normalized for hint in _SYSTEM_MESSAGE_HINTS):
        return True
    return normalized.startswith("【") or normalized.startswith("[系统]")


async def _is_penalty_message_llm(message_text: str) -> dict:
    """用 LLM 判断 IM 消息是否为平台处罚。"""
    try:
        from src.agents.llm import MODEL_FLASH, call_tool

        penalty_tool = {
            "name": "detect_penalty",
            "description": "判断消息是否为美团平台处罚/警告",
            "input_schema": {
                "type": "object",
                "properties": {
                    "is_penalty": {"type": "boolean"},
                    "penalty_type": {
                        "type": "string",
                        "enum": [
                            "违规扣分",
                            "商品下架",
                            "店铺处罚",
                            "资质问题",
                            "价格违规",
                            "虚假宣传",
                            "配送违规",
                            "其他",
                            "非处罚",
                        ],
                    },
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                },
                "required": ["is_penalty"],
            },
        }
        prompt = f"判断以下美团商家IM消息是否为平台处罚/警告：\n\n{message_text[:500]}"
        result = await call_tool(prompt, penalty_tool, model=MODEL_FLASH)
        if isinstance(result, dict):
            return result
        return {"is_penalty": False, "penalty_type": "非处罚", "severity": "info"}
    except Exception:
        return {"is_penalty": False, "penalty_type": "非处罚", "severity": "info"}


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
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_time(int(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=SH_TZ)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=SH_TZ)
        except ValueError:
            continue
    return None


async def _table_exists(conn, table_name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = $1
            )
            """,
            table_name,
        )
    )


async def _pick_columns(conn, table_name: str) -> tuple[str | None, str | None]:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
        """,
        table_name,
    )
    available = {r["column_name"] for r in rows}

    content_col = None
    for candidate in ("content", "message", "msg", "text", "body", "raw_data"):
        if candidate in available:
            content_col = candidate
            break

    time_col = None
    for candidate in (
        "message_time",
        "created_at",
        "create_time",
        "updated_at",
        "send_time",
        "time",
        "timestamp",
    ):
        if candidate in available:
            time_col = candidate
            break
    return content_col, time_col


async def _collect_matches(
    conn, table_name: str, source: str
) -> list[tuple[str, str, str, datetime | None]]:
    content_col, time_col = await _pick_columns(conn, table_name)
    if not content_col:
        logger.info("Skip %s: no content-like column", table_name)
        return []

    content_ident = _quote_ident(content_col)
    time_sql = f"{_quote_ident(time_col)} AS original_time" if time_col else "NULL AS original_time"
    rows = await conn.fetch(
        f"""
        SELECT
            {content_ident}::text AS content,
            {time_sql}
        FROM {table_name}
        WHERE {content_ident} IS NOT NULL
        """
    )

    matched: list[tuple[str, str, str, datetime | None]] = []
    for row in rows:
        text = str(row["content"] or "").strip()
        if not text:
            continue
        keyword = _match_keyword(text)
        if keyword:
            matched.append((source, text, keyword, _parse_time(row["original_time"])))
            continue

        if not _looks_like_system_message(text):
            continue

        llm_result = await _is_penalty_message_llm(text)
        try:
            is_penalty = bool(llm_result.get("is_penalty"))
            if not is_penalty:
                continue
            penalty_type = str(llm_result.get("penalty_type") or "其他").strip()
            severity = str(llm_result.get("severity") or "info").strip()
            matched.append(
                (
                    source,
                    text,
                    f"LLM:{penalty_type}/{severity}",
                    _parse_time(row["original_time"]),
                )
            )
        except Exception:
            continue
    return matched


async def run_platform_penalties_etl(pool) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(_PENALTY_TABLE_SQL)

            records: list[tuple[str, str, str, datetime | None]] = []

            if await _table_exists(conn, "qnh_im_sessions"):
                records.extend(await _collect_matches(conn, "qnh_im_sessions", "qnh_im_sessions"))
            else:
                logger.info("qnh_im_sessions not found, skip")

            if await _table_exists(conn, "qnh_im_messages"):
                records.extend(await _collect_matches(conn, "qnh_im_messages", "qnh_im_messages"))
            else:
                logger.info("qnh_im_messages not found, skip")

            if not records:
                logger.info("Platform penalties ETL done: no matched messages")
                return

            await conn.executemany(
                """
                INSERT INTO platform_penalties (
                    source,
                    content,
                    keyword_matched,
                    original_time,
                    detected_at
                )
                VALUES ($1, $2, $3, $4, NOW())
                """,
                records,
            )
            logger.info("Platform penalties ETL done: inserted=%d", len(records))
    except Exception:
        logger.exception("Platform penalties ETL failed")
