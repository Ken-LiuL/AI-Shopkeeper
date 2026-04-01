"""Dashboard API routes — reads from both structured and raw sync tables."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re

from fastapi import APIRouter

from src.db import postgres as pg
from src.services.manual_import import ManualImportService

from .schemas import (
    ActionItem,
    ActionOutcome,
    APIResponse,
    DashboardOverview,
    SalesTrendPoint,
    TopAction,
    TopProduct,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)
DEFAULT_STORE_ID = os.environ.get("DEFAULT_STORE_ID", "30850916")


# ── Dataset record helpers ──────────────────────────────────────────


def _parse_data_value(field: dict | str | None) -> float:
    """Parse a dataValue from goldengateway payload field.

    Field is typically: {"dataCode": "...", "dataValue": "3,910.34", ...}
    dataValue may contain commas, percentage signs, or be plain numbers.
    """
    if field is None:
        return 0.0
    if isinstance(field, int | float):
        return float(field)
    if isinstance(field, str):
        raw = field
    elif isinstance(field, dict):
        raw = field.get("dataValue", "")
    else:
        return 0.0
    if not raw:
        return 0.0
    # Remove commas, percentage signs, whitespace
    cleaned = re.sub(r"[,%\s]", "", str(raw))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _get_data_str(field: dict | str | None) -> str:
    """Get string dataValue from a payload field."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return str(field.get("dataValue", ""))
    return str(field)


async def _get_dataset_records(pool, dataset: str) -> list[dict]:
    """Fetch all records from qnh_dataset_records for a given dataset."""
    try:
        rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset = $1",
            dataset,
        )
        results = []
        for row in rows:
            p = row["payload"]
            if isinstance(p, str):
                p = json.loads(p)
            results.append(p)
        return results
    except Exception as e:
        logger.debug("Failed to fetch dataset %s: %s", dataset, e)
        return []


def _extract_metric(raw_data: dict, key: str, use_reference: bool = True) -> float:
    """Extract metric value from complex goldengateway JSON.

    Structure: {key: {indicValue: {originValue: X}, reference: {lastPeriodValue: {originValue: Y}}}}
    If current value is 0 and use_reference=True, fall back to lastPeriodValue.
    """
    field = raw_data.get(key, {})
    if not isinstance(field, dict):
        # Simple flat value
        try:
            return float(field)
        except (TypeError, ValueError):
            return 0.0

    current = 0.0
    indic = field.get("indicValue", {})
    if isinstance(indic, dict):
        current = float(indic.get("originValue", 0) or 0)

    if current == 0 and use_reference:
        ref = field.get("reference", {})
        if isinstance(ref, dict):
            lp = ref.get("lastPeriodValue", {})
            if isinstance(lp, dict):
                current = float(lp.get("originValue", 0) or 0)

    return current


async def _get_latest_metrics(pool) -> dict:
    """Get the latest raw metrics record and parse it."""
    with contextlib.suppress(Exception):
        row = await pool.fetchrow(
            "SELECT raw_data FROM qnh_store_metrics_raw ORDER BY created_at DESC LIMIT 1"
        )
        if row and row["raw_data"]:
            data = row["raw_data"]
            if isinstance(data, str):
                data = json.loads(data)
            return data
    return {}


async def _table_exists(pool, table_name: str) -> bool:
    try:
        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table_name,
        )
        return bool(exists)
    except Exception:
        return False


async def _column_exists(pool, table_name: str, column_name: str) -> bool:
    try:
        exists = await pool.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = $1
                  AND column_name = $2
            )
            """,
            table_name,
            column_name,
        )
        return bool(exists)
    except Exception:
        return False


async def _get_daily_order_metrics(pool) -> tuple[int, float, float, int, float]:
    """Read today's and yesterday's metrics from qnh_daily_metrics (ETL table).

    Returns:
        (today_orders, today_gmv, today_avg_order_value, yesterday_orders, yesterday_gmv)
    """
    # ── Priority 1: qnh_daily_metrics (ETL generated) ──
    if await _table_exists(pool, "qnh_daily_metrics"):
        try:
            rows = await pool.fetch(
                """
                SELECT metric_date,
                       COALESCE(valid_order_count, 0) AS order_count,
                       COALESCE(valid_order_amount, 0) AS gmv,
                       COALESCE(avg_order_value, 0)   AS avg_order_value
                FROM qnh_daily_metrics
                WHERE metric_date IN (CURRENT_DATE, CURRENT_DATE - INTERVAL '1 day')
                  AND channel IS NULL
                ORDER BY metric_date DESC
                """,
            )
            import datetime as _dt
            from datetime import date as _date
            by_date = {str(r["metric_date"]): r for r in rows}
            today_str = str(_date.today())
            yesterday_str = str(_date.today() - _dt.timedelta(days=1))

            t = by_date.get(today_str)
            y = by_date.get(yesterday_str)

            today_orders = int(t["order_count"]) if t else 0
            today_gmv = float(t["gmv"]) if t else 0.0
            today_avg = float(t["avg_order_value"]) if t else 0.0
            yesterday_orders = int(y["order_count"]) if y else 0
            yesterday_gmv = float(y["gmv"]) if y else 0.0

            if today_orders > 0 or yesterday_orders > 0:
                return today_orders, today_gmv, today_avg, yesterday_orders, yesterday_gmv
        except Exception as e:
            logger.debug("qnh_daily_metrics read failed: %s", e)

    # ── Priority 2: qnh_orders (normalized orders table) ──
    if await _table_exists(pool, "qnh_orders"):
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE DATE(order_time AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE) AS today_cnt,
                    COALESCE(SUM(total_amount) FILTER (WHERE DATE(order_time AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE), 0) AS today_gmv,
                    COUNT(*) FILTER (WHERE DATE(order_time AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE - 1) AS yesterday_cnt,
                    COALESCE(SUM(total_amount) FILTER (WHERE DATE(order_time AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE - 1), 0) AS yesterday_gmv
                FROM qnh_orders
                WHERE order_time >= CURRENT_DATE - INTERVAL '2 days'
                  AND COALESCE(status, '') NOT IN ('cancelled', 'refunded')
                """
            )
            if row:
                t_cnt = int(row["today_cnt"] or 0)
                t_gmv = float(row["today_gmv"] or 0)
                y_cnt = int(row["yesterday_cnt"] or 0)
                y_gmv = float(row["yesterday_gmv"] or 0)
                t_avg = t_gmv / t_cnt if t_cnt > 0 else 0.0
                return t_cnt, t_gmv, t_avg, y_cnt, y_gmv
        except Exception as e:
            logger.debug("qnh_orders read failed: %s", e)

    # ── Fallback: qnh_orders_raw (legacy) ──
    if not await _table_exists(pool, "qnh_orders_raw"):
        return 0, 0.0, 0.0, 0, 0.0

    try:
        has_total = await _column_exists(pool, "qnh_orders_raw", "total")
        total_expr = "COALESCE(SUM(total), 0)" if has_total else "0"

        date_col = None
        for candidate in ("order_date", "created_at", "order_time", "pay_time", "synced_at"):
            if await _column_exists(pool, "qnh_orders_raw", candidate):
                date_col = candidate
                break

        where_clause = f"{date_col}::date = CURRENT_DATE" if date_col else "TRUE"
        row = await pool.fetchrow(
            f"""
            SELECT COUNT(*) AS cnt, {total_expr} AS revenue
            FROM qnh_orders_raw
            WHERE {where_clause}
            """
        )
        cnt = int((row and row["cnt"]) or 0)
        rev = float((row and row["revenue"]) or 0)
        return cnt, rev, (rev / cnt if cnt > 0 else 0.0), 0, 0.0
    except Exception:
        return 0, 0.0, 0.0, 0, 0.0


async def _get_low_stock_count(pool) -> int:
    """Count products with low/zero stock."""
    # ── Priority 1: qnh_inventory ──
    if await _table_exists(pool, "qnh_inventory"):
        try:
            count = await pool.fetchval(
                "SELECT COUNT(*) FROM qnh_inventory WHERE COALESCE(stock, 0) < 10"
            )
            if count is not None:
                return int(count)
        except Exception:
            pass

    # ── Fallback: products table ──
    if await _table_exists(pool, "products"):
        with contextlib.suppress(Exception):
            count = await pool.fetchval(
                "SELECT COUNT(*) FROM products WHERE status = 'active' AND COALESCE(stock, 0) < 10"
            )
            return int(count or 0)

    return 0


async def _get_inventory_alert_count(pool) -> int:
    if not await _table_exists(pool, "qnh_inventory"):
        return 0
    try:
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_inventory WHERE COALESCE(stock, 0) < 10"
        )
        return int(count or 0)
    except Exception:
        return 0


async def _get_pending_alert_count(pool) -> int:
    if await _table_exists(pool, "alerts"):
        with contextlib.suppress(Exception):
            count = await pool.fetchval("SELECT COUNT(*) FROM alerts WHERE status = 'pending'")
            if count:
                return int(count)

    with contextlib.suppress(Exception):
        from .alerts import _generate_smart_alerts

        alerts = await asyncio.wait_for(_generate_smart_alerts(pool), timeout=5.0)
        if alerts:
            return len(alerts)

    return await _get_inventory_alert_count(pool)


async def _get_avg_rating(pool) -> float:
    if not await _table_exists(pool, "qnh_reviews_raw"):
        return 0.0
    try:
        date_col = None
        for candidate in ("review_date", "created_at", "synced_at"):
            if await _column_exists(pool, "qnh_reviews_raw", candidate):
                date_col = candidate
                break
        where_clause = f"WHERE {date_col}::date = CURRENT_DATE" if date_col else ""
        avg_rating = await pool.fetchval(
            f"SELECT AVG(rating) FROM qnh_reviews_raw {where_clause}"
        )
        return round(float(avg_rating or 0), 2)
    except Exception:
        return 0.0


async def _get_recent_sync_state(pool, limit: int = 5) -> list[dict]:
    if not await _table_exists(pool, "sync_state"):
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT
                syncer_name,
                COALESCE(last_sync_status, 'unknown') AS last_sync_status,
                COALESCE(last_incremental_sync, last_full_sync, updated_at) AS last_sync_time,
                COALESCE(records_synced, 0) AS records_synced,
                COALESCE(last_sync_duration_ms, 0) AS duration_ms
            FROM sync_state
            ORDER BY updated_at DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
        result = []
        for row in rows:
            last_time = row["last_sync_time"]
            result.append(
                {
                    "syncer_name": row["syncer_name"] or "unknown",
                    "last_sync_status": row["last_sync_status"] or "unknown",
                    "last_sync_time": last_time.isoformat() if last_time else None,
                    "records_synced": int(row["records_synced"] or 0),
                    "duration_ms": int(row["duration_ms"] or 0),
                }
            )
        return result
    except Exception:
        return []


async def _generate_action_items(
    pool,
    *,
    total_products: int | None = None,
    store_records: list[dict] | None = None,
) -> list[ActionItem]:
    """Generate actionable recommendations based on current business data."""
    action_items = []

    try:
        with contextlib.suppress(Exception):
            review = await ManualImportService(pool).get_review(limit=3)
            summary = (
                review.get("open_summary")
                if isinstance(review, dict) and isinstance(review.get("open_summary"), dict)
                else review.get("summary") if isinstance(review, dict) else {}
            )
            if isinstance(summary, dict):
                stockout_count = int(summary.get("stockout_but_selling") or 0)
                catalog_gap_count = int(summary.get("catalog_gaps") or 0)
                missing_price_count = int(summary.get("products_missing_price") or 0)
                mismatch_count = int(summary.get("order_amount_mismatch") or 0)

                if stockout_count > 0:
                    action_items.append(
                        ActionItem(
                            priority="high",
                            action="处理断货热销商品",
                            detail=f"{stockout_count} 款商品有销量但当前库存为 0，先补货或核对库存。",
                            link="/alerts",
                        )
                    )
                if catalog_gap_count > 0:
                    action_items.append(
                        ActionItem(
                            priority="high",
                            action="补齐商品主档",
                            detail=f"{catalog_gap_count} 个商品只出现在订单或库存里，主档还不完整。",
                            link="/products",
                        )
                    )
                if missing_price_count > 0:
                    action_items.append(
                        ActionItem(
                            priority="medium",
                            action="补齐缺失售价",
                            detail=f"{missing_price_count} 个商品没有零售价，价格和毛利分析暂时不准。",
                            link="/products",
                        )
                    )
                if mismatch_count > 0:
                    action_items.append(
                        ActionItem(
                            priority="medium",
                            action="修正订单金额口径",
                            detail=f"{mismatch_count} 单金额与明细不一致，利润分析先排除这部分订单。",
                            link="/orders",
                        )
                    )

        # 1. Check for low stock items (high priority) - 用 alerts 表真实数据
        with contextlib.suppress(Exception):
            low_stock_rows = await pool.fetch(
                """
                SELECT p.name, p.stock,
                       COUNT(*) OVER () AS total_low_stock
                FROM alerts a
                JOIN products p ON a.product_id = p.product_id
                WHERE a.alert_type = 'low_stock' AND a.status = 'pending'
                ORDER BY p.stock ASC NULLS LAST
                LIMIT 3
                """
            )
            low_stock_count = low_stock_rows[0]["total_low_stock"] if low_stock_rows else 0

            if low_stock_count:
                product_names = [row["name"] for row in low_stock_rows if row["name"]]
                detail = f"{low_stock_count}款商品库存不足"
                if product_names:
                    detail += f"，包括：{', '.join(product_names[:2])}"
                    if len(product_names) > 2:
                        detail += "等"

                action_items.append(
                    ActionItem(
                        priority="high",
                        action="紧急补货",
                        detail=detail,
                        link="/inventory",
                    )
                )

        # 2. Check for pricing issues from our own category price distribution (medium priority)
        with contextlib.suppress(Exception):
            overpriced_count = (
                await pool.fetchval(
                    """
                    WITH category_avg AS (
                        SELECT category, AVG(retail_price) AS avg_price
                        FROM products
                        WHERE status = 'active' AND retail_price > 0
                        GROUP BY category
                    )
                    SELECT COUNT(*)
                    FROM products p
                    JOIN category_avg c ON p.category = c.category
                    WHERE p.status = 'active'
                      AND p.retail_price > 100
                      AND p.retail_price > c.avg_price * 1.2
                    """
                )
                or 0
            )

            if overpriced_count > 0:
                action_items.append(
                    ActionItem(
                        priority="medium",
                        action="复核价格",
                        detail=f"{overpriced_count}款商品价格高于同类均价20%以上",
                        link="/pricing",
                    )
                )

        # 3. Check performance metrics from dataset records (priority) or raw data
        if store_records is None:
            store_records = await _get_dataset_records(pool, "store_rank")
        if store_records:
            # Aggregate KPIs across stores
            total_overtime = sum(
                _parse_data_value(r.get("overtime_ord_rate")) for r in store_records
            )
            avg_overtime = total_overtime / len(store_records) if store_records else 0
            total_stockout = sum(
                _parse_data_value(r.get("stockout_loss_amt")) for r in store_records
            )
            total_turnover_days = sum(
                _parse_data_value(r.get("turnover_days_by_quantity")) for r in store_records
            )
            avg_turnover = total_turnover_days / len(store_records) if store_records else 0
            sku_rate = sum(_parse_data_value(r.get("txn_sku_rate")) for r in store_records)
            avg_sku_rate = sku_rate / len(store_records) if store_records else 0

            if avg_overtime > 20:  # > 20%
                action_items.append(
                    ActionItem(
                        priority="high",
                        action="优化配送",
                        detail=f"整单超时率{avg_overtime:.1f}%，严重影响客户满意度",
                        link="/orders",
                    )
                )
            elif avg_overtime > 5:
                action_items.append(
                    ActionItem(
                        priority="medium",
                        action="关注超时率",
                        detail=f"整单超时率{avg_overtime:.1f}%，建议优化配送",
                        link="/alerts",
                    )
                )

            if total_stockout > 1000:
                action_items.append(
                    ActionItem(
                        priority="high",
                        action="减少缺货损失",
                        detail=f"缺货损失¥{total_stockout:,.2f}，需优化库存预警",
                        link="/inventory",
                    )
                )

            if avg_turnover > 90:
                action_items.append(
                    ActionItem(
                        priority="medium",
                        action="加速库存周转",
                        detail=f"平均周转天数{avg_turnover:.0f}天，建议清理滞销品",
                        link="/inventory",
                    )
                )

            if avg_sku_rate < 40:
                action_items.append(
                    ActionItem(
                        priority="low",
                        action="提升动销率",
                        detail=f"商品动销率{avg_sku_rate:.1f}%，{100 - avg_sku_rate:.0f}%商品无销售",
                        link="/products",
                    )
                )
        else:
            metrics = await _get_latest_metrics(pool)
            if metrics:
                overtime_rate = _extract_metric(metrics, "overtime_ord_rate")
                if overtime_rate > 0.2:
                    action_items.append(
                    ActionItem(
                        priority="high",
                        action="优化配送",
                        detail=f"超时订单率{overtime_rate * 100:.1f}%，影响客户满意度",
                        link="/orders",
                    )
                )
                stockout_loss = _extract_metric(metrics, "stockout_loss_amt")
                if stockout_loss > 1000:
                    action_items.append(
                    ActionItem(
                        priority="high",
                        action="减少缺货损失",
                        detail=f"缺货损失¥{stockout_loss:.2f}，优化库存预警",
                        link="/inventory",
                    )
                )

            expose_cnt = 0
            order_cnt = 0
            if metrics:
                expose_cnt = _extract_metric(metrics, "expose_cnt")
                order_cnt = _extract_metric(metrics, "eff_ord_cnt")
            if expose_cnt > 0 and order_cnt > 0:
                conversion_rate = order_cnt / expose_cnt
                if conversion_rate < 0.02:  # < 2%
                    action_items.append(
                        ActionItem(
                            priority="medium",
                            action="提升转化率",
                            detail=f"当前转化率{conversion_rate * 100:.2f}%，建议优化商品展示",
                            link="/products",
                        )
                    )

        # 4. Check for category concentration (low priority)
        with contextlib.suppress(Exception):
            top_category = await pool.fetchrow(
                """
                SELECT category, COUNT(*) as cnt,
                       COUNT(*) * 100.0 / NULLIF(
                           (SELECT COUNT(*) FROM products WHERE status = 'active'), 0
                       ) as percentage
                FROM products
                WHERE status = 'active' AND category != ''
                GROUP BY category
                ORDER BY cnt DESC
                LIMIT 1
                """
            )

            if top_category and top_category["percentage"] and top_category["percentage"] > 40:
                action_items.append(
                    ActionItem(
                        priority="low",
                        action="丰富品类",
                        detail=f"「{top_category['category']}」占比{top_category['percentage']:.0f}%过高，建议增加其他品类",
                        link="/products",
                    )
                )

        # 5. Generate growth opportunities (low priority)
        if total_products is None:
            total_products = (
                await pool.fetchval("SELECT COUNT(*) FROM products WHERE status = 'active'") or 0
            )
        if total_products < 50:
            action_items.append(
                ActionItem(
                    priority="low",
                    action="扩充商品",
                    detail=f"当前在售{total_products}款商品，建议增加商品丰富度",
                    link="/selection",
                )
            )

        # Sort by priority (high -> medium -> low) and limit to top 5
        priority_order = {"high": 0, "medium": 1, "low": 2}
        deduped = []
        seen = set()
        for item in action_items:
            dedupe_key = (item.action, item.link)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(item)
        deduped.sort(key=lambda x: priority_order.get(x.priority, 3))

        return deduped[:5]

    except Exception as e:
        logger.error(f"Failed to generate action items: {e}")
        # Return fallback action items
        return [
            ActionItem(
                priority="medium",
                action="检查系统状态",
                detail="数据分析服务异常，建议检查系统运行状态",
                link="/system/health",
            )
        ]


def _priority_by_rank(rank: int, severity_score: int) -> str:
    if rank == 0 or severity_score >= 3:
        return "high"
    if rank == 1 or severity_score >= 2:
        return "medium"
    return "low"


async def _generate_top_actions(pool) -> list[TopAction]:
    candidates: list[dict] = []

    # 1) 低库存风险
    if await _table_exists(pool, "alerts") and await _table_exists(pool, "products"):
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS item_count,
                    COALESCE(
                        SUM(
                            GREATEST(10 - COALESCE(p.stock, 0), 0)
                            * COALESCE(NULLIF(p.retail_price, 0), NULLIF(p.cost_price, 0), 0)
                        ),
                        0
                    ) AS impact,
                    MIN(COALESCE(p.stock, 0)) AS min_stock,
                    MAX(a.created_at) AS latest_at,
                    MAX(
                        CASE
                            WHEN COALESCE(a.severity, '') IN ('critical', 'high') THEN 3
                            WHEN COALESCE(a.severity, '') IN ('warning', 'medium') THEN 2
                            WHEN COALESCE(a.severity, '') IN ('info', 'low') THEN 1
                            ELSE 0
                        END
                    ) AS severity_score
                FROM alerts a
                LEFT JOIN products p ON p.product_id = a.product_id
                WHERE a.status = 'pending' AND a.alert_type = 'low_stock'
                """
            )
            if row and int(row["item_count"] or 0) > 0:
                item_count = int(row["item_count"] or 0)
                min_stock = int(row["min_stock"] or 0)
                candidates.append(
                    {
                        "type": "low_stock",
                        "title": "优先补货低库存商品",
                        "reason": f"{item_count} 款商品库存告急，最低仅 {min_stock} 件。",
                        "expected_impact_amount": float(row["impact"] or 0),
                        "action_url": "/inventory?low_stock_first=true",
                        "severity_score": int(row["severity_score"] or 2),
                        "latest_at": row["latest_at"],
                    }
                )

    # 2) 价格风险
    if await _table_exists(pool, "products"):
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                """
                WITH category_avg AS (
                    SELECT category, AVG(retail_price) AS avg_price
                    FROM products
                    WHERE status = 'active' AND retail_price > 0 AND category IS NOT NULL AND category != ''
                    GROUP BY category
                ), risky AS (
                    SELECT
                        p.product_id,
                        p.retail_price,
                        c.avg_price,
                        COALESCE(p.monthly_sales, 0) AS monthly_sales,
                        p.updated_at
                    FROM products p
                    JOIN category_avg c ON c.category = p.category
                    WHERE p.status = 'active'
                      AND p.retail_price > c.avg_price * 1.2
                )
                SELECT
                    COUNT(*) AS item_count,
                    COALESCE(SUM((retail_price - avg_price) * GREATEST(monthly_sales, 1)), 0) AS impact,
                    MAX(updated_at) AS latest_at
                FROM risky
                """
            )
            if row and int(row["item_count"] or 0) > 0:
                item_count = int(row["item_count"] or 0)
                candidates.append(
                    {
                        "type": "price_risk",
                        "title": "复核高溢价商品价格",
                        "reason": f"{item_count} 款商品价格高于同类均值 20% 以上。",
                        "expected_impact_amount": float(row["impact"] or 0),
                        "action_url": "/pricing",
                        "severity_score": 2,
                        "latest_at": row["latest_at"],
                    }
                )

    # 3) 客诉/评分风险
    if await _table_exists(pool, "alerts"):
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS item_count,
                    MAX(created_at) AS latest_at,
                    MAX(
                        CASE
                            WHEN COALESCE(severity, '') IN ('critical', 'high') THEN 3
                            WHEN COALESCE(severity, '') IN ('warning', 'medium') THEN 2
                            WHEN COALESCE(severity, '') IN ('info', 'low') THEN 1
                            ELSE 0
                        END
                    ) AS severity_score
                FROM alerts
                WHERE status = 'pending'
                  AND (
                    alert_type ILIKE '%review%'
                    OR alert_type ILIKE '%rating%'
                    OR alert_type ILIKE '%customer%'
                  )
                """
            )
            if row and int(row["item_count"] or 0) > 0:
                item_count = int(row["item_count"] or 0)
                severity_score = int(row["severity_score"] or 2)
                candidates.append(
                    {
                        "type": "customer_risk",
                        "title": "跟进客户体验风险",
                        "reason": f"有 {item_count} 条客户体验相关预警待处理。",
                        "expected_impact_amount": float(item_count * 80),
                        "action_url": "/customer-service",
                        "severity_score": severity_score,
                        "latest_at": row["latest_at"],
                    }
                )

    # 4) 通用待处理预警
    if await _table_exists(pool, "alerts"):
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS pending_count,
                    COUNT(*) FILTER (WHERE COALESCE(severity, '') IN ('critical', 'high')) AS high_count,
                    MAX(created_at) AS latest_at,
                    MAX(
                        CASE
                            WHEN COALESCE(severity, '') IN ('critical', 'high') THEN 3
                            WHEN COALESCE(severity, '') IN ('warning', 'medium') THEN 2
                            WHEN COALESCE(severity, '') IN ('info', 'low') THEN 1
                            ELSE 0
                        END
                    ) AS severity_score
                FROM alerts
                WHERE status = 'pending'
                """
            )
            if row and int(row["pending_count"] or 0) > 0:
                pending_count = int(row["pending_count"] or 0)
                high_count = int(row["high_count"] or 0)
                severity_score = int(row["severity_score"] or 1)
                candidates.append(
                    {
                        "type": "alert_pending",
                        "title": "清理高优先级预警",
                        "reason": f"仍有 {pending_count} 条预警未处理，其中高优先级 {high_count} 条。",
                        "expected_impact_amount": float(high_count * 200 + pending_count * 30),
                        "action_url": "/alerts",
                        "severity_score": severity_score,
                        "latest_at": row["latest_at"],
                    }
                )

    if not candidates:
        return []

    def _timeliness_score(latest_at: object) -> float:
        if hasattr(latest_at, "timestamp"):
            with contextlib.suppress(Exception):
                return float(latest_at.timestamp())
        return 0.0

    candidates.sort(
        key=lambda item: (
            float(item.get("expected_impact_amount") or 0),
            int(item.get("severity_score") or 0),
            _timeliness_score(item.get("latest_at")),
        ),
        reverse=True,
    )

    top_actions: list[TopAction] = []
    for idx, item in enumerate(candidates[:3]):
        top_actions.append(
            TopAction(
                type=str(item["type"]),
                title=str(item["title"]),
                reason=str(item["reason"]),
                expected_impact_amount=round(float(item.get("expected_impact_amount") or 0), 2),
                action_url=str(item["action_url"]),
                priority=_priority_by_rank(idx, int(item.get("severity_score") or 0)),
            )
        )

    return top_actions


def _metadata_label(metadata: dict | None, *keys: str) -> str:
    if not isinstance(metadata, dict):
        return ""
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _build_issue_outcome(
    row: dict[str, object],
    open_summary: dict[str, int] | None = None,
) -> ActionOutcome:
    issue_type = str(row.get("issue_type") or "")
    metadata = row.get("metadata")
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    label = _metadata_label(
        metadata_dict,
        "name",
        "product_name",
        "order_id",
        "sku_id",
        "product_id",
    ) or str(row.get("title") or "最近处理的问题")

    mapping = {
        "product_missing_price": (
            "商品修复",
            f"已补齐 {label} 的价格信息。",
            "下次价格复核和客服回答会直接使用新价格。",
            "/products",
        ),
        "product_catalog_gap": (
            "商品修复",
            f"已补齐 {label} 的主档与知识底座。",
            "下次知识检索会优先命中这条商品资料。",
            "/products",
        ),
        "stockout_but_selling": (
            "库存修复",
            f"已处理 {label} 的断货风险。",
            "下一次库存导入后确认是否恢复可售。",
            "/inventory",
        ),
        "inventory_missing_cost": (
            "库存修复",
            f"已补齐 {label} 的成本价。",
            "后续价格复核会使用真实成本。",
            "/inventory",
        ),
        "order_amount_mismatch": (
            "订单复核",
            f"已复核订单 {label} 的金额口径。",
            "利润分析会优先排除仍未复核的异常订单。",
            "/orders",
        ),
        "selection_candidate": (
            "重点运营",
            f"已将 {label} 纳入重点运营。",
            "下次导入后对比销量、库存和客服咨询变化。",
            "/selection",
        ),
        "bundle_candidate": (
            "套餐候选",
            f"已将 {label} 纳入套餐执行。",
            "观察后续客单价和共购订单占比变化。",
            "/bundles",
        ),
        "cs_low_score_reply": (
            "客服质量",
            f"已处理 {label} 的低分回复。",
            "继续观察后续回复评分是否回升。",
            "/customer-service",
        ),
    }
    category, detail, next_check, link = mapping.get(
        issue_type,
        ("最近动作", str(row.get("title") or "已完成一次处理"), "继续观察后续数据变化。", "/"),
    )
    summary_key_map = {
        "product_missing_price": "products_missing_price",
        "product_catalog_gap": "catalog_gaps",
        "stockout_but_selling": "stockout_but_selling",
        "inventory_missing_cost": "inventory_missing_cost",
        "order_amount_mismatch": "order_amount_mismatch",
    }
    summary_key = summary_key_map.get(issue_type)
    if summary_key and open_summary and summary_key in open_summary:
        detail = f"{detail} 当前剩余 {int(open_summary.get(summary_key) or 0)} 项。"
    happened_at = row.get("updated_at")
    return ActionOutcome(
        title=str(row.get("title") or category),
        detail=detail,
        category=category,
        link=link,
        happened_at=happened_at.isoformat() if hasattr(happened_at, "isoformat") else "",
        next_check=next_check,
    )


async def _get_recent_outcomes(
    pool,
    limit: int = 6,
    open_summary: dict[str, int] | None = None,
) -> list[ActionOutcome]:
    events: list[tuple[float, ActionOutcome]] = []

    def sort_value(value: object) -> float:
        if hasattr(value, "timestamp"):
            with contextlib.suppress(Exception):
                return float(value.timestamp())
        return 0.0

    if await _table_exists(pool, "issue_actions"):
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """
                SELECT issue_type, title, metadata, updated_at
                FROM issue_actions
                WHERE status = 'resolved'
                ORDER BY updated_at DESC NULLS LAST
                LIMIT $1
                """,
                limit,
            )
            for row in rows:
                outcome = _build_issue_outcome(dict(row), open_summary=open_summary)
                events.append((sort_value(row["updated_at"]), outcome))

    if await _table_exists(pool, "manual_import_runs"):
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """
                SELECT import_type, filename, imported_rows, quality_score, created_at
                FROM manual_import_runs
                WHERE status = 'completed' AND COALESCE(dry_run, FALSE) = FALSE
                ORDER BY created_at DESC NULLS LAST
                LIMIT $1
                """,
                3,
            )
            type_labels = {
                "products": "商品",
                "orders": "订单",
                "inventory": "库存",
            }
            for row in rows:
                import_type = str(row["import_type"] or "数据")
                label = type_labels.get(import_type, import_type)
                outcome = ActionOutcome(
                    title=f"完成{label}导入",
                    detail=f"{row['filename']} 已导入 {int(row['imported_rows'] or 0)} 行，质量分 {float(row['quality_score'] or 0):.1f}。",
                    category="数据导入",
                    link="/settings/sync",
                    happened_at=row["created_at"].isoformat() if row["created_at"] else "",
                    next_check="重新查看今日待办，确认这批数据带来的新问题和已修复项。",
                )
                events.append((sort_value(row["created_at"]), outcome))

    if await _table_exists(pool, "price_history"):
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """
                SELECT ph.product_id, ph.old_price, ph.new_price, ph.reason, ph.changed_at, p.name
                FROM price_history ph
                LEFT JOIN products p ON p.product_id = ph.product_id
                ORDER BY ph.changed_at DESC NULLS LAST
                LIMIT $1
                """,
                3,
            )
            for row in rows:
                product_name = row["name"] or row["product_id"] or "商品"
                outcome = ActionOutcome(
                    title="已更新商品价格",
                    detail=f"{product_name}：¥{float(row['old_price'] or 0):.2f} 调整为 ¥{float(row['new_price'] or 0):.2f}。",
                    category="价格复核",
                    link="/pricing",
                    happened_at=row["changed_at"].isoformat() if row["changed_at"] else "",
                    next_check="观察 1 到 3 天的订单、毛利和库存变化，再决定是否继续调整。",
                )
                events.append((sort_value(row["changed_at"]), outcome))

    events.sort(key=lambda item: item[0] or 0, reverse=True)
    return [item[1] for item in events[:limit]]


# Pool is lazily initialized by middleware in main.py


# UNUSED: no frontend caller
@router.get("", response_model=APIResponse[DashboardOverview])
@router.get("/overview", response_model=APIResponse[DashboardOverview])
async def overview() -> APIResponse[DashboardOverview]:
    pool = pg.get_pool()
    total_products = 0
    with contextlib.suppress(Exception):
        total_products = (
            await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE COALESCE(status, 'active') = 'active'")
            or 0
        )
    if total_products == 0:
        with contextlib.suppress(Exception):
            total_products = (
                await pool.fetchval("SELECT COUNT(*) FROM products WHERE status = 'active'") or 0
            )

    today_orders, today_gmv, avg_order_value, yesterday_orders, yesterday_gmv = (
        await _get_daily_order_metrics(pool)
    )
    low_stock_count = await _get_low_stock_count(pool)
    avg_rating = await _get_avg_rating(pool)
    pending_alerts = await _get_pending_alert_count(pool)
    recent_sync_state = await _get_recent_sync_state(pool, limit=5)

    action_items = []
    top_actions = []
    recent_outcomes = []
    review_open_summary = None
    with contextlib.suppress(Exception):
        action_items = await asyncio.wait_for(
            _generate_action_items(pool, total_products=total_products),
            timeout=10.0,
        )
    with contextlib.suppress(Exception):
        top_actions = await asyncio.wait_for(_generate_top_actions(pool), timeout=10.0)
    with contextlib.suppress(Exception):
        review_payload = await asyncio.wait_for(ManualImportService(pool).get_review(limit=3), timeout=10.0)
        if isinstance(review_payload, dict) and isinstance(review_payload.get("open_summary"), dict):
            review_open_summary = {
                str(key): int(value or 0)
                for key, value in review_payload["open_summary"].items()
            }
    with contextlib.suppress(Exception):
        recent_outcomes = await asyncio.wait_for(
            _get_recent_outcomes(pool, limit=6, open_summary=review_open_summary),
            timeout=10.0,
        )
    pending_tasks = len(action_items)

    from decimal import Decimal

    return APIResponse(
        data=DashboardOverview(
            total_products=total_products,
            today_orders=today_orders,
            today_gmv=Decimal(str(round(today_gmv, 2))),
            yesterday_orders=yesterday_orders,
            yesterday_gmv=Decimal(str(round(yesterday_gmv, 2))),
            avg_rating=avg_rating,
            avg_order_value=Decimal(str(round(avg_order_value, 2))),
            total_customers=0,
            conversion_rate=0.0,
            pending_alerts=pending_alerts,
            pending_tasks=pending_tasks,
            low_stock_count=low_stock_count,
            recent_sync_state=recent_sync_state,
            action_items=action_items,
            top_actions=top_actions,
            recent_outcomes=recent_outcomes,
        )
    )


@router.get("/alerts", response_model=APIResponse[list[dict]])
async def dashboard_alerts() -> APIResponse[list[dict]]:
    """Get dashboard alerts from smart alerts generator."""
    pool = pg.get_pool()
    try:
        from .alerts import _generate_smart_alerts

        alerts = await _generate_smart_alerts(pool)
        return APIResponse(data=alerts)
    except Exception as e:
        logger.error("Failed to generate alerts: %s", e)
        return APIResponse(data=[], message="Failed to load alerts")


# UNUSED: no frontend caller
@router.get("/sales-trend", response_model=APIResponse[list[SalesTrendPoint]])
async def sales_trend() -> APIResponse[list[SalesTrendPoint]]:
    pool = pg.get_pool()

    rows: list[dict] = []

    # ── Priority 1: Daily snapshots from qnh_dataset_records ──
    # Each sync run saves store_rank with synced_at timestamp — aggregate by date
    with contextlib.suppress(Exception):
        snapshot_rows = await pool.fetch("""
            SELECT synced_at::date AS date, payload
            FROM qnh_dataset_records
            WHERE dataset = 'store_rank'
              AND synced_at >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY synced_at
        """)
        daily: dict[str, dict] = {}
        for r in snapshot_rows:
            d = str(r["date"])
            p = r["payload"]
            if isinstance(p, str):
                p = json.loads(p)
            orders = int(_parse_data_value(p.get("eff_ord_cnt")))
            revenue = _parse_data_value(p.get("sale_amt_gmv"))
            if d not in daily:
                daily[d] = {"date": d, "quantity": 0, "revenue": 0.0}
            daily[d]["quantity"] += orders
            daily[d]["revenue"] += revenue
        if daily:
            rows = sorted(daily.values(), key=lambda x: x["date"])

    # ── Priority 2: structured sales_history table ──
    if not rows:
        with contextlib.suppress(Exception):
            db_rows = await pool.fetch(
                """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
                   FROM sales_history
                   WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
                   GROUP BY sale_date ORDER BY sale_date"""
            )
            rows = [
                {"date": str(r["date"]), "quantity": r["quantity"], "revenue": float(r["revenue"])}
                for r in db_rows
            ]

    # ── Priority 3: raw metrics per day ──
    if not rows:
        with contextlib.suppress(Exception):
            raw_rows = await pool.fetch("""
                SELECT DISTINCT ON (created_at::date) created_at::date AS date, raw_data
                FROM qnh_store_metrics_raw
                WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY created_at::date, created_at DESC
            """)
            for r in raw_rows:
                data = r["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                rows.append(
                    {
                        "date": str(r["date"]),
                        "quantity": int(_extract_metric(data, "eff_ord_cnt")),
                        "revenue": _extract_metric(data, "sale_amt_gmv"),
                    }
                )
            rows = sorted(rows, key=lambda x: x["date"])

    # Build result — only real data, no simulation
    result_points = [
        SalesTrendPoint(
            date=r["date"],
            quantity=r["quantity"],
            revenue=float(r["revenue"]),
            simulated=False,
        )
        for r in rows
    ]

    # If we only have 1 data point (today), that's fine — frontend handles it
    # As daily sync accumulates, this will fill up automatically

    # Calculate growth rates (day-over-day)
    for i in range(1, len(result_points)):
        prev_revenue = result_points[i - 1].revenue
        curr_revenue = result_points[i].revenue
        if prev_revenue > 0:
            result_points[i].growth_rate = round(
                ((curr_revenue - prev_revenue) / prev_revenue) * 100, 2
            )
        else:
            result_points[i].growth_rate = 0.0

    return APIResponse(data=result_points)


# UNUSED: no frontend caller
@router.get("/top-products", response_model=APIResponse[list[TopProduct]])
async def top_products() -> APIResponse[list[TopProduct]]:
    pool = pg.get_pool()

    # ── Priority 0: products 表 monthly_sales (美团真实数据) ──
    mt_rows = []
    with contextlib.suppress(Exception):
        mt_rows = await pool.fetch(
            """SELECT product_id, name, monthly_sales,
                      ROUND(monthly_sales * retail_price, 2) AS revenue
               FROM products
               WHERE status = 'active' AND monthly_sales > 0
               ORDER BY monthly_sales DESC
               LIMIT 10"""
        )
    if mt_rows:
        return APIResponse(data=[
            TopProduct(
                product_id=r["product_id"],
                name=r["name"],
                total_sales=r["monthly_sales"],
                revenue=float(r["revenue"] or 0),
            ) for r in mt_rows
        ])

    # ── Priority 1: Read from qnh_dataset_records (hotsale_goods) ──
    hotsale = await _get_dataset_records(pool, "hotsale_goods")
    if hotsale:
        products = []
        for rec in hotsale:
            name = _get_data_str(rec.get("product_name"))
            if not name:
                continue
            rank = int(_parse_data_value(rec.get("rank")))
            revenue = _parse_data_value(rec.get("prod_sale_amt"))
            sales = int(_parse_data_value(rec.get("prod_sale_num_gmv")))
            products.append(
                TopProduct(
                    product_id=str(rank),
                    name=name,
                    total_sales=sales,
                    revenue=revenue,
                )
            )
        products.sort(key=lambda p: p.revenue, reverse=True)
        return APIResponse(data=products[:10])

    # ── Fallback: old tables ──
    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT ps.product_id, p.name, SUM(ps.quantity)::int AS total_sales,
                      SUM(ps.revenue) AS revenue
               FROM sales_history ps JOIN products p ON ps.product_id = p.product_id
               WHERE ps.sale_date >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY ps.product_id, p.name
               ORDER BY total_sales DESC LIMIT 10"""
        )

    if not rows:
        with contextlib.suppress(Exception):
            rows = await pool.fetch("""
                SELECT product_id, name,
                       COALESCE(retail_price, 0)::numeric AS revenue,
                       1 AS total_sales
                FROM products
                WHERE status = 'active' AND name != '' AND retail_price IS NOT NULL
                ORDER BY retail_price DESC
                LIMIT 10
            """)

    return APIResponse(
        data=[
            TopProduct(
                product_id=str(r["product_id"]),
                name=r["name"],
                total_sales=int(r.get("total_sales", 0)),
                revenue=float(r.get("revenue", 0)),
            )
            for r in rows
        ]
    )


@router.get("/store-kpis", response_model=APIResponse[dict])
async def store_kpis() -> APIResponse[dict]:
    """Return parsed store KPIs from dataset records or raw metrics."""
    pool = pg.get_pool()

    # ── Priority 0: store_daily_metrics from meituan scraper ──
    daily_metrics = None
    with contextlib.suppress(Exception):
        daily_metrics = await pool.fetchrow(
            """SELECT * FROM store_daily_metrics
               WHERE store_id = $1 AND metric_date = CURRENT_DATE""",
            DEFAULT_STORE_ID,
        )
    if daily_metrics and daily_metrics.get("transaction_volume", 0) > 0:
        dm = daily_metrics
        return APIResponse(
            data={
                "orders": dm["transaction_volume"],
                "gmv": round(float(dm["deal_amount"] or 0), 2),
                "actual_revenue": round(float(dm["settlement_amount"] or 0), 2),
                "product_sales": round(float(dm["deal_amount"] or 0), 2),
                "avg_order_value": round(float(dm["avg_order_value"] or 0), 2),
                "actual_avg_order_value": round(float(dm["avg_order_value"] or 0), 2),
                "net_profit": round(float(dm["settlement_amount"] or 0) - float(dm["commission_amount"] or 0), 2),
                "customers": dm["total_customers"] or 0,
                "new_customers": dm["new_customers"] or 0,
                "old_customers": dm["old_customers"] or 0,
                "delivery_fee": 0.0,
                "package_fee": 0.0,
                "stockout_loss": 0.0,
                "exposure_uv": dm["exposure_uv"] or 0,
                "exposure_pv": dm["exposure_pv"] or 0,
                "conversion_rate": round(float(dm["conversion_rate"] or 0), 2),
                "refund_amount": round(float(dm["refund_amount"] or 0), 2),
                "refund_count": dm["refund_count"] or 0,
                "commission_amount": round(float(dm["commission_amount"] or 0), 2),
            }
        )

    orders_row = None
    with contextlib.suppress(Exception):
        orders_row = await pool.fetchrow(
            """
            SELECT
                COUNT(*)::int AS order_count,
                COALESCE(SUM(total_amount), 0) AS gmv,
                COALESCE(SUM(customer_paid), 0) AS actual_revenue,
                COALESCE(SUM(commission), 0) AS commission_fee,
                COALESCE(SUM(delivery_fee), 0) AS delivery_fee,
                COALESCE(SUM(merchant_discount), 0) AS package_fee,
                COUNT(DISTINCT customer_name) FILTER (WHERE customer_name IS NOT NULL) AS customers
            FROM orders
            WHERE order_date = CURRENT_DATE
              AND customer_paid IS NOT NULL
            """
        )

    product_stats = None
    with contextlib.suppress(Exception):
        product_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*)::int AS active_products,
                COALESCE(SUM(COALESCE(monthly_sales, 0)), 0) AS total_units,
                COALESCE(
                    SUM(COALESCE(monthly_sales, 0)::numeric * COALESCE(retail_price, 0)),
                    0
                ) AS sales_amount,
                COALESCE(
                    SUM(
                        COALESCE(monthly_sales, 0)::numeric
                        * GREATEST(COALESCE(retail_price, 0) - COALESCE(cost_price, 0), 0)
                    ),
                    0
                ) AS gross_profit,
                COALESCE(
                    SUM(
                        GREATEST(0, 10 - COALESCE(stock, 0)) * COALESCE(cost_price, 0)
                    ),
                    0
                ) AS stockout_loss
            FROM products
            WHERE status = 'active'
            """
        )

    orders = int(orders_row["order_count"]) if orders_row and orders_row["order_count"] else 0
    gmv = float(orders_row["gmv"]) if orders_row and orders_row["gmv"] is not None else 0.0
    actual_revenue = (
        float(orders_row["actual_revenue"])
        if orders_row and orders_row["actual_revenue"] is not None
        else 0.0
    )
    delivery_fee = (
        float(orders_row["delivery_fee"])
        if orders_row and orders_row["delivery_fee"] is not None
        else 0.0
    )
    package_fee = (
        float(orders_row["package_fee"])
        if orders_row and orders_row["package_fee"] is not None
        else 0.0
    )
    customers = (
        int(orders_row["customers"]) if orders_row and orders_row["customers"] is not None else 0
    )
    commission_total = (
        float(orders_row["commission_fee"])
        if orders_row and orders_row["commission_fee"] is not None
        else 0.0
    )

    avg_order_value = gmv / orders if orders else 0.0
    actual_avg_order_value = actual_revenue / orders if orders else 0.0

    product_sales = (
        float(product_stats["sales_amount"])
        if product_stats and product_stats["sales_amount"] is not None
        else 0.0
    )
    stockout_loss = (
        float(product_stats["stockout_loss"])
        if product_stats and product_stats["stockout_loss"] is not None
        else 0.0
    )
    gross_profit = (
        float(product_stats["gross_profit"])
        if product_stats and product_stats["gross_profit"] is not None
        else 0.0
    )
    active_products = (
        int(product_stats["active_products"])
        if product_stats and product_stats["active_products"] is not None
        else 0
    )

    has_real_orders = orders > 0
    has_product_stats = active_products > 0

    if has_real_orders or has_product_stats:
        net_profit = actual_revenue - commission_total - delivery_fee if has_real_orders else 0.0
        if net_profit == 0.0:
            net_profit = gross_profit
        if product_sales == 0.0 and has_real_orders:
            product_sales = gmv

        return APIResponse(
            data={
                "orders": orders,
                "gmv": round(gmv, 2),
                "actual_revenue": round(actual_revenue, 2),
                "product_sales": round(product_sales, 2),
                "avg_order_value": round(avg_order_value, 2),
                "actual_avg_order_value": round(actual_avg_order_value, 2),
                "net_profit": round(net_profit, 2),
                "customers": customers,
                "delivery_fee": round(delivery_fee, 2),
                "package_fee": round(package_fee, 2),
                "stockout_loss": round(stockout_loss, 2),
            }
        )

    # ── Fallback: dataset records ──
    store_records = await _get_dataset_records(pool, "store_rank")
    if store_records:
        agg: dict[str, float] = {}
        kpi_keys = [
            "eff_ord_cnt",
            "sale_amt_gmv",
            "actual_pay_amt",
            "prod_sale_amt",
            "unit_price",
            "actual_unit_price",
            "net_profit",
            "user_cnt",
            "delivery_fee",
            "package_fee",
            "stockout_loss_amt",
        ]
        pct_keys = {"overtime_ord_rate", "stockout_refund_rate"}

        for key in kpi_keys:
            agg[key] = sum(_parse_data_value(rec.get(key)) for rec in store_records)
        for key in pct_keys:
            vals = [_parse_data_value(rec.get(key)) for rec in store_records]
            agg[key] = sum(vals) / len(vals) if vals else 0.0
        if agg["eff_ord_cnt"] > 0:
            agg["unit_price"] = agg["sale_amt_gmv"] / agg["eff_ord_cnt"]
            agg["actual_unit_price"] = agg["actual_pay_amt"] / agg["eff_ord_cnt"]

        return APIResponse(
            data={
                "orders": int(agg["eff_ord_cnt"]),
                "gmv": round(agg["sale_amt_gmv"], 2),
                "actual_revenue": round(agg["actual_pay_amt"], 2),
                "product_sales": round(agg["prod_sale_amt"], 2),
                "avg_order_value": round(agg["unit_price"], 2),
                "actual_avg_order_value": round(agg["actual_unit_price"], 2),
                "net_profit": round(agg["net_profit"], 2),
                "customers": int(agg["user_cnt"]),
                "delivery_fee": round(agg["delivery_fee"], 2),
                "package_fee": round(agg["package_fee"], 2),
                "stockout_loss": round(agg["stockout_loss_amt"], 2),
            }
        )

    # ── Fallback: old raw metrics ──
    metrics = await _get_latest_metrics(pool)
    if not metrics:
        return APIResponse(data={}, message="no metrics data")

    kpis = {}
    for key in [
        "eff_ord_cnt",
        "sale_amt_gmv",
        "actual_pay_amt",
        "prod_sale_amt",
        "unit_price",
        "actual_unit_price",
        "net_profit",
        "user_cnt",
        "delivery_fee",
        "package_fee",
        "stockout_loss_amt",
    ]:
        kpis[key] = _extract_metric(metrics, key)

    return APIResponse(
        data={
            "orders": int(kpis["eff_ord_cnt"]),
            "gmv": kpis["sale_amt_gmv"],
            "actual_revenue": kpis["actual_pay_amt"],
            "product_sales": kpis["prod_sale_amt"],
            "avg_order_value": kpis["unit_price"],
            "actual_avg_order_value": kpis["actual_unit_price"],
            "net_profit": kpis["net_profit"],
            "customers": int(kpis["user_cnt"]),
            "delivery_fee": kpis["delivery_fee"],
            "package_fee": kpis["package_fee"],
            "stockout_loss": kpis["stockout_loss_amt"],
        }
    )


@router.get("/ai-stats", response_model=APIResponse[dict])
async def get_ai_stats() -> APIResponse[dict]:
    """返回 AI 今日工作统计，优先采用当前主链真实动作口径。"""
    from datetime import datetime

    pool = pg.get_pool()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    async def safe_count(query: str, *args) -> int:
        try:
            result = await pool.fetchval(query, *args)
            return int(result or 0)
        except Exception:
            return 0

    async def safe_count_if_exists(table_name: str, query: str, *args) -> int:
        if not await _table_exists(pool, table_name):
            return 0
        return await safe_count(query, *args)

    # 今日已处理的告警数
    alerts_handled = await safe_count(
        "SELECT COUNT(*) FROM alerts WHERE status = 'resolved' AND resolved_at >= $1", today_start
    )

    # 今日客服会话数
    cs_replies = await safe_count(
        "SELECT COUNT(*) FROM cs_sessions WHERE created_at >= $1", today_start
    )

    # 今日价格调整数
    pricing_adj = await safe_count_if_exists(
        "price_history",
        "SELECT COUNT(*) FROM price_history WHERE changed_at >= $1",
        today_start,
    )
    if pricing_adj == 0:
        pricing_adj = await safe_count_if_exists(
            "price_changes",
            "SELECT COUNT(*) FROM price_changes WHERE created_at >= $1",
            today_start,
        )

    # 选品运行数
    selection_runs = await safe_count(
        "SELECT COUNT(*) FROM selection_runs WHERE created_at >= $1", today_start
    )

    # 套餐创建数
    bundles_created = await safe_count(
        "SELECT COUNT(*) FROM bundles WHERE created_at >= $1", today_start
    )

    # 今日人工导入批次数
    data_imports = await safe_count_if_exists(
        "manual_import_runs",
        """
        SELECT COUNT(*)
        FROM manual_import_runs
        WHERE created_at >= $1
          AND status = 'completed'
          AND dry_run = FALSE
        """,
        today_start,
    )

    total = alerts_handled + cs_replies + pricing_adj + selection_runs + bundles_created + data_imports

    # 预估增收只基于真实价格调整次数估算，不包含未执行建议。
    estimated = 0.0
    if pricing_adj > 0:
        try:
            avg_order = await pool.fetchval(
                "SELECT AVG(total_amount) FROM orders WHERE order_time >= $1", today_start
            )
            avg_order_val = float(avg_order or 50)
            estimated = round(avg_order_val * pricing_adj * 0.05, 2)  # 假设5%提升
        except Exception:
            estimated = round(50 * pricing_adj * 0.05, 2)

    return APIResponse(data={
        "totalActions": total,
        "alertsHandled": alerts_handled,
        "csReplies": cs_replies,
        "pricingAdj": pricing_adj,
        "selectionRuns": selection_runs,
        "bundlesCreated": bundles_created,
        "dataImports": data_imports,
        "estimatedSaved": str(estimated),
        "reflectionRounds": 0,  # TODO: 从 llm_usage 统计
        "factChecks": alerts_handled,  # 每个告警都做事实核查
    })


# UNUSED: no frontend caller
@router.get("/raw-data-debug")
async def raw_data_debug() -> dict:
    """Debug endpoint: show what's in raw tables."""
    pool = pg.get_pool()
    result = {}
    for table in [
        "qnh_store_metrics_raw",
        "qnh_orders_raw",
        "qnh_traffic_raw",
        "qnh_customers_raw",
        "qnh_traffic_channels_raw",
    ]:
        with contextlib.suppress(Exception):
            count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
            sample = await pool.fetchrow(
                f"SELECT raw_data, synced_at FROM {table} ORDER BY id DESC LIMIT 1"
            )
            result[table] = {
                "count": count,
                "latest": dict(sample) if sample else None,
            }
    return result


# UNUSED: no frontend caller
@router.get("/trends", response_model=APIResponse[list[dict]])
async def sales_trends(
    days: int = 7,
) -> APIResponse[list[dict]]:
    """查询近 N 天销售趋势 — 优先 store_daily_metrics (美团)"""
    pool = pg.get_pool()
    try:
        # Priority 0: store_daily_metrics (美团真实数据)
        trends = []
        with contextlib.suppress(Exception):
            dm_rows = await pool.fetch(
                """SELECT metric_date AS date,
                          transaction_volume AS order_count,
                          deal_amount AS revenue,
                          CASE WHEN transaction_volume > 0
                               THEN deal_amount / transaction_volume ELSE 0 END AS avg_order_value,
                          total_customers AS customers,
                          exposure_uv AS exposure,
                          new_customers
                   FROM store_daily_metrics
                   WHERE metric_date >= CURRENT_DATE - ($1 - 1) * INTERVAL '1 day'
                   ORDER BY metric_date""",
                days,
            )
            if dm_rows:
                trends = [
                    {
                        "date": str(r["date"]),
                        "order_count": int(r["order_count"] or 0),
                        "revenue": round(float(r["revenue"] or 0), 2),
                        "avg_order_value": round(float(r["avg_order_value"] or 0), 2),
                        "customers": int(r["customers"] or 0),
                        "exposure": int(r["exposure"] or 0),
                        "new_customers": int(r["new_customers"] or 0),
                    }
                    for r in dm_rows
                ]

        # Fallback: orders table
        if not trends:
            rows = []
            with contextlib.suppress(Exception):
                rows = await pool.fetch(
                    """SELECT DATE(order_time) AS date,
                              COUNT(*) AS order_count,
                              COALESCE(SUM(total_amount), 0) AS revenue,
                              COALESCE(AVG(total_amount), 0) AS avg_order_value
                       FROM orders
                       WHERE order_time >= CURRENT_DATE - ($1 - 1) * INTERVAL '1 day'
                       GROUP BY DATE(order_time) ORDER BY date""",
                    days,
                )
            trends = [
                {
                    "date": str(r["date"]),
                    "order_count": int(r["order_count"]),
                    "revenue": round(float(r["revenue"]), 2),
                    "avg_order_value": round(float(r["avg_order_value"]), 2),
                }
                for r in rows
            ]

        if not trends:
            # 数据库无订单数据，尝试从 metrics_raw 中提取
            with contextlib.suppress(Exception):
                raw_rows = await pool.fetch(
                    """
                    SELECT DISTINCT ON (created_at::date)
                           created_at::date AS date,
                           raw_data
                    FROM qnh_store_metrics_raw
                    WHERE created_at >= CURRENT_DATE - ($1 - 1) * INTERVAL '1 day'
                    ORDER BY created_at::date, created_at DESC
                    """,
                    days,
                )
                import json as _json

                for r in raw_rows:
                    data = r["raw_data"]
                    if isinstance(data, str):
                        data = _json.loads(data)
                    order_count = int(_extract_metric(data, "eff_ord_cnt"))
                    revenue = _extract_metric(data, "sale_amt_gmv")
                    avg_val = revenue / order_count if order_count > 0 else 0
                    trends.append(
                        {
                            "date": str(r["date"]),
                            "order_count": order_count,
                            "revenue": round(revenue, 2),
                            "avg_order_value": round(avg_val, 2),
                        }
                    )
                trends.sort(key=lambda x: x["date"])

        return APIResponse(data=trends, message=f"近{days}天销售趋势")
    except Exception as e:
        logger.error("Failed to get sales trends: %s", e)
        return APIResponse(success=False, message=f"获取销售趋势失败: {str(e)}", data=[])
