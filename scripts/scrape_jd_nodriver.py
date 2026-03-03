#!/usr/bin/env python3
"""Scrape JD (京东) search results with nodriver and persist competitor prices."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import asyncpg
import nodriver

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = ROOT_DIR / "data" / "jd_competitor_prices.db"
SEARCH_URL_TEMPLATE = "https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
DEFAULT_KEYWORDS = [
    "验孕棒",
    "HIV检测试纸",
    "避孕套",
    "血氧仪",
    "血压计",
    "体温计",
    "血糖仪",
    "医用口罩",
    "创可贴",
    "消毒液",
    "酒精棉片",
    "纱布",
    "护腰带",
    "雾化器",
]
LAZY_SCROLL_STEPS = 12
logger = logging.getLogger("scrape_jd_nodriver")
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS jd_competitor_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    product_name TEXT NOT NULL,
    price REAL,
    shop_name TEXT,
    sales_count REAL,
    sales_text TEXT,
    product_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'jd'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jd_competitor_prices_keyword_url
    ON jd_competitor_prices(keyword, product_url);
CREATE INDEX IF NOT EXISTS idx_jd_competitor_prices_scraped_at
    ON jd_competitor_prices(scraped_at);
"""

EXTRACTION_SCRIPT = """
(() => {
  const clean = (text) => {
    if (!text) return '';
    return text.replace(/\\s+/g, ' ').trim();
  };
  const toUrl = (anchor, sku) => {
    if (anchor && anchor.href) {
      return anchor.href;
    }
    if (sku) {
      return `https://item.jd.com/${sku}.html`;
    }
    return '';
  };
  const parseSales = (text) => {
    const normalized = clean(text).replace(/[,，]/g, '');
    if (!normalized) {
      return { count: null, text: '' };
    }
    const match = normalized.match(/([\\d.]+)/);
    if (!match) {
      return { count: null, text: normalized };
    }
    let value = parseFloat(match[1]);
    if (!Number.isFinite(value)) {
      return { count: null, text: normalized };
    }
    if (/万/.test(normalized)) {
      value *= 10000;
    } else if (/千/.test(normalized)) {
      value *= 1000;
    }
    return { count: Math.round(value), text: normalized };
  };
  const cards = Array.from(
    document.querySelectorAll('#J_goodsList .gl-warp .gl-item, #J_goodsList li.gl-item')
  );
  const seen = new Set();
  const payload = [];
  for (const card of cards) {
    const sku =
      card.getAttribute('data-sku') ||
      card.getAttribute('data-sku-id') ||
      card.getAttribute('data-spu') ||
      '';
    const nameEl = card.querySelector('.p-name em');
    const anchor = card.querySelector('.p-name a');
    const priceEl = card.querySelector('.p-price i');
    const shopEl = card.querySelector('.p-shop span, .p-shop a, .p-shopname span');
    const salesEl = card.querySelector('.p-commit a, .p-commit strong');
    const priceRaw = priceEl ? priceEl.innerText : '';
    const priceVal = parseFloat(priceRaw.replace(/[^\\d.]/g, ''));
    const sales = parseSales(salesEl ? salesEl.innerText : '');
    const name = clean(nameEl ? nameEl.innerText : '');
    const url = toUrl(anchor, sku);
    if (!name || !url || seen.has(url)) {
      continue;
    }
    seen.add(url);
    payload.push({
      sku,
      name,
      price: Number.isFinite(priceVal) ? priceVal : null,
      shop: clean(shopEl ? shopEl.innerText : ''),
      salesCount: sales.count,
      salesText: sales.text,
      url
    });
  }
  window.__jd_products = payload;
})();
"""


@dataclass(slots=True)
class JDProduct:
    keyword: str
    product_name: str
    price: float | None
    shop_name: str
    sales_count: int | None
    sales_text: str
    product_url: str
    scraped_at: datetime

    def sqlite_tuple(self) -> tuple[Any, ...]:
        return (
            self.keyword,
            self.product_name,
            self.price,
            self.shop_name,
            self.sales_count,
            self.sales_text,
            self.product_url,
            self.scraped_at.isoformat(),
            "jd",
        )

    def pg_tuple(self) -> tuple[Any, ...]:
        return (
            self.product_name,
            self.shop_name or "京东健康",
            self.price,
            self.product_url,
            self.keyword,
            self.scraped_at,
        )


class ResultWriter:
    def __init__(self, sqlite_path: Path, database_url: str, dry_run: bool) -> None:
        self.sqlite_path = sqlite_path
        self.database_url = database_url
        self.dry_run = dry_run
        self._sqlite_conn: sqlite3.Connection | None = None
        self._pg_pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        if self.dry_run:
            return
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_conn = sqlite3.connect(
            self.sqlite_path, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES
        )
        self._sqlite_conn.executescript(SQLITE_SCHEMA)
        self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
        if self.database_url:
            self._pg_pool = await asyncpg.create_pool(
                self.database_url, min_size=1, max_size=3, timeout=60
            )

    async def close(self) -> None:
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
        if self._sqlite_conn:
            self._sqlite_conn.close()
            self._sqlite_conn = None

    async def write(self, rows: Sequence[JDProduct]) -> None:
        if self.dry_run or not rows:
            return
        if self._sqlite_conn:
            await asyncio.to_thread(self._write_sqlite, rows)
        if self._pg_pool:
            await self._write_postgres(rows)

    def _write_sqlite(self, rows: Sequence[JDProduct]) -> None:
        assert self._sqlite_conn is not None
        sql = """
            INSERT INTO jd_competitor_prices (
                keyword, product_name, price, shop_name, sales_count,
                sales_text, product_url, scraped_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(keyword, product_url) DO UPDATE SET
                price=excluded.price,
                shop_name=excluded.shop_name,
                sales_count=excluded.sales_count,
                sales_text=excluded.sales_text,
                scraped_at=excluded.scraped_at;
        """
        tuples = [row.sqlite_tuple() for row in rows]
        self._sqlite_conn.executemany(sql, tuples)
        self._sqlite_conn.commit()

    async def _write_postgres(self, rows: Sequence[JDProduct]) -> None:
        assert self._pg_pool is not None
        valid_rows = [row for row in rows if row.price is not None]
        if not valid_rows:
            return
        delete_pairs = {(row.product_name, row.shop_name or "京东健康") for row in valid_rows}
        async with self._pg_pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "DELETE FROM competitor_products WHERE product_name=$1 AND competitor_name=$2",
                    [(name, shop) for name, shop in delete_pairs],
                )
                await conn.executemany(
                    """
                    INSERT INTO competitor_products (
                        product_name, competitor_name, price, product_url, category, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [row.pg_tuple() for row in valid_rows],
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("python scripts/scrape_jd_nodriver.py", description=__doc__)
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Override keywords (comma-separated or space separated).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print results, skip DB writes.")
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help=f"SQLite output path (default: {DEFAULT_SQLITE_PATH})",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Optional Postgres DATABASE_URL.",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=3.0,
        help="Minimum delay between keyword searches (seconds).",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=5.0,
        help="Maximum delay between keyword searches (seconds).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (default: INFO).",
    )
    return parser.parse_args()


def resolve_keywords(raw: Sequence[str] | None) -> list[str]:
    if not raw:
        return DEFAULT_KEYWORDS.copy()
    normalized: list[str] = []
    seen: set[str] = set()
    for chunk in raw:
        for token in chunk.split(","):
            word = token.strip()
            if not word or word in seen:
                continue
            seen.add(word)
            normalized.append(word)
    return normalized or DEFAULT_KEYWORDS.copy()


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _signal_callback(s, stop_event))
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())


def _signal_callback(sig: signal.Signals, stop_event: asyncio.Event) -> None:
    if stop_event.is_set():
        return
    logging.getLogger("scrape_jd_nodriver").info("Received %s, shutting down...", sig.name)
    stop_event.set()


async def start_browser() -> nodriver.Browser:
    logger.info("Launching Chrome via nodriver (headless=False)...")
    browser = await nodriver.start(
        headless=False,
        browser_args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    return browser


async def scrape_keyword(
    browser: nodriver.Browser, keyword: str, stop_event: asyncio.Event
) -> list[JDProduct]:
    url = SEARCH_URL_TEMPLATE.format(keyword=quote_plus(keyword))
    logger.info("Searching JD for '%s' → %s", keyword, url)
    page = await browser.get(url)
    await page.sleep(4)
    if stop_event.is_set():
        return []
    await trigger_lazy_loading(page, stop_event)
    if stop_event.is_set():
        return []
    await page.evaluate(EXTRACTION_SCRIPT)
    payload = await page.evaluate("JSON.stringify(window.__jd_products || [])")
    records = json.loads(payload) if payload else []
    scraped_at = datetime.now(UTC)
    products: list[JDProduct] = []
    for item in records:
        name = (item.get("name") or "").strip()
        url_value = (item.get("url") or "").strip()
        if not name or not url_value:
            continue
        price_value = item.get("price")
        price = float(price_value) if isinstance(price_value, int | float) else None
        shop_name = (item.get("shop") or "京东健康").strip() or "京东健康"
        sales_count = item.get("salesCount")
        if isinstance(sales_count, int | float):
            sales_count = int(sales_count)
        else:
            sales_count = None
        sales_text = (item.get("salesText") or "").strip()
        products.append(
            JDProduct(
                keyword=keyword,
                product_name=name[:200],
                price=price,
                shop_name=shop_name[:120],
                sales_count=sales_count,
                sales_text=sales_text[:120],
                product_url=url_value,
                scraped_at=scraped_at,
            )
        )
    return products


async def trigger_lazy_loading(page: nodriver.Page, stop_event: asyncio.Event) -> None:
    for step in range(LAZY_SCROLL_STEPS):
        if stop_event.is_set():
            break
        await page.evaluate(f"window.scrollBy(0, {400 + step * 80});")
        await page.sleep(0.35)
    await page.evaluate("window.scrollTo(0, 0);")


async def wait_with_cancellation(delay: float, stop_event: asyncio.Event) -> None:
    if delay <= 0:
        return
    loop = asyncio.get_running_loop()
    end = loop.time() + delay
    while not stop_event.is_set():
        remaining = end - loop.time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.5, remaining))


async def run(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    keywords = resolve_keywords(args.keywords)
    if args.delay_min > args.delay_max:
        raise ValueError("--delay-min cannot exceed --delay-max")
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    writer = ResultWriter(Path(args.sqlite_path), args.database_url, args.dry_run)
    await writer.start()
    browser: nodriver.Browser | None = None
    stored = 0
    try:
        browser = await start_browser()
        for idx, keyword in enumerate(keywords, start=1):
            if stop_event.is_set():
                logger.info("Stop signal received, aborting remaining keywords.")
                break
            try:
                products = await scrape_keyword(browser, keyword, stop_event)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Keyword '%s' failed: %s", keyword, exc, exc_info=True)
                continue
            if not products:
                logger.info("No products found for '%s'", keyword)
            elif args.dry_run:
                for product in products:
                    logger.info(
                        "[DRY] %s | %s | ¥%s | %s | sales=%s",
                        product.keyword,
                        product.product_name,
                        f"{product.price:.2f}" if product.price is not None else "N/A",
                        product.shop_name,
                        product.sales_count or product.sales_text or "N/A",
                    )
            else:
                await writer.write(products)
                stored += len(products)
                logger.info(
                    "Stored %d JD products for '%s' (keyword %d/%d)",
                    len(products),
                    keyword,
                    idx,
                    len(keywords),
                )
            if idx < len(keywords):
                delay = random.uniform(args.delay_min, args.delay_max)
                logger.info("Sleeping %.1f seconds before next keyword...", delay)
                await wait_with_cancellation(delay, stop_event)
    finally:
        if browser:
            try:
                await browser.close()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Browser close failed: %s", exc)
        await writer.close()
    logger.info("JD scraping finished. Stored rows: %d", stored)


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()
