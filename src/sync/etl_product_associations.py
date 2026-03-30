from __future__ import annotations

import json
import logging
from collections import Counter
from itertools import combinations
from typing import Any

logger = logging.getLogger(__name__)

_ASSOCIATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS product_associations (
    id SERIAL PRIMARY KEY,
    product_a TEXT,
    product_b TEXT,
    co_occurrence INT,
    confidence NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(product_a, product_b)
);
"""


def _normalize_product_name(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split())


def _extract_name_from_item(item: Any) -> str:
    if isinstance(item, str):
        return _normalize_product_name(item)
    if not isinstance(item, dict):
        return ""
    for key in (
        "product_name",
        "productName",
        "name",
        "title",
        "sku_name",
        "skuName",
        "spu_name",
        "spuName",
        "goods_name",
        "goodsName",
        "drug_name",
        "drugName",
    ):
        if key in item:
            name = _normalize_product_name(item.get(key))
            if name:
                return name
    return ""


def _extract_items_from_order(order: Any) -> list[str]:
    names: list[str] = []
    if isinstance(order, list):
        for item in order:
            name = _extract_name_from_item(item)
            if name:
                names.append(name)
        return names

    if not isinstance(order, dict):
        return names

    for key in ("items", "products", "productList", "goodsList", "skuList", "orderItems"):
        data = order.get(key)
        if isinstance(data, list):
            for item in data:
                name = _extract_name_from_item(item)
                if name:
                    names.append(name)

    if not names:
        fallback = _extract_name_from_item(order)
        if fallback:
            names.append(fallback)

    return names


def _extract_orders(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        if all(isinstance(item, dict) and _extract_name_from_item(item) for item in payload):
            return [{"items": payload}]
        return payload

    if isinstance(payload, dict):
        orders: list[Any] = []
        for key in ("orders", "orderList", "order_list", "list"):
            data = payload.get(key)
            if isinstance(data, list):
                orders.extend(data)

        data_field = payload.get("data")
        if isinstance(data_field, list):
            orders.extend(data_field)
        elif isinstance(data_field, dict):
            for key in ("orders", "orderList", "list"):
                nested = data_field.get(key)
                if isinstance(nested, list):
                    orders.extend(nested)

        if orders:
            return orders

        if isinstance(payload.get("items"), list):
            return [payload]

        if any(key in payload for key in ("orderId", "order_id", "id")):
            return [payload]

    return []


async def _pick_orders_payload_column(conn) -> str | None:
    rows = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'qnh_orders_raw'
        """
    )
    available = {row["column_name"] for row in rows}
    for candidate in ("content", "raw_data"):
        if candidate in available:
            return candidate
    return None


async def _has_rows(conn, table: str) -> bool:
    """Return True if the table exists and has at least one row."""
    exists = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = $1
        )
        """,
        table,
    )
    if not exists:
        return False
    count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
    return (count or 0) > 0


async def run_product_associations_etl(pool) -> None:
    """统计订单商品共现关系并写入 product_associations。

    数据源优先级：
      1. qnh_orders_raw（raw JSONB，content 或 raw_data 列）
      2. qnh_orders（结构化表，items JSONB 列）— 当 qnh_orders_raw 为空时自动降级
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(_ASSOCIATION_TABLE_SQL)

            # --- 决定数据源 ---
            use_raw = await _has_rows(conn, "qnh_orders_raw")
            if use_raw:
                payload_col = await _pick_orders_payload_column(conn)
                if not payload_col:
                    logger.warning(
                        "qnh_orders_raw exists but has no content/raw_data column; "
                        "falling back to qnh_orders"
                    )
                    use_raw = False

            if use_raw:
                rows = await conn.fetch(
                    f"""
                    SELECT {payload_col} AS payload
                    FROM qnh_orders_raw
                    WHERE {payload_col} IS NOT NULL
                    """
                )
            else:
                # 从结构化 qnh_orders 表读取，把每行包装成兼容格式
                logger.info("使用 qnh_orders 作为数据源（qnh_orders_raw 为空或不存在）")
                raw_rows = await conn.fetch(
                    """
                    SELECT order_id, items
                    FROM qnh_orders
                    WHERE items IS NOT NULL
                    """
                )
                # 把 qnh_orders.items 包装成 run_product_associations_etl 期望的 payload 格式
                rows = [{"payload": {"orderId": r["order_id"], "items": r["items"]}} for r in raw_rows]

            product_order_counts: Counter[str] = Counter()
            pair_counts: Counter[tuple[str, str]] = Counter()

            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        continue

                for order in _extract_orders(payload):
                    unique_names = {
                        name
                        for name in _extract_items_from_order(order)
                        if len(name) >= 2
                    }
                    if len(unique_names) < 2:
                        continue

                    for name in unique_names:
                        product_order_counts[name] += 1

                    for left, right in combinations(sorted(unique_names), 2):
                        pair_counts[(left, right)] += 1

            records: list[tuple[str, str, int, float]] = []
            for (product_a, product_b), co_occurrence in pair_counts.items():
                base_count = product_order_counts.get(product_a, 0)
                confidence = float(co_occurrence / base_count) if base_count > 0 else 0.0
                records.append((product_a, product_b, int(co_occurrence), confidence))

            if not records:
                logger.info("Product associations ETL done: no associations extracted")
                return

            await conn.executemany(
                """
                INSERT INTO product_associations (
                    product_a,
                    product_b,
                    co_occurrence,
                    confidence,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (product_a, product_b) DO UPDATE SET
                    co_occurrence = EXCLUDED.co_occurrence,
                    confidence = EXCLUDED.confidence,
                    updated_at = NOW()
                """,
                records,
            )
            logger.info("Product associations ETL done: upserted=%d", len(records))
    except Exception:
        logger.exception("Product associations ETL failed")
