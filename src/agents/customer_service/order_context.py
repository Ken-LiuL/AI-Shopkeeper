"""
订单上下文查询模块

提供订单状态、物流信息查询，用于在对话中自动注入订单上下文。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 订单号正则：10-20位数字
ORDER_ID_PATTERN = re.compile(r"\b(\d{10,20})\b")


def extract_order_ids(text: str) -> list[str]:
    """从文本中提取订单号"""
    return ORDER_ID_PATTERN.findall(text)


def has_order_mention(text: str) -> bool:
    """判断文本是否提到订单相关关键词"""
    order_keywords = ["我的订单", "订单号", "订单状态", "查订单", "发货", "物流", "快递", "配送", "退款", "换货"]
    if extract_order_ids(text):
        return True
    return any(kw in text for kw in order_keywords)


async def get_customer_orders(
    pool,
    customer_id: str | None = None,
    phone: str | None = None,
    session_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """查询客户最近的订单

    Args:
        pool: 数据库连接池
        customer_id: 客户ID
        phone: 手机号
        session_id: 会话ID（用于关联）
        limit: 返回数量

    Returns:
        订单列表，每项包含 order_id, status, items, total, created_at, logistics_status
    """
    if not pool:
        return []

    results = []

    # 尝试从多个可能的订单表查询
    tables_to_try = [
        # (表名, customer_id列, phone列, order_id列, status列, amount列, created_at列)
        ("qnh_orders_raw", "buyer_id", "receiver_mobile", "order_id", "order_status", "actual_amount", "order_time"),
        ("orders", "customer_id", "phone", "id", "status", "total_amount", "created_at"),
    ]

    for (table, cid_col, phone_col, oid_col, status_col, amount_col, time_col) in tables_to_try:
        try:
            conditions = []
            params = []
            idx = 1

            if customer_id:
                conditions.append(f"{cid_col} = ${idx}")
                params.append(customer_id)
                idx += 1
            if phone:
                conditions.append(f"{phone_col} = ${idx}")
                params.append(phone)
                idx += 1

            if not conditions:
                # 无查询条件时跳过
                continue

            where_clause = " OR ".join(conditions)
            query = f"""
                SELECT {oid_col} AS order_id,
                       {status_col} AS status,
                       {amount_col} AS total,
                       {time_col} AS created_at
                FROM {table}
                WHERE {where_clause}
                ORDER BY {time_col} DESC
                LIMIT ${idx}
            """
            params.append(limit)

            rows = await pool.fetch(query, *params)
            for row in rows:
                results.append({
                    "order_id": str(row["order_id"] or ""),
                    "status": str(row["status"] or ""),
                    "total": float(row["total"] or 0),
                    "created_at": str(row["created_at"] or ""),
                    "logistics_status": "",  # 物流状态单独查询
                    "items": [],
                })

            if results:
                logger.info(f"[OrderCtx] Found {len(results)} orders from {table}")
                break

        except Exception as e:
            logger.debug(f"[OrderCtx] Table {table} query failed (graceful): {e}")
            continue

    return results[:limit]


async def get_order_detail(pool, order_id: str) -> dict | None:
    """查询单个订单详情

    Args:
        pool: 数据库连接池
        order_id: 订单号

    Returns:
        订单详情字典，包含商品列表、收货地址、状态等；未找到返回 None
    """
    if not pool or not order_id:
        return None

    tables_to_try = [
        ("qnh_orders_raw", "order_id"),
        ("orders", "id"),
    ]

    for (table, id_col) in tables_to_try:
        try:
            row = await pool.fetchrow(
                f"SELECT * FROM {table} WHERE {id_col} = $1 LIMIT 1",
                order_id,
            )
            if row:
                data = dict(row)
                # 标准化字段名
                result = {
                    "order_id": order_id,
                    "status": str(data.get("order_status") or data.get("status") or ""),
                    "total": float(data.get("actual_amount") or data.get("total_amount") or 0),
                    "created_at": str(data.get("order_time") or data.get("created_at") or ""),
                    "receiver_name": str(data.get("receiver_name") or data.get("recipient_name") or ""),
                    "receiver_address": str(data.get("receiver_address") or data.get("address") or ""),
                    "items": [],
                    "raw": {k: str(v) for k, v in data.items() if v is not None},
                }
                logger.info(f"[OrderCtx] Order {order_id} found in {table}")
                return result
        except Exception as e:
            logger.debug(f"[OrderCtx] Order detail query failed for {table}: {e}")
            continue

    logger.debug(f"[OrderCtx] Order {order_id} not found in any table")
    return None


async def get_order_logistics(pool, order_id: str) -> dict | None:
    """查询订单物流状态

    Args:
        pool: 数据库连接池
        order_id: 订单号

    Returns:
        物流信息字典；未找到返回 None
    """
    if not pool or not order_id:
        return None

    logistics_tables = [
        ("logistics", "order_id"),
        ("qnh_logistics", "order_id"),
        ("order_logistics", "order_id"),
    ]

    for (table, id_col) in logistics_tables:
        try:
            row = await pool.fetchrow(
                f"SELECT * FROM {table} WHERE {id_col} = $1 ORDER BY updated_at DESC LIMIT 1",
                order_id,
            )
            if row:
                data = dict(row)
                result = {
                    "order_id": order_id,
                    "carrier": str(data.get("carrier") or data.get("express_company") or ""),
                    "tracking_no": str(data.get("tracking_no") or data.get("waybill_no") or ""),
                    "status": str(data.get("status") or data.get("logistics_status") or ""),
                    "last_update": str(data.get("updated_at") or data.get("last_track_time") or ""),
                    "estimated_delivery": str(data.get("estimated_delivery") or ""),
                    "location": str(data.get("current_location") or data.get("location") or ""),
                }
                logger.info(f"[OrderCtx] Logistics for {order_id} found in {table}")
                return result
        except Exception as e:
            logger.debug(f"[OrderCtx] Logistics query failed for {table}: {e}")
            continue

    # Fallback: 尝试从订单表中读取内嵌物流字段
    try:
        for (table, id_col) in [("qnh_orders_raw", "order_id"), ("orders", "id")]:
            try:
                row = await pool.fetchrow(
                    f"SELECT * FROM {table} WHERE {id_col} = $1 LIMIT 1",
                    order_id,
                )
                if row:
                    data = dict(row)
                    # 检查是否有物流相关字段
                    carrier = data.get("express_company") or data.get("carrier") or ""
                    tracking = data.get("waybill_no") or data.get("tracking_no") or ""
                    status = data.get("logistics_status") or data.get("delivery_status") or ""
                    if carrier or tracking or status:
                        return {
                            "order_id": order_id,
                            "carrier": str(carrier),
                            "tracking_no": str(tracking),
                            "status": str(status),
                            "last_update": "",
                            "estimated_delivery": "",
                            "location": "",
                        }
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[OrderCtx] Fallback logistics query failed: {e}")

    return None


async def build_order_context_str(
    pool,
    message: str,
    customer_id: str | None = None,
    phone: str | None = None,
) -> str:
    """构建注入 prompt 的订单上下文字符串

    Args:
        pool: 数据库连接池
        message: 用户消息（用于提取订单号）
        customer_id: 客户ID
        phone: 手机号

    Returns:
        格式化的订单上下文字符串（空字符串表示无相关信息）
    """
    if not pool:
        return ""

    context_parts = []

    # 1. 从消息中提取订单号，查询具体订单
    order_ids = extract_order_ids(message)
    for order_id in order_ids[:2]:  # 最多查2个
        detail = await get_order_detail(pool, order_id)
        if detail:
            context_parts.append(
                f"订单 {order_id}：状态={detail['status']}，"
                f"金额=¥{detail['total']:.2f}，"
                f"下单时间={detail['created_at']}"
            )
            # 尝试获取物流
            logistics = await get_order_logistics(pool, order_id)
            if logistics and (logistics.get("status") or logistics.get("carrier")):
                context_parts.append(
                    f"  物流：{logistics.get('carrier', '')} {logistics.get('tracking_no', '')} "
                    f"状态={logistics.get('status', '')} 位置={logistics.get('location', '')}"
                )

    # 2. 如果没有具体订单号但提到订单相关，查询最近订单
    if not order_ids and has_order_mention(message) and (customer_id or phone):
        recent_orders = await get_customer_orders(
            pool, customer_id=customer_id, phone=phone, limit=3
        )
        if recent_orders:
            context_parts.append(f"客户最近订单（共{len(recent_orders)}条）：")
            for o in recent_orders[:3]:
                context_parts.append(
                    f"  - 订单{o['order_id']}：{o['status']}，¥{o['total']:.2f}，{o['created_at']}"
                )

    if not context_parts:
        return ""

    return "【订单上下文】\n" + "\n".join(context_parts)
