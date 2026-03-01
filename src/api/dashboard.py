"""Dashboard API routes — reads from both structured and raw sync tables."""

from __future__ import annotations

import contextlib
import json
import logging

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import ActionItem, APIResponse, DashboardOverview, SalesTrendPoint, TopProduct

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


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
        low_stock_count = (
            await pool.fetchval("""
            SELECT COUNT(*) FROM qnh_products
            WHERE status = '在售' AND stock_num IS NOT NULL AND stock_num < 10
        """)
            or 0
        )

        if low_stock_count > 0:
            # Get sample product names
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
                    priority="high", action="紧急补货", detail=detail, link="/inventory/restock"
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

        # 3. Check performance metrics from raw data
        metrics = await _get_latest_metrics(pool)
        if metrics:
            # Check overtime rate
            overtime_rate = _extract_metric(metrics, "overtime_ord_rate")
            if overtime_rate > 0.2:  # > 20%
                action_items.append(
                    ActionItem(
                        priority="high",
                        action="优化配送",
                        detail=f"超时订单率{overtime_rate * 100:.1f}%，影响客户满意度",
                        link="/logistics",
                    )
                )
            elif overtime_rate > 0.05:  # > 5%
                action_items.append(
                    ActionItem(
                        priority="medium",
                        action="关注超时率",
                        detail=f"超时订单率{overtime_rate * 100:.1f}%，建议优化配送",
                        link="/alerts",
                    )
                )

            # Check stockout losses
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

            # Check conversion rate
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
    with contextlib.suppress(Exception):
        today_orders = (
            await pool.fetchval("SELECT COUNT(*) FROM orders WHERE order_time::date = CURRENT_DATE")
            or 0
        )

    # Extract GMV / orders from raw metrics
    today_gmv = 0.0
    avg_order_value = 0.0
    total_customers = 0
    conversion_rate = 0.0
    metrics = await _get_latest_metrics(pool)
    if metrics:
        if today_orders == 0:
            today_orders = int(_extract_metric(metrics, "eff_ord_cnt"))
        today_gmv = _extract_metric(metrics, "sale_amt_gmv")
        if today_gmv == 0:
            today_gmv = _extract_metric(metrics, "actual_pay_amt")
        total_customers = int(_extract_metric(metrics, "user_cnt"))
        # Unit price from raw metric directly
        avg_order_value = _extract_metric(metrics, "unit_price")
        if avg_order_value == 0 and today_orders > 0 and today_gmv > 0:
            avg_order_value = today_gmv / today_orders
        # Conversion
        expose_cnt = _extract_metric(metrics, "expose_cnt")
        if expose_cnt > 0 and today_orders > 0:
            conversion_rate = round(today_orders / expose_cnt * 100, 2)

    # Get pending alerts count dynamically
    pending_alerts = 0
    with contextlib.suppress(Exception):
        from .alerts import _generate_smart_alerts

        smart_alerts = await _generate_smart_alerts(pool)
        pending_alerts = len([a for a in smart_alerts if a.get("status") == "pending"])

    pending_tasks = 0
    for q in [
        "SELECT COUNT(*) FROM selection_runs WHERE status = 'running'",
        "SELECT COUNT(*) FROM bundle_tasks WHERE status = 'running'",
        "SELECT COUNT(*) FROM listings WHERE status = 'processing'",
    ]:
        with contextlib.suppress(Exception):
            pending_tasks += await pool.fetchval(q) or 0

    # Generate action items
    action_items = await _generate_action_items(pool)

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

    # Try to get 30 days of data from structured sales_history first
    rows = []
    with contextlib.suppress(Exception):
        rows = await pool.fetch(
            """SELECT sale_date AS date, SUM(quantity)::int AS quantity, SUM(revenue) AS revenue
               FROM sales_history
               WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY sale_date ORDER BY sale_date"""
        )

    # Fallback: aggregate from raw metrics per day
    if not rows:
        with contextlib.suppress(Exception):
            raw_rows = await pool.fetch("""
                SELECT DISTINCT ON (created_at::date)
                       created_at::date AS date,
                       raw_data
                FROM qnh_store_metrics_raw
                WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY created_at::date, created_at DESC
            """)

            for r in raw_rows:
                d = str(r["date"])
                data = r["raw_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                orders = int(_extract_metric(data, "eff_ord_cnt"))
                revenue = _extract_metric(data, "sale_amt_gmv")
                rows.append({"date": d, "quantity": orders, "revenue": revenue})
            rows = sorted(rows, key=lambda x: x["date"])

    # If we still have insufficient data (< 7 days), simulate reasonable trend
    result_points = []

    if len(rows) < 7:
        from datetime import date, timedelta

        # Use existing data as baseline
        if rows:
            avg_orders = sum(r["quantity"] for r in rows) / len(rows)
            avg_revenue = sum(r["revenue"] for r in rows) / len(rows)
        else:
            # Get current day metrics as baseline
            metrics = await _get_latest_metrics(pool)
            avg_orders = _extract_metric(metrics, "eff_ord_cnt") if metrics else 10
            avg_revenue = _extract_metric(metrics, "sale_amt_gmv") if metrics else 500

        # Generate 30 days of simulated trend data
        import random

        for i in range(29, -1, -1):  # 30 days ago to today
            target_date = date.today() - timedelta(days=i)
            date_str = target_date.isoformat()

            # Check if we have real data for this date
            existing = next((r for r in rows if r["date"] == date_str), None)
            if existing:
                result_points.append(
                    SalesTrendPoint(
                        date=date_str,
                        quantity=existing["quantity"],
                        revenue=float(existing["revenue"]),
                        simulated=False,
                    )
                )
            else:
                # Generate simulated data with some variance
                variance = 0.3  # 30% variance
                sim_orders = max(0, int(avg_orders * (1 + random.uniform(-variance, variance))))
                sim_revenue = max(0, avg_revenue * (1 + random.uniform(-variance, variance)))

                result_points.append(
                    SalesTrendPoint(
                        date=date_str, quantity=sim_orders, revenue=sim_revenue, simulated=True
                    )
                )
    else:
        # We have sufficient real data
        result_points = [
            SalesTrendPoint(
                date=str(r["date"]),
                quantity=r["quantity"],
                revenue=float(r["revenue"]),
                simulated=False,
            )
            for r in rows
        ]

    # Calculate growth rates (day-over-day)
    for i in range(1, len(result_points)):
        prev_revenue = result_points[i - 1].revenue
        curr_revenue = result_points[i].revenue

        if prev_revenue > 0:
            growth_rate = ((curr_revenue - prev_revenue) / prev_revenue) * 100
            result_points[i].growth_rate = round(growth_rate, 2)
        else:
            result_points[i].growth_rate = 0.0

    return APIResponse(data=result_points)


@router.get("/top-products", response_model=APIResponse[list[TopProduct]])
async def top_products() -> APIResponse[list[TopProduct]]:
    pool = pg.get_pool()

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
    """Return parsed store KPIs from raw metrics."""
    pool = pg.get_pool()
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
        val = _extract_metric(metrics, key)
        kpis[key] = val

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
