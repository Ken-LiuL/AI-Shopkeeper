"""智能选品推荐 — 基于销售数据+品类缺口+市场趋势。"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter

from src.db import postgres as pg

from .schemas import APIResponse

router = APIRouter(prefix="/api/selection-intelligence", tags=["selection"])
logger = logging.getLogger(__name__)


def _pv(field) -> float:
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
    if field is None:
        return ""
    if isinstance(field, dict):
        return str(field.get("dataValue", ""))
    return str(field)


@router.get("/gaps")
async def category_gaps() -> APIResponse[list[dict]]:
    """品类缺口分析 — 哪些品类商品少但行业需求大。"""
    pool = pg.get_pool()

    # 当前品类分布
    cats = await pool.fetch("""
        SELECT category, COUNT(*) as cnt,
               AVG(retail_price) as avg_price,
               SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_cnt
        FROM products
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category
        ORDER BY cnt DESC
    """)

    total = sum(c["cnt"] for c in cats)
    gaps = []

    # 医疗器械行业标准品类（即时零售）
    ideal_categories = {
        "医用急救": {"ideal_pct": 15, "reason": "急救类需求刚性，复购率高"},
        "家庭常备": {"ideal_pct": 12, "reason": "日常消耗品，复购稳定"},
        "成人情趣": {"ideal_pct": 10, "reason": "高毛利品类，即时需求强"},
        "美容敷料": {"ideal_pct": 10, "reason": "女性消费主力，客单价高"},
        "检测试剂": {"ideal_pct": 8, "reason": "隐私需求驱动即时购买"},
        "口腔护理": {"ideal_pct": 8, "reason": "日常消耗，引流品类"},
        "母婴用品": {"ideal_pct": 5, "reason": "家庭场景延伸"},
        "保健器械": {"ideal_pct": 5, "reason": "高客单价，利润贡献大"},
    }

    cat_map = {}
    for c in cats:
        # Simplify category name for matching
        short = c["category"].split(">")[0] if ">" in c["category"] else c["category"]
        if short not in cat_map:
            cat_map[short] = {"count": 0, "active": 0, "avg_price": 0, "full_name": c["category"]}
        cat_map[short]["count"] += c["cnt"]
        cat_map[short]["active"] += c["active_cnt"]

    for ideal_cat, info in ideal_categories.items():
        current = cat_map.get(ideal_cat, {})
        current_cnt = current.get("count", 0)
        current_pct = (current_cnt / total * 100) if total > 0 else 0
        ideal_pct = info["ideal_pct"]

        if current_pct < ideal_pct * 0.7:  # 低于理想值70%
            gaps.append(
                {
                    "category": ideal_cat,
                    "current_products": current_cnt,
                    "current_pct": round(current_pct, 1),
                    "ideal_pct": ideal_pct,
                    "gap": round(ideal_pct - current_pct, 1),
                    "priority": "high" if current_pct < ideal_pct * 0.3 else "medium",
                    "reason": info["reason"],
                    "recommendation": f"建议补充{min(20, max(3, int(total * (ideal_pct - current_pct) / 100 * 0.3)))}款{ideal_cat}商品",
                }
            )

    gaps.sort(key=lambda x: x["gap"], reverse=True)
    return APIResponse(data=gaps)


@router.get("/opportunities")
async def selection_opportunities() -> APIResponse[dict]:
    """选品机会发现 — 基于热销数据+品类分析。"""
    pool = pg.get_pool()

    # 1. 热销商品品类集中度
    hotsale_rows = await pool.fetch(
        "SELECT payload FROM qnh_dataset_records WHERE dataset = 'hotsale_goods'"
    )

    category_revenue: dict[str, float] = {}
    top_products = []
    for row in hotsale_rows:
        p = row["payload"]
        if isinstance(p, str):
            p = json.loads(p)
        name = _sv(p.get("product_name"))
        revenue = _pv(p.get("prod_sale_amt"))
        qty = int(_pv(p.get("prod_sale_num_gmv")))
        if not name:
            continue

        # Match to category
        prod = await pool.fetchrow(
            "SELECT category FROM products WHERE name = $1 LIMIT 1", name
        )
        cat = prod["category"] if prod else "未分类"
        short_cat = cat.split(">")[0] if ">" in cat else cat

        if short_cat not in category_revenue:
            category_revenue[short_cat] = 0
        category_revenue[short_cat] += revenue

        avg_price = revenue / qty if qty > 0 else 0
        top_products.append(
            {
                "name": name[:30],
                "category": short_cat,
                "revenue": round(revenue, 2),
                "qty": qty,
                "avg_price": round(avg_price, 2),
            }
        )

    # 2. 高收入品类 = 应该加大投入
    sorted_cats = sorted(category_revenue.items(), key=lambda x: x[1], reverse=True)

    # 3. 低SKU高收入 = 选品不够
    cat_sku = await pool.fetch("""
        SELECT SPLIT_PART(category, '>', 1) as short_cat, COUNT(*) as sku_count
        FROM products WHERE status = 'active' AND category != ''
        GROUP BY SPLIT_PART(category, '>', 1)
    """)
    sku_map = {c["short_cat"]: c["sku_count"] for c in cat_sku}

    underserved = []
    for cat, rev in sorted_cats[:10]:
        skus = sku_map.get(cat, 0)
        rev_per_sku = rev / skus if skus > 0 else rev
        if rev_per_sku > 100:  # High revenue per SKU = needs more selection
            underserved.append(
                {
                    "category": cat,
                    "revenue": round(rev, 2),
                    "sku_count": skus,
                    "revenue_per_sku": round(rev_per_sku, 2),
                    "suggestion": f"每SKU贡献¥{rev_per_sku:.0f}收入，建议增加{max(3, int(skus * 0.5))}款同类商品分散风险",
                }
            )

    return APIResponse(
        data={
            "category_revenue_ranking": [
                {"category": cat, "revenue": round(rev, 2)} for cat, rev in sorted_cats[:10]
            ],
            "underserved_categories": underserved,
            "top_products_by_revenue": top_products[:10],
            "total_hotsale_products": len(top_products),
        }
    )
