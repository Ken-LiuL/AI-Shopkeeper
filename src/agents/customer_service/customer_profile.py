"""
客户画像模块

查询并构建客户画像，用于对 VIP 客户提供差异化服务。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# VIP 门槛：累计消费金额（元）
VIP_THRESHOLD = 1000.0


async def get_customer_profile(
    pool,
    session_id: str | None = None,
    customer_id: str | None = None,
    phone: str | None = None,
) -> dict:
    """构建客户画像

    Args:
        pool: 数据库连接池
        session_id: 会话ID（可能关联客户）
        customer_id: 客户ID
        phone: 手机号

    Returns:
        客户画像字典，未查到时返回空画像（is_vip=False）
    """
    empty_profile: dict = {
        "total_orders": 0,
        "total_spent": 0.0,
        "last_order_date": None,
        "favorite_categories": [],
        "avg_order_value": 0.0,
        "is_vip": False,
        "complaint_history": 0,
        "satisfaction_score": None,
        "customer_id": customer_id,
        "found": False,
    }

    if not pool:
        return empty_profile

    profile = dict(empty_profile)

    # ── 1. 查询订单汇总 ────────────────────────────────────────────────
    order_tables = [
        ("qnh_orders_raw", "buyer_id", "receiver_mobile", "actual_amount", "order_time", "category_name"),
        ("orders", "customer_id", "phone", "total_amount", "created_at", "category"),
    ]

    for (table, cid_col, phone_col, amount_col, time_col, cat_col) in order_tables:
        try:
            conditions = []
            params: list = []
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
                continue

            where_clause = " OR ".join(f"({c})" for c in conditions)

            # 汇总统计
            summary = await pool.fetchrow(
                f"""
                SELECT COUNT(*)::int AS total_orders,
                       COALESCE(SUM({amount_col}), 0) AS total_spent,
                       MAX({time_col}) AS last_order_date,
                       CASE WHEN COUNT(*) > 0 THEN COALESCE(SUM({amount_col}), 0) / COUNT(*) ELSE 0 END AS avg_order_value
                FROM {table}
                WHERE {where_clause}
                """,
                *params,
            )

            if summary and summary["total_orders"] > 0:
                profile["total_orders"] = summary["total_orders"]
                profile["total_spent"] = float(summary["total_spent"] or 0)
                profile["last_order_date"] = str(summary["last_order_date"] or "")
                profile["avg_order_value"] = round(float(summary["avg_order_value"] or 0), 2)
                profile["is_vip"] = profile["total_spent"] >= VIP_THRESHOLD
                profile["found"] = True

                # 查询常买类目（Top 3）
                try:
                    cats = await pool.fetch(
                        f"""
                        SELECT {cat_col} AS cat, COUNT(*) AS cnt
                        FROM {table}
                        WHERE {where_clause} AND {cat_col} IS NOT NULL
                        GROUP BY {cat_col}
                        ORDER BY cnt DESC
                        LIMIT 3
                        """,
                        *params,
                    )
                    profile["favorite_categories"] = [
                        str(r["cat"]) for r in cats if r["cat"]
                    ]
                except Exception:
                    pass

                logger.info(
                    f"[Profile] Customer found in {table}: "
                    f"orders={profile['total_orders']}, "
                    f"spent=¥{profile['total_spent']:.2f}, "
                    f"vip={profile['is_vip']}"
                )
                break

        except Exception as e:
            logger.debug(f"[Profile] Table {table} query failed (graceful): {e}")
            continue

    # ── 2. 查询投诉历史 ────────────────────────────────────────────────
    if profile["found"] and (customer_id or phone):
        complaint_tables = [
            ("cs_conversation_log", "session_id", "intent"),
            ("complaint_records", "customer_id", "type"),
        ]
        for (table, cid_col, intent_col) in complaint_tables:
            try:
                conditions = []
                params2: list = []
                idx = 1
                if customer_id:
                    conditions.append(f"{cid_col} = ${idx}")
                    params2.append(customer_id)
                    idx += 1
                if not conditions:
                    continue

                row = await pool.fetchrow(
                    f"""
                    SELECT COUNT(*)::int AS cnt
                    FROM {table}
                    WHERE {" OR ".join(conditions)}
                      AND {intent_col} IN ('complaint', 'after_sales', '投诉')
                    """,
                    *params2,
                )
                if row:
                    profile["complaint_history"] = row["cnt"]
                    break
            except Exception:
                continue

    # ── 3. 查询历史满意度评分 ─────────────────────────────────────────
    if profile["found"] and (customer_id or session_id):
        score_tables = [
            ("cs_evaluation_log", "session_id", "overall_score"),
            ("satisfaction_scores", "customer_id", "score"),
        ]
        for (table, id_col, score_col) in score_tables:
            try:
                id_val = session_id or customer_id
                row = await pool.fetchrow(
                    f"""
                    SELECT AVG({score_col}) AS avg_score
                    FROM {table}
                    WHERE {id_col} = $1
                    """,
                    id_val,
                )
                if row and row["avg_score"] is not None:
                    profile["satisfaction_score"] = round(float(row["avg_score"]), 2)
                    break
            except Exception:
                continue

    return profile


def build_profile_context_str(profile: dict) -> str:
    """将客户画像格式化为注入 prompt 的字符串

    Args:
        profile: get_customer_profile() 返回的画像字典

    Returns:
        格式化的客户画像字符串（空字符串表示未知客户）
    """
    if not profile or not profile.get("found"):
        return ""

    lines = ["【客户画像】"]

    vip_tag = "⭐ VIP客户" if profile.get("is_vip") else "普通客户"
    lines.append(f"- 身份：{vip_tag}")
    lines.append(f"- 历史订单：{profile.get('total_orders', 0)}单，累计消费¥{profile.get('total_spent', 0):.2f}")

    if profile.get("avg_order_value"):
        lines.append(f"- 客单价：¥{profile['avg_order_value']:.2f}")

    if profile.get("last_order_date"):
        lines.append(f"- 最近下单：{profile['last_order_date']}")

    if profile.get("favorite_categories"):
        cats = "、".join(profile["favorite_categories"][:3])
        lines.append(f"- 偏好品类：{cats}")

    if profile.get("complaint_history", 0) > 0:
        lines.append(f"- 历史投诉：{profile['complaint_history']}次（需重点关注）")

    if profile.get("satisfaction_score") is not None:
        score = profile["satisfaction_score"]
        lines.append(f"- 历史满意度：{score:.2f}")

    # 服务指引
    if profile.get("is_vip"):
        lines.append("→ VIP客户，请给予优先、热情的服务，主动提供优惠方案")
    if profile.get("complaint_history", 0) >= 3:
        lines.append("→ 该客户有多次投诉记录，请特别谨慎处理，必要时转人工")

    return "\n".join(lines)
