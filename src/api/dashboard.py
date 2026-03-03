"""Dashboard API routes — reads from both structured and raw sync tables."""

from __future__ import annotations

import contextlib
import json
import logging
import re

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import ActionItem, APIResponse, DashboardOverview, SalesTrendPoint, TopProduct

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


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
        # Re-acquire pool if connection is dead
        try:
            rows = await pool.fetch(
                "SELECT payload FROM qnh_dataset_records WHERE dataset = $1",
                dataset,
            )
        except Exception:
            from src.db import postgres as pg_mod

            pool = await pg_mod.ensure_pool()
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


async def _generate_action_items(pool) -> list[ActionItem]:
    """Generate actionable recommendations based on current business data."""
    action_items = []

    try:
        # 1. Check for low stock items (high priority)
        with contextlib.suppress(Exception):
            low_stock_count = (
                await pool.fetchval("""
                SELECT COUNT(*) FROM qnh_products
                WHERE status = '在售' AND stock_num IS NOT NULL AND stock_num < 10
            """)
                or 0
            )

            if low_stock_count > 0:
                sample_products = await pool.fetch("""
                    SELECT name FROM qnh_products
                    WHERE status = '在售' AND stock_num IS NOT NULL AND stock_num < 10
                    ORDER BY stock_num ASC LIMIT 3
                """)
                product_names = [row["name"] for row in sample_products]
                detail = f"{low_stock_count}款商品库存不足10件"
                if product_names:
                    detail += f"，包括：{', '.join(product_names[:2])}"
                    if len(product_names) > 2:
                        detail += "等"

                action_items.append(
                    ActionItem(
                        priority="high",
                        action="紧急补货",
                        detail=detail,
                        link="/inventory/restock",
                    )
                )

        # 2. Check for pricing issues from competitor analysis (medium priority)
        with contextlib.suppress(Exception):
            overpriced_count = (
                await pool.fetchval("""
                SELECT COUNT(*) FROM qnh_products p
                WHERE status = '在售' AND retail_price > 100
                AND retail_price > (
                    SELECT AVG(retail_price) * 1.2
                    FROM qnh_products
                    WHERE status = '在售' AND category = p.category AND retail_price > 0
                )
            """)
                or 0
            )

            if overpriced_count > 0:
                action_items.append(
                    ActionItem(
                        priority="medium",
                        action="调整定价",
                        detail=f"{overpriced_count}款商品价格高于同类均价20%以上",
                        link="/pricing",
                    )
                )

        # 3. Check performance metrics from dataset records (priority) or raw data
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
                        link="/logistics",
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
                        link="/inventory/alerts",
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
                            link="/logistics",
                        )
                    )
                stockout_loss = _extract_metric(metrics, "stockout_loss_amt")
                if stockout_loss > 1000:
                    action_items.append(
                        ActionItem(
                            priority="high",
                            action="减少缺货损失",
                            detail=f"缺货损失¥{stockout_loss:.2f}，优化库存预警",
                            link="/inventory/alerts",
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
                            link="/products/optimize",
                        )
                    )

        # 4. Check for category concentration (low priority)
        with contextlib.suppress(Exception):
            top_category = await pool.fetchrow("""
                SELECT category, COUNT(*) as cnt,
                       COUNT(*) * 100 / (SELECT COUNT(*) FROM qnh_products WHERE status = '在售') as percentage
                FROM qnh_products
                WHERE status = '在售' AND category != ''
                GROUP BY category
                ORDER BY cnt DESC
                LIMIT 1
            """)

            if top_category and top_category["percentage"] > 40:
                action_items.append(
                    ActionItem(
                        priority="low",
                        action="丰富品类",
                        detail=f"「{top_category['category']}」占比{top_category['percentage']:.0f}%过高，建议增加其他品类",
                        link="/products/categories",
                    )
                )

        # 5. Generate growth opportunities (low priority)
        total_products = (
            await pool.fetchval("SELECT COUNT(*) FROM qnh_products WHERE status = '在售'") or 0
        )
        if total_products < 50:
            action_items.append(
                ActionItem(
                    priority="low",
                    action="扩充商品",
                    detail=f"当前在售{total_products}款商品，建议增加商品丰富度",
                    link="/products/selection",
                )
            )

        # Sort by priority (high -> medium -> low) and limit to top 5
        priority_order = {"high": 0, "medium": 1, "low": 2}
        action_items.sort(key=lambda x: priority_order.get(x.priority, 3))

        return action_items[:5]

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


@router.get("", response_model=APIResponse[DashboardOverview])
@router.get("/overview", response_model=APIResponse[DashboardOverview])
async def overview() -> APIResponse[DashboardOverview]:
    pool = pg.get_pool()
    total_products = await pool.fetchval("SELECT COUNT(*) FROM qnh_products") or 0

    today_orders = 0
    today_gmv = 0.0
    avg_order_value = 0.0
    total_customers = 0
    conversion_rate = 0.0

    # ── Priority 1: Read from qnh_dataset_records (store_rank aggregated) ──
    store_records = await _get_dataset_records(pool, "store_rank")
    if store_records:
        for rec in store_records:
            today_orders += int(_parse_data_value(rec.get("eff_ord_cnt")))
            today_gmv += _parse_data_value(rec.get("sale_amt_gmv"))
            total_customers += int(_parse_data_value(rec.get("user_cnt")))
        if today_orders > 0 and today_gmv > 0:
            avg_order_value = today_gmv / today_orders

    # ── Fallback: old raw metrics table ──
    if today_orders == 0:
        with contextlib.suppress(Exception):
            today_orders = (
                await pool.fetchval(
                    "SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE"
                )
                or 0
            )
        metrics = await _get_latest_metrics(pool)
        if metrics:
            if today_orders == 0:
                today_orders = int(_extract_metric(metrics, "eff_ord_cnt"))
            today_gmv = _extract_metric(metrics, "sale_amt_gmv")
            if today_gmv == 0:
                today_gmv = _extract_metric(metrics, "actual_pay_amt")
            total_customers = int(_extract_metric(metrics, "user_cnt"))
            avg_order_value = _extract_metric(metrics, "unit_price")
            if avg_order_value == 0 and today_orders > 0 and today_gmv > 0:
                avg_order_value = today_gmv / today_orders
            expose_cnt = _extract_metric(metrics, "expose_cnt")
            if expose_cnt > 0 and today_orders > 0:
                conversion_rate = round(today_orders / expose_cnt * 100, 2)

    # Fast alert count estimate (avoid expensive full alert generation in overview)
    pending_alerts = 0
    with contextlib.suppress(Exception):
        # Count low-stock products as proxy for alert count
        low_stock = (
            await pool.fetchval(
                "SELECT COUNT(*) FROM qnh_products WHERE status = '在售' AND stock_num IS NOT NULL AND stock_num < 10"
            )
            or 0
        )
        pending_alerts += low_stock
    # Add store_rank based alerts
    if store_records:
        for rec in store_records:
            if _parse_data_value(rec.get("stockout_loss_amt")) > 0:
                pending_alerts += 1
            ot = _parse_data_value(rec.get("overtime_ord_rate"))
            if ot > 5:
                pending_alerts += 1

    pending_tasks = 0
    for q in [
        "SELECT COUNT(*) FROM selection_runs WHERE status = 'running'",
        "SELECT COUNT(*) FROM bundle_tasks WHERE status = 'running'",
        "SELECT COUNT(*) FROM listings WHERE status = 'processing'",
    ]:
        with contextlib.suppress(Exception):
            pending_tasks += await pool.fetchval(q) or 0

    # Generate action items
    # Timeout action_items generation to prevent overview from hanging
    import asyncio

    try:
        action_items = await asyncio.wait_for(_generate_action_items(pool), timeout=10.0)
    except TimeoutError:
        logger.warning("action_items generation timed out")
        action_items = []

    from decimal import Decimal

    return APIResponse(
        data=DashboardOverview(
            total_products=total_products,
            today_orders=today_orders,
            today_gmv=Decimal(str(round(today_gmv, 2))),
            avg_order_value=Decimal(str(round(avg_order_value, 2))),
            total_customers=total_customers,
            conversion_rate=conversion_rate,
            pending_alerts=pending_alerts,
            pending_tasks=pending_tasks,
            action_items=action_items,
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


@router.get("/top-products", response_model=APIResponse[list[TopProduct]])
async def top_products() -> APIResponse[list[TopProduct]]:
    pool = pg.get_pool()

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
                SELECT spu_id AS product_id, name,
                       COALESCE(retail_price, 0)::numeric AS revenue,
                       1 AS total_sales
                FROM qnh_products
                WHERE status = '在售' AND name != '' AND retail_price IS NOT NULL
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


@router.get("/store-kpis")
async def store_kpis() -> dict:
    """Return parsed store KPIs from dataset records or raw metrics."""
    pool = pg.get_pool()

    # ── Priority 1: Aggregate from qnh_dataset_records (store_rank) ──
    store_records = await _get_dataset_records(pool, "store_rank")
    if store_records:
        # Aggregate across all stores
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
        # Percentage-based fields: take weighted average, not sum
        pct_keys = {"overtime_ord_rate", "stockout_refund_rate"}

        for key in kpi_keys:
            agg[key] = sum(_parse_data_value(rec.get(key)) for rec in store_records)
        for key in pct_keys:
            vals = [_parse_data_value(rec.get(key)) for rec in store_records]
            agg[key] = sum(vals) / len(vals) if vals else 0.0
        # Avg order value = GMV / orders (not sum)
        if agg["eff_ord_cnt"] > 0:
            agg["unit_price"] = agg["sale_amt_gmv"] / agg["eff_ord_cnt"]
            agg["actual_unit_price"] = agg["actual_pay_amt"] / agg["eff_ord_cnt"]

        return {
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

    # ── Fallback: old raw metrics ──
    metrics = await _get_latest_metrics(pool)
    if not metrics:
        return {"error": "no metrics data"}

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
        "overtime_ord_rate",
        "stockout_refund_rate",
        "stockout_loss_amt",
    ]:
        kpis[key] = _extract_metric(metrics, key)

    return {
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


@router.get("/trends", response_model=APIResponse[list[dict]])
async def sales_trends(
    days: int = 7,
) -> APIResponse[list[dict]]:
    """查询近 N 天销售趋势（从 orders 表）"""
    pool = pg.get_pool()
    try:
        rows = []
        with contextlib.suppress(Exception):
            rows = await pool.fetch(
                """
                SELECT
                    DATE(order_time) AS date,
                    COUNT(*) AS order_count,
                    COALESCE(SUM(total_amount), 0) AS revenue,
                    COALESCE(AVG(total_amount), 0) AS avg_order_value
                FROM orders
                WHERE order_time >= CURRENT_DATE - ($1 - 1) * INTERVAL '1 day'
                GROUP BY DATE(order_time)
                ORDER BY date
                """,
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
