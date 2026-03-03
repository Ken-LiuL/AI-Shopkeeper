"""预测性补货引擎 — 利用热销商品真实销量+库存估算提前发出预警。"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.db import postgres as pg

logger = logging.getLogger(__name__)

HOTSALE_DATASET = "hotsale_goods"
HOTSALE_WINDOW_DAYS = 7  # qnh hotsale 榜单为近7天窗口
SAFETY_STOCK_DAYS = 14
LEAD_TIME_DAYS = 3
URGENT_THRESHOLD_DAYS = 5
WARNING_THRESHOLD_DAYS = 10

MASK_KEYWORDS = ("口罩", "mask", "n95", "kn95")
CONDOM_KEYWORDS = ("避孕套", "安全套", "condom")


@dataclass(slots=True)
class ReplenishmentPrediction:
    product_name: str
    current_daily_sales: float
    projected_daily_sales: float
    days_until_oos: float
    suggested_restock_qty: int
    urgency: str
    seasonal_weight: float
    current_stock: int
    sales_last_7d: int
    avg_price: float
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "product_name": self.product_name,
            "current_daily_sales": self.current_daily_sales,
            "projected_daily_sales": self.projected_daily_sales,
            "days_until_oos": self.days_until_oos,
            "suggested_restock_qty": self.suggested_restock_qty,
            "urgency": self.urgency,
            "seasonal_weight": self.seasonal_weight,
            "current_stock": self.current_stock,
            "sales_last_7d": self.sales_last_7d,
            "avg_price": self.avg_price,
        }
        if self.extra:
            payload["extra"] = self.extra
        return payload


async def predict_replenishment() -> list[dict[str, Any]]:
    """生成补货预测列表（主入口）。"""

    pool = pg.get_pool()
    hotsale_records = await _load_hotsale_records(pool)
    if not hotsale_records:
        logger.info("未获取到 hotsale_goods 数据，无法生成补货预测")
        return []

    product_names = [_extract_data_value(rec, "product_name").strip() for rec in hotsale_records]
    product_names = [name for name in product_names if name]
    inventory_index = await _load_inventory_snapshot(pool)
    product_meta = await _load_product_meta(pool, product_names)

    predictions: list[ReplenishmentPrediction] = []
    today = date.today()

    for record in hotsale_records:
        name = _extract_data_value(record, "product_name").strip()
        if not name:
            continue

        sales_units = int(_parse_number(_extract_data_value(record, "prod_sale_num_gmv")))
        if sales_units <= 0:
            continue

        sale_amount = _parse_number(_extract_data_value(record, "prod_sale_amt"))
        actual_pay_amount = _parse_number(_extract_data_value(record, "prod_actual_pay_amt"))
        avg_price = _safe_avg_price(sales_units, actual_pay_amount or sale_amount)
        rank = int(_parse_number(_extract_data_value(record, "rank")))

        current_daily = round(sales_units / HOTSALE_WINDOW_DAYS, 2)
        seasonal_weight, season_note = _seasonal_weight(name, today)
        projected_daily = round(max(current_daily * seasonal_weight, 0.1), 2)

        current_stock = _resolve_stock(
            name=name,
            inventory_index=inventory_index,
            product_meta=product_meta,
            avg_price=avg_price,
            rank=rank,
        )
        if current_stock < 0:
            current_stock = 0

        days_until_oos = (
            round(current_stock / projected_daily, 1) if projected_daily > 0 else math.inf
        )
        urgency = _classify_urgency(days_until_oos)

        target_cover_days = SAFETY_STOCK_DAYS + LEAD_TIME_DAYS
        target_stock = projected_daily * target_cover_days
        suggested_qty = max(0, math.ceil(target_stock - current_stock))

        predictions.append(
            ReplenishmentPrediction(
                product_name=name,
                current_daily_sales=current_daily,
                projected_daily_sales=projected_daily,
                days_until_oos=days_until_oos if math.isfinite(days_until_oos) else 999,
                suggested_restock_qty=suggested_qty,
                urgency=urgency,
                seasonal_weight=seasonal_weight,
                current_stock=current_stock,
                sales_last_7d=sales_units,
                avg_price=avg_price,
                extra={
                    "rank": rank,
                    "seasonality_note": season_note,
                    "sale_amount_7d": sale_amount,
                    "actual_pay_amount_7d": actual_pay_amount,
                },
            )
        )

    urgency_order = {"urgent": 0, "warning": 1, "normal": 2}
    predictions.sort(key=lambda p: (urgency_order.get(p.urgency, 3), p.days_until_oos))

    return [prediction.to_dict() for prediction in predictions]


async def _load_hotsale_records(pool) -> list[dict[str, Any]]:
    rows = []

    if pool:
        try:
            rows = await pool.fetch(
                "SELECT payload FROM qnh_dataset_records WHERE dataset = $1",
                HOTSALE_DATASET,
            )
        except Exception as exc:
            logger.warning("读取 PG hotsale_goods 失败: %s", exc)

    if rows:
        return [_normalize_payload(row["payload"]) for row in rows]

    return _load_hotsale_from_sqlite()


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("payload 不是合法 JSON: %s", payload[:80])
    return {}


def _load_hotsale_from_sqlite() -> list[dict[str, Any]]:
    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "qnh_sync.db"
    if not db_path.exists():
        return []

    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT payload FROM qnh_dataset_records WHERE dataset = ?", (HOTSALE_DATASET,))
        rows = cur.fetchall()
        conn.close()
        return [_normalize_payload(row[0]) for row in rows]
    except Exception as exc:
        logger.warning("SQLite fallback 读取失败: %s", exc)
        return []


async def _load_inventory_snapshot(pool) -> dict[str, int]:
    if not pool:
        return {}
    try:
        rows = await pool.fetch(
            """
            SELECT LOWER(TRIM(COALESCE(product_name, ''))) AS name,
                   COALESCE(available_stock, current_stock, 0) AS stock
            FROM qnh_inventory
            WHERE snapshot_time >= NOW() - INTERVAL '30 days'
            """
        )
        inventory: dict[str, int] = {}
        for row in rows:
            name = row["name"]
            stock = int(row["stock"] or 0)
            if not name:
                continue
            inventory[name] = max(stock, inventory.get(name, 0))
        return inventory
    except Exception as exc:
        logger.info("qnh_inventory 数据不可用: %s", exc)
        return {}


async def _load_product_meta(pool, names: list[str]) -> dict[str, dict[str, Any]]:
    if not pool or not names:
        return {}
    # 去重并转换为集合以降低 SQL in 的长度
    unique_names = sorted({name.strip() for name in names if name})
    if not unique_names:
        return {}
    try:
        rows = await pool.fetch(
            """
            SELECT LOWER(TRIM(name)) AS name,
                   retail_price,
                   cost_price,
                   category
            FROM qnh_products
            WHERE name = ANY($1::text[])
            """,
            unique_names,
        )
        return {row["name"]: dict(row) for row in rows if row["name"]}
    except Exception as exc:
        logger.info("qnh_products 元数据查询失败: %s", exc)
        return {}


def _extract_data_value(record: dict[str, Any], field_name: str) -> str:
    field = record.get(field_name)
    if isinstance(field, dict):
        value = field.get("dataValue")
        return str(value or "")
    if field is None:
        return ""
    return str(field)


def _parse_number(value: str | int | float) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _safe_avg_price(units: int, amount: float) -> float:
    if units <= 0:
        return round(amount or 0.0, 2)
    return round((amount or 0.0) / max(units, 1), 2)


def _seasonal_weight(product_name: str, today: date) -> tuple[float, str | None]:
    name = product_name.lower()
    weight = 1.0
    note: str | None = None

    if any(keyword in name for keyword in MASK_KEYWORDS) and today.month in (3, 4, 5):
        weight = 1.5
        note = "春季防护需求高峰"
    elif any(keyword in name for keyword in CONDOM_KEYWORDS) and _is_holiday_season(today):
        weight = 1.3
        note = "节假日亲密场景需求上升"

    return weight, note


def _is_holiday_season(today: date) -> bool:
    windows = (
        ((2, 7), (2, 21)),  # 情人节前后
        ((5, 15), (5, 25)),  # 520
        ((8, 1), (8, 20)),  # 七夕
        ((12, 20), (12, 31)),  # 跨年/圣诞
    )
    for (start_month, start_day), (end_month, end_day) in windows:
        start = date(today.year, start_month, start_day)
        end = date(today.year, end_month, end_day)
        if start <= today <= end:
            return True
    return False


def _resolve_stock(
    name: str,
    inventory_index: dict[str, int],
    product_meta: dict[str, dict[str, Any]],
    avg_price: float,
    rank: int,
) -> int:
    normalized = name.lower()
    if normalized in inventory_index:
        return inventory_index[normalized]

    meta = product_meta.get(normalized, {})
    price = float(meta.get("retail_price") or avg_price or 0)
    if price <= 0:
        price = float(meta.get("cost_price") or avg_price or 0)

    # 基于价格和排名估算库存区间
    if price >= 300:
        base = 20
    elif price >= 100:
        base = 45
    elif price >= 50:
        base = 80
    else:
        base = 120

    # 排名越高，默认周转更快 → 在售库存略高
    if rank <= 10:
        base = int(base * 1.2)
    elif rank >= 40:
        base = int(base * 0.8)

    return max(base, 10)


def _classify_urgency(days_until_oos: float) -> str:
    if not math.isfinite(days_until_oos):
        return "normal"
    if days_until_oos <= URGENT_THRESHOLD_DAYS:
        return "urgent"
    if days_until_oos <= WARNING_THRESHOLD_DAYS:
        return "warning"
    return "normal"
