"""Order analysis API routes."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query

from src.db import postgres as pg

from .errors import NotFoundError
from .schemas import APIResponse, PaginatedResponse

router = APIRouter(prefix="/api/orders", tags=["orders"])
logger = logging.getLogger(__name__)
_DATA_VALUE_CLEAN = re.compile(r"[,%\s]")


def _extract_metric(raw_data: dict, key: str, use_reference: bool = True) -> float:
    """Extract metric value from complex goldengateway JSON.
    Same function as in dashboard.py to ensure consistency.
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


def _parse_rank_value(field) -> float:
    """Parse dataValue style numbers from dataset payloads."""
    if field is None:
        return 0.0
    if isinstance(field, int | float):
        return float(field)
    if isinstance(field, dict):
        raw = field.get("dataValue") or field.get("value") or ""
    else:
        raw = str(field)
    if not raw:
        return 0.0
    cleaned = _DATA_VALUE_CLEAN.sub("", str(raw))
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_rank_str(field) -> str:
    """Extract string dataValue."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field.strip()
    if isinstance(field, dict):
        val = field.get("dataValue") or field.get("dataName") or ""
        return str(val).strip()
    return str(field).strip()


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


async def _extract_orders_from_raw(raw_data: dict) -> list[dict]:
    """从qnh_orders_raw的JSONB数据中提取订单信息"""
    orders = []

    # 处理不同的raw_data结构
    if isinstance(raw_data, dict):
        # 如果有orders数组
        if "orders" in raw_data and isinstance(raw_data["orders"], list):
            for order in raw_data["orders"]:
                orders.append(_normalize_order(order))
        # 如果直接是单个订单
        elif "orderId" in raw_data or "order_id" in raw_data:
            orders.append(_normalize_order(raw_data))

    return orders


def _normalize_order(order_data: dict) -> dict:
    """标准化订单数据格式"""
    return {
        "order_id": order_data.get("orderId") or order_data.get("order_id") or order_data.get("id"),
        "order_time": order_data.get("orderTime")
        or order_data.get("order_time")
        or order_data.get("created_at"),
        "total_amount": float(
            order_data.get("totalAmount")
            or order_data.get("total_amount")
            or order_data.get("amount")
            or 0
        ),
        "status": order_data.get("status") or order_data.get("orderStatus") or "unknown",
        "customer_id": order_data.get("customerId")
        or order_data.get("customer_id")
        or order_data.get("userId"),
        "delivery_time": order_data.get("deliveryTime") or order_data.get("delivery_time"),
        "items": order_data.get("items", []),
        "payment_method": order_data.get("paymentMethod") or order_data.get("payment_method"),
        "delivery_address": order_data.get("deliveryAddress") or order_data.get("delivery_address"),
    }


@router.get("/list", response_model=PaginatedResponse[dict])
async def list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query("all"),
    store_id: str = Query(None, description="按门店 ID 过滤"),
    date: str | None = Query(None, description="按下单日期过滤 YYYY-MM-DD"),
) -> PaginatedResponse[dict]:
    """订单列表 — 优先从 orders 表查真实美团订单"""
    pool = pg.get_pool()
    offset = (page - 1) * limit

    try:
        # 优先从 orders 表查真实订单 (美团 syncer 写入)
        real_orders = []
        try:
            conditions = ["order_id IS NOT NULL"]
            params: list = []
            idx = 1

            if store_id:
                conditions.append(f"store_id = ${idx}")
                params.append(store_id)
                idx += 1

            if date:
                conditions.append(f"order_time::date = ${idx}::date")
                params.append(date)
                idx += 1

            if status and status != "all":
                conditions.append(f"status = ${idx}")
                params.append(status)
                idx += 1

            where = " AND ".join(conditions)

            total_real = await pool.fetchval(
                f"SELECT COUNT(*) FROM orders WHERE {where} AND customer_paid IS NOT NULL",
                *params,
            ) or 0

            if total_real > 0:
                rows = await pool.fetch(
                    f"""SELECT order_id, store_id, customer_name, total_amount,
                               customer_paid, status, order_time, order_date,
                               commission, delivery_fee, merchant_discount,
                               day_seq, items, created_at
                        FROM orders
                        WHERE {where} AND customer_paid IS NOT NULL
                        ORDER BY order_time DESC
                        LIMIT ${idx} OFFSET ${idx + 1}""",
                    *params, limit, offset,
                )
                for r in rows:
                    order_dict = dict(r)
                    # 解析 items JSONB
                    items_data = order_dict.get("items")
                    if isinstance(items_data, str):
                        items_data = json.loads(items_data)
                    products = items_data.get("products", []) if isinstance(items_data, dict) else []
                    order_dict["items"] = products
                    primary_name = "—"
                    if products:
                        first_name = str(products[0].get("product_name") or products[0].get("name") or "未命名商品")
                        primary_name = first_name if len(products) == 1 else f"{first_name} 等{len(products)}件"
                    order_dict["product_name"] = primary_name
                    order_dict["amount"] = float(order_dict.get("customer_paid") or order_dict.get("total_amount") or 0)
                    order_dict["created_at"] = (
                        order_dict.get("order_time").isoformat()
                        if getattr(order_dict.get("order_time"), "isoformat", None)
                        else order_dict.get("order_time")
                    )
                    order_dict["synthetic"] = False
                    order_dict["source"] = "meituan_yiyao"
                    real_orders.append(order_dict)

                return PaginatedResponse(
                    data=real_orders, total=total_real, page=page, page_size=limit,
                )
        except Exception as exc:
            logger.exception("Real orders query failed, falling back: %s", exc)

        logger.info(
            "No verified imported orders found in orders table; returning empty result instead of synthetic data"
        )
        return PaginatedResponse(data=[], total=0, page=page, page_size=limit)

    except Exception as e:
        logger.error(f"Failed to fetch orders: {e}")
        return PaginatedResponse(data=[], total=0, page=page, page_size=limit)


async def _count_orders_raw(pool, status: str) -> int:
    """统计raw表中的订单总数"""
    try:
        rows = await pool.fetch("SELECT raw_data FROM qnh_orders_raw")
        count = 0
        for row in rows:
            raw_data = row["raw_data"]
            if isinstance(raw_data, str):
                raw_data = json.loads(raw_data)
            orders = await _extract_orders_from_raw(raw_data)
            if status == "all":
                count += len(orders)
            else:
                count += len([o for o in orders if o.get("status") == status])
        return count
    except Exception:
        return 0


@router.get("/stats", response_model=APIResponse[dict])
async def order_stats() -> APIResponse[dict]:
    """今日/本周/本月订单统计（从qnh_store_metrics_raw获取，与dashboard保持一致）"""
    pool = pg.get_pool()

    try:
        with contextlib.suppress(Exception):
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE order_time::date = CURRENT_DATE)::int AS today_orders,
                    COUNT(*)::int AS month_orders,
                    COUNT(*) FILTER (
                        WHERE order_time::date = CURRENT_DATE AND status = 'completed'
                    )::int AS today_completed_orders,
                    COUNT(*) FILTER (
                        WHERE order_time::date = CURRENT_DATE AND status IN ('refunded', 'cancelled')
                    )::int AS today_refunded_orders,
                    COUNT(*) FILTER (WHERE status = 'completed')::int AS month_completed_orders,
                    COUNT(*) FILTER (WHERE status IN ('refunded', 'cancelled'))::int AS month_refunded_orders
                FROM orders
                WHERE order_time >= CURRENT_DATE - INTERVAL '30 days'
                """
            )
            if row and int(row["month_orders"] or 0) > 0:
                month_orders = int(row["month_orders"] or 0)
                month_completed_orders = int(row["month_completed_orders"] or 0)
                month_refunded_orders = int(row["month_refunded_orders"] or 0)
                completion_rate = round(month_completed_orders / max(month_orders, 1) * 100, 2)
                refund_rate = round(month_refunded_orders / max(month_orders, 1) * 100, 2)
                avg_delivery_time = 0.0
                return APIResponse(
                    data={
                        "today_orders": int(row["today_orders"] or 0),
                        "completion_rate": completion_rate,
                        "refund_rate": refund_rate,
                        "avg_delivery_time": avg_delivery_time,
                        "today": {
                            "total": int(row["today_orders"] or 0),
                            "completed": int(row["today_completed_orders"] or 0),
                            "refunded": int(row["today_refunded_orders"] or 0),
                            "completion_rate": round(
                                int(row["today_completed_orders"] or 0) / max(int(row["today_orders"] or 0), 1) * 100,
                                2,
                            ),
                            "refund_rate": round(
                                int(row["today_refunded_orders"] or 0) / max(int(row["today_orders"] or 0), 1) * 100,
                                2,
                            ),
                            "avg_delivery_time": avg_delivery_time,
                        },
                    }
                )

        # 从metrics表获取最新数据（与dashboard一致）
        metrics = await _get_latest_metrics(pool)
        if not metrics:
            return APIResponse(
                data={
                    "today_orders": 0,
                    "completion_rate": 0,
                    "refund_rate": 0,
                    "avg_delivery_time": 0,
                    "today": {
                        "total": 0,
                        "completed": 0,
                        "refunded": 0,
                        "completion_rate": 0,
                        "refund_rate": 0,
                        "avg_delivery_time": 0,
                    },
                    "this_week": {
                        "total": 0,
                        "completed": 0,
                        "refunded": 0,
                        "completion_rate": 0,
                        "refund_rate": 0,
                        "avg_delivery_time": 0,
                    },
                    "this_month": {
                        "total": 0,
                        "completed": 0,
                        "refunded": 0,
                        "completion_rate": 0,
                        "refund_rate": 0,
                        "avg_delivery_time": 0,
                    },
                    "total_amount": {"today": 0, "this_week": 0, "this_month": 0},
                }
            )

        # 提取关键指标（与dashboard._extract_metric逻辑一致）
        today_orders = int(_extract_metric(metrics, "eff_ord_cnt"))
        today_gmv = _extract_metric(metrics, "sale_amt_gmv")
        if today_gmv == 0:
            today_gmv = _extract_metric(metrics, "actual_pay_amt")

        avg_order_value = _extract_metric(metrics, "unit_price")
        if avg_order_value == 0 and today_orders > 0 and today_gmv > 0:
            avg_order_value = today_gmv / today_orders

        # 估算完成率和退单率（基于常见指标）
        completion_rate = 85.0  # 默认估算值
        refund_rate = _extract_metric(metrics, "stockout_refund_rate") or 8.0
        avg_delivery_time = 2.5  # 默认配送时间（天）

        # 今日数据（主要来源）
        today_stats = {
            "total": today_orders,
            "completed": int(today_orders * completion_rate / 100),
            "refunded": int(today_orders * refund_rate / 100),
            "completion_rate": round(completion_rate, 2),
            "refund_rate": round(refund_rate, 2),
            "avg_delivery_time": round(avg_delivery_time, 2),
        }

        # 本周估算（今日数据 × 7）
        week_orders = today_orders * 7
        week_gmv = today_gmv * 7
        week_stats = {
            "total": week_orders,
            "completed": int(week_orders * completion_rate / 100),
            "refunded": int(week_orders * refund_rate / 100),
            "completion_rate": round(completion_rate, 2),
            "refund_rate": round(refund_rate, 2),
            "avg_delivery_time": round(avg_delivery_time, 2),
        }

        # 本月估算（今日数据 × 30）
        month_orders = today_orders * 30
        month_gmv = today_gmv * 30
        month_stats = {
            "total": month_orders,
            "completed": int(month_orders * completion_rate / 100),
            "refunded": int(month_orders * refund_rate / 100),
            "completion_rate": round(completion_rate, 2),
            "refund_rate": round(refund_rate, 2),
            "avg_delivery_time": round(avg_delivery_time, 2),
        }

        stats = {
            "today_orders": today_orders,
            "completion_rate": round(completion_rate, 2),
            "refund_rate": round(refund_rate, 2),
            "avg_delivery_time": round(avg_delivery_time, 2),
            "today": today_stats,
            "this_week": week_stats,
            "this_month": month_stats,
            "total_amount": {
                "today": round(today_gmv, 2),
                "this_week": round(week_gmv, 2),
                "this_month": round(month_gmv, 2),
            },
        }

        return APIResponse(data=stats)

    except Exception as e:
        logger.error(f"Failed to calculate order stats: {e}")
        return APIResponse(success=False, message=f"Failed to calculate stats: {str(e)}", data={})


# Debug endpoint for data structure analysis
# UNUSED: no frontend caller
@router.get("/debug-raw")
async def debug_raw():
    """Debug endpoint to check raw data structure"""
    from fastapi import HTTPException

    pool = pg.get_pool()
    try:
        orders_rows = await pool.fetch("SELECT raw_data FROM qnh_orders_raw LIMIT 3")
        metrics_rows = await pool.fetch("SELECT raw_data FROM qnh_store_metrics_raw LIMIT 3")
        metrics = await _get_latest_metrics(pool)
    except Exception as exc:
        logger.error("debug-raw failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Debug query failed: {exc}") from exc

    test_extraction = {
        "eff_ord_cnt": _extract_metric(metrics, "eff_ord_cnt"),
        "sale_amt_gmv": _extract_metric(metrics, "sale_amt_gmv"),
        "unit_price": _extract_metric(metrics, "unit_price"),
        "user_cnt": _extract_metric(metrics, "user_cnt"),
    }

    return {
        "qnh_orders_raw": [dict(r) for r in orders_rows],
        "qnh_store_metrics_raw": [dict(r) for r in metrics_rows],
        "extracted_test": test_extraction,
        "raw_metrics": metrics,
    }


# UNUSED: no frontend caller
@router.get("/{order_id}", response_model=APIResponse[dict])
async def get_order(order_id: str) -> APIResponse[dict]:
    """获取订单详情"""
    pool = pg.get_pool()

    try:
        # 从raw表搜索订单
        rows = await pool.fetch(
            """SELECT raw_data, synced_at, created_at FROM qnh_orders_raw
               ORDER BY created_at DESC"""
        )

        for row in rows:
            raw_data = row["raw_data"]
            if isinstance(raw_data, str):
                raw_data = json.loads(raw_data)

            orders = await _extract_orders_from_raw(raw_data)
            for order in orders:
                if order.get("order_id") == order_id:
                    order["synced_at"] = row["synced_at"]
                    order["raw_created_at"] = row["created_at"]
                    return APIResponse(data=order)

        raise NotFoundError("Order", order_id)

    except NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to get order {order_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get order: {str(e)}") from e


# 保留原有API兼容性
# UNUSED: no frontend caller
@router.get("/recent", response_model=APIResponse[list[dict]])
async def recent_orders(
    limit: int = Query(10, ge=1, le=100),
) -> APIResponse[list[dict]]:
    """Get recent orders from raw data."""
    result = await list_orders(page=1, limit=limit)
    return APIResponse(data=result.data)


# UNUSED: no frontend caller
@router.get("/trend", response_model=APIResponse[list[dict]])
async def order_trend(
    days: int = Query(30, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|week|month)$"),
) -> APIResponse[list[dict]]:
    """Order trend grouped by day/week/month."""
    pool = pg.get_pool()

    try:
        rows = await pool.fetch(
            f"""SELECT raw_data, created_at FROM qnh_orders_raw
               WHERE created_at >= CURRENT_DATE - INTERVAL '{days} days'
               ORDER BY created_at"""
        )

        # 按日期分组统计
        from collections import defaultdict

        trend_data = defaultdict(lambda: {"order_count": 0, "total_amount": 0})

        for row in rows:
            raw_data = row["raw_data"]
            if isinstance(raw_data, str):
                raw_data = json.loads(raw_data)

            orders = await _extract_orders_from_raw(raw_data)
            date_key = row["created_at"].date()

            if granularity == "week":
                date_key = date_key - timedelta(days=date_key.weekday())
            elif granularity == "month":
                date_key = date_key.replace(day=1)

            trend_data[date_key]["order_count"] += len(orders)
            trend_data[date_key]["total_amount"] += sum([o.get("total_amount", 0) for o in orders])

        result = [
            {
                "period": str(date),
                "order_count": data["order_count"],
                "total_amount": data["total_amount"],
            }
            for date, data in sorted(trend_data.items())
        ]

        return APIResponse(data=result)

    except Exception as e:
        logger.error(f"Failed to get order trend: {e}")
        return APIResponse(success=False, message=str(e), data=[])


# UNUSED: no frontend caller
@router.get("/refunds", response_model=PaginatedResponse[dict])
async def list_refunds(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[dict]:
    """退单列表"""
    # 使用现有的list_orders但过滤退单状态
    result = await list_orders(page=page, limit=page_size, status="refunded")

    # 也包括cancelled状态
    cancelled_result = await list_orders(page=page, limit=page_size, status="cancelled")

    # 合并结果
    all_refunds = result.data + cancelled_result.data
    all_refunds = all_refunds[:page_size]  # 限制数量

    return PaginatedResponse(
        data=all_refunds, total=len(all_refunds), page=page, page_size=page_size
    )


# 兼容性API
# UNUSED: no frontend caller
@router.get("", response_model=PaginatedResponse[dict])
async def list_orders_compat(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    store_id: str | None = Query(None),
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
) -> PaginatedResponse[dict]:
    """兼容性API - 重定向到新的list接口"""
    return await list_orders(page=page, limit=page_size, status=status or "all", store_id=store_id)
