"""智能定价引擎 — 基于真实销售数据 + 竞品价格的动态定价推荐。

核心能力：
1. 结合 hotsale_goods 真实销量识别高潜力商品
2. 对比竞品价格发现定价空间
3. 基于毛利率 + 销量弹性给出调价建议
4. 自动识别滞销品 + 爆品
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/pricing-intelligence", tags=["pricing-intelligence"])
logger = logging.getLogger(__name__)


def _pv(field) -> float:
    """Parse goldengateway dataValue field."""
    if field is None:
        return 0.0
    if isinstance(field, int | float):
        return float(field)
    if isinstance(field, dict):
        raw = field.get("dataValue", "")
    else:
        raw = str(field)
    if not raw:
        return 0.0
    cleaned = re.sub(r"[,%\s]", "", str(raw))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _sv(field) -> str:
    """Get string value from goldengateway field."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return str(field.get("dataValue", ""))
    return str(field)


class PricingInsight(BaseModel):
    product_name: str
    current_price: float
    suggested_price: float | None = None
    action: str  # "raise" | "lower" | "hold" | "promote"
    reason: str
    priority: str  # "high" | "medium" | "low"
    metrics: dict  # sales_volume, revenue, rank, margin_estimate etc.


class PricingReport(BaseModel):
    total_products_analyzed: int
    revenue_optimization_potential: float
    insights: list[PricingInsight]
    top_performers: list[dict]
    underperformers: list[dict]
    competitor_gaps: list[dict]


@router.get("/report", response_model=APIResponse[PricingReport])
async def pricing_report() -> APIResponse[PricingReport]:
    """生成完整的智能定价报告。"""
    pool = pg.get_pool()

    # 1. 获取热销商品真实数据
    hotsale_rows = await pool.fetch(
        "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
    )
    hotsale_data = []
    for row in hotsale_rows:
        p = row["payload"]
        if isinstance(p, str):
            p = json.loads(p)
        hotsale_data.append(
            {
                "name": _sv(p.get("product_name")),
                "rank": int(_pv(p.get("rank"))),
                "sales_amount": _pv(p.get("prod_sale_amt")),
                "actual_pay": _pv(p.get("prod_actual_pay_amt")),
                "sales_qty": int(_pv(p.get("prod_sale_num_gmv"))),
            }
        )

    # 2. 获取商品库数据（含成本价）
    products = await pool.fetch("""
        SELECT spu_id, name, retail_price, cost_price, category
        FROM qnh_products WHERE status = '在售' AND retail_price > 0
    """)
    product_map = {p["name"]: dict(p) for p in products}

    # 3. 获取竞品价格
    competitor_data = {}
    try:
        comps = await pool.fetch("""
            SELECT product_name, competitor_name, price
            FROM competitor_products
            WHERE updated_at >= CURRENT_DATE - INTERVAL '30 days'
        """)
        for c in comps:
            key = c["product_name"]
            if key not in competitor_data:
                competitor_data[key] = []
            competitor_data[key].append(
                {
                    "competitor": c["competitor_name"],
                    "price": float(c["price"]),
                }
            )
    except Exception:
        logger.debug("No competitor data available")

    # 4. 获取门店 KPI
    store_records = await pool.fetch(
        "SELECT payload FROM qnh_dataset_records WHERE dataset = 'store_rank'"
    )
    total_gmv = 0.0
    total_orders = 0
    for row in store_records:
        p = row["payload"]
        if isinstance(p, str):
            p = json.loads(p)
        total_gmv += _pv(p.get("sale_amt_gmv"))
        total_orders += int(_pv(p.get("eff_ord_cnt")))

    # 5. 分析每个热销商品
    insights: list[PricingInsight] = []
    top_performers: list[dict] = []
    underperformers: list[dict] = []
    competitor_gaps: list[dict] = []
    revenue_potential = 0.0

    for item in sorted(hotsale_data, key=lambda x: x["sales_amount"], reverse=True):
        name = item["name"]
        if not name:
            continue

        prod = product_map.get(name, {})
        retail_price = float(prod.get("retail_price") or 0)
        cost_price = float(prod.get("cost_price") or 0)
        # 计算实际均价（用户实付 / 销量）
        actual_avg_price = item["actual_pay"] / item["sales_qty"] if item["sales_qty"] > 0 else 0
        # 毛利率估算
        if cost_price > 0 and actual_avg_price > 0:
            margin = (actual_avg_price - cost_price) / actual_avg_price * 100
        elif retail_price > 0:
            # 按行业标准估算成本
            if retail_price <= 50:
                margin = 25.0
            elif retail_price <= 200:
                margin = 30.0
            else:
                margin = 35.0
        else:
            margin = 0.0

        # 折扣率（实付 vs 标价）
        discount_rate = (1 - actual_avg_price / retail_price) * 100 if retail_price > 0 else 0

        metrics = {
            "rank": item["rank"],
            "sales_qty": item["sales_qty"],
            "sales_amount": round(item["sales_amount"], 2),
            "actual_pay": round(item["actual_pay"], 2),
            "actual_avg_price": round(actual_avg_price, 2),
            "retail_price": retail_price,
            "discount_rate": round(discount_rate, 1),
            "margin_estimate": round(margin, 1),
        }

        # 竞品对比
        comps = competitor_data.get(name, [])
        if comps:
            avg_comp = sum(c["price"] for c in comps) / len(comps)
            min_comp = min(c["price"] for c in comps)
            metrics["competitor_avg"] = round(avg_comp, 2)
            metrics["competitor_min"] = round(min_comp, 2)
            metrics["vs_competitor"] = (
                round((retail_price / avg_comp - 1) * 100, 1) if avg_comp > 0 else 0
            )

            if retail_price > avg_comp * 1.2:
                competitor_gaps.append(
                    {
                        "product": name,
                        "our_price": retail_price,
                        "competitor_avg": round(avg_comp, 2),
                        "gap_pct": round((retail_price / avg_comp - 1) * 100, 1),
                    }
                )

        # 定价建议逻辑
        action = "hold"
        reason = "价格合理，维持现状"
        priority = "low"
        suggested = None

        # 高销量 + 低毛利 → 提价
        if item["sales_qty"] > 100 and margin < 20:
            action = "raise"
            suggested = round(actual_avg_price * 1.1, 2)
            reason = f"月销{item['sales_qty']}件需求旺盛，毛利率{margin:.0f}%偏低，建议提价10%"
            priority = "high"
            revenue_potential += (
                item["sales_qty"] * (suggested - actual_avg_price) * 0.9
            )  # 90% retention

        # 高销量 + 高折扣 → 减少折扣
        elif item["sales_qty"] > 50 and discount_rate > 30:
            action = "raise"
            suggested = round(retail_price * 0.85, 2)  # 降到15%折扣
            reason = f"折扣率{discount_rate:.0f}%过高，需求足够支撑减少折扣至15%"
            priority = "medium"
            revenue_potential += item["sales_qty"] * (suggested - actual_avg_price) * 0.85

        # 低销量 + 高价 + 有竞品更低 → 降价
        elif item["sales_qty"] < 20 and comps and retail_price > avg_comp * 1.15:
            action = "lower"
            suggested = round(avg_comp * 1.05, 2)  # 比竞品高5%
            reason = f"销量低({item['sales_qty']}件)且高于竞品均价{(retail_price / avg_comp - 1) * 100:.0f}%"
            priority = "medium"

        # 低销量 + 高毛利 → 促销
        elif item["sales_qty"] < 10 and margin > 40:
            action = "promote"
            suggested = round(actual_avg_price * 0.9, 2)
            reason = f"销量仅{item['sales_qty']}件但毛利率{margin:.0f}%高，建议限时促销带量"
            priority = "low"

        # 爆品识别
        if item["rank"] <= 5:
            top_performers.append(
                {
                    "name": name,
                    "rank": item["rank"],
                    "sales_qty": item["sales_qty"],
                    "revenue": round(item["sales_amount"], 2),
                    "actual_avg_price": round(actual_avg_price, 2),
                }
            )

        # 滞销品识别
        if item["sales_qty"] < 5 and item["rank"] > 30:
            underperformers.append(
                {
                    "name": name,
                    "rank": item["rank"],
                    "sales_qty": item["sales_qty"],
                    "revenue": round(item["sales_amount"], 2),
                }
            )

        insights.append(
            PricingInsight(
                product_name=name,
                current_price=retail_price,
                suggested_price=suggested,
                action=action,
                reason=reason,
                priority=priority,
                metrics=metrics,
            )
        )

    # 按优先级排序
    priority_order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda x: priority_order.get(x.priority, 3))

    report = PricingReport(
        total_products_analyzed=len(insights),
        revenue_optimization_potential=round(revenue_potential, 2),
        insights=insights,
        top_performers=top_performers[:10],
        underperformers=underperformers[:10],
        competitor_gaps=competitor_gaps[:10],
    )

    return APIResponse(data=report)


@router.get("/quick-wins")
async def quick_wins() -> APIResponse[list[dict]]:
    """快速盈利机会 — 最容易执行的提价/降本建议。"""
    pool = pg.get_pool()

    wins = []

    # 1. 高销量低折扣空间商品
    hotsale_rows = await pool.fetch(
        "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods' LIMIT 50"
    )

    for row in hotsale_rows:
        p = row["payload"]
        if isinstance(p, str):
            p = json.loads(p)

        name = _sv(p.get("product_name"))
        sales_amt = _pv(p.get("prod_sale_amt"))
        actual_pay = _pv(p.get("prod_actual_pay_amt"))
        qty = int(_pv(p.get("prod_sale_num_gmv")))

        if qty == 0 or sales_amt == 0:
            continue

        discount_rate = (1 - actual_pay / sales_amt) * 100

        # 折扣大于20%且销量好 = 有提价空间
        if discount_rate > 20 and qty > 30:
            potential_gain = qty * (sales_amt / qty - actual_pay / qty) * 0.3  # 收回30%折扣
            wins.append(
                {
                    "type": "reduce_discount",
                    "product": name,
                    "current_discount": f"{discount_rate:.1f}%",
                    "sales_qty": qty,
                    "potential_monthly_gain": round(potential_gain, 2),
                    "action": f"将折扣从{discount_rate:.0f}%降至{max(5, discount_rate - 15):.0f}%",
                    "difficulty": "easy",
                }
            )

    # 2. 低价高频商品提价（价格敏感度低）
    try:
        low_price_high_freq = await pool.fetch("""
            SELECT name, retail_price FROM qnh_products
            WHERE status = '在售' AND retail_price BETWEEN 1 AND 15 AND retail_price > 0
            ORDER BY retail_price ASC LIMIT 10
        """)
        for p in low_price_high_freq:
            wins.append(
                {
                    "type": "micro_raise",
                    "product": p["name"],
                    "current_price": float(p["retail_price"]),
                    "suggested_price": round(float(p["retail_price"]) * 1.15, 2),
                    "action": f"提价15%至¥{float(p['retail_price']) * 1.15:.2f}（低价商品用户不敏感）",
                    "difficulty": "easy",
                }
            )
    except Exception:
        pass

    # Sort by potential gain
    wins.sort(key=lambda w: w.get("potential_monthly_gain", 0), reverse=True)

    return APIResponse(data=wins[:15])
