from __future__ import annotations

import html
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

POLICY_URLS = [
    "https://rules-center.meituan.com/rules-detail/372",
    "https://rules-center.meituan.com/rules-detail/373",
    "https://rules-center.meituan.com/rules-detail/374",
]

_POLICY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS policy_documents (
    id SERIAL PRIMARY KEY,
    url TEXT,
    title TEXT,
    content TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(url)
);
"""


def _extract_title(page: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()


def _html_to_text(page: str) -> str:
    text = re.sub(
        r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
        " ",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


async def _fetch_policy(session: aiohttp.ClientSession, url: str) -> tuple[str, str, str] | None:
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.info("Policy crawl skip %s: status=%s", url, resp.status)
                return None
            body = await resp.text(errors="ignore")
            title = _extract_title(body)
            content = _html_to_text(body)
            if not content:
                logger.info("Policy crawl skip %s: empty content", url)
                return None
            return (url, title, content)
    except Exception as exc:
        logger.info("Policy crawl skip %s: %s", url, exc)
        return None


async def run_policy_crawler_etl(pool) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(_POLICY_TABLE_SQL)

        timeout = aiohttp.ClientTimeout(total=10)
        headers = {"User-Agent": "AI-Shopkeeper-ETL/1.0"}
        records: list[tuple[str, str, str]] = []
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for url in POLICY_URLS:
                item = await _fetch_policy(session, url)
                if item:
                    records.append(item)

        if not records:
            logger.info("Policy crawler ETL done: no documents fetched")
            return

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO policy_documents (url, title, content, fetched_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (url) DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    fetched_at = NOW()
                """,
                records,
            )
        logger.info("Policy crawler ETL done: upserted=%d", len(records))
    except Exception:
        logger.exception("Policy crawler ETL failed")
