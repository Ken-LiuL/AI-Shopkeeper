"""智能套餐推荐引擎 — 基于商品关联性 + 场景 + 毛利优化。

不依赖订单级购物篮数据（QNH 不提供），而是通过：
1. 品类互补规则（医疗器械场景知识）
2. 热销商品组合
3. 价格区间互补（高+低搭配提升客单价）
4. LLM 场景命名和文案

输出: 推荐的 bundle 列表，含商品组合、建议价格、场景描述
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── 品类互补规则 ─────────────────────────────────────────────────
# 医疗器械/药房场景下的天然互补品类对
COMPLEMENTARY_PAIRS: list[tuple[list[str], list[str], str, str]] = [
    # (品类A关键词, 品类B关键词, 场景名, 场景描述)
    (
        ["验孕棒", "验孕", "早孕", "HCG"],
        ["叶酸", "孕期", "产检", "排卵"],
        "备孕关怀套装",
        "备孕检测+营养补充，贴心呵护准妈妈",
    ),
    (
        ["避孕套", "安全套", "避孕"],
        ["润滑", "润滑剂", "润滑液"],
        "亲密时刻套装",
        "安全+舒适，品质生活之选",
    ),
    (
        ["血压计", "血压仪"],
        ["血糖仪", "血糖试纸", "血糖"],
        "三高监测套装",
        "血压+血糖双重监测，守护中老年健康",
    ),
    (
        ["血压计", "血压仪"],
        ["体温计", "体温枪", "额温"],
        "家庭健康监测套装",
        "血压+体温，日常健康管理必备",
    ),
    (
        ["血糖仪"],
        ["血糖试纸", "采血针"],
        "血糖监测套装",
        "仪器+耗材一站配齐，长期监测更省心",
    ),
    (
        ["制氧机", "氧气"],
        ["血氧仪", "脉搏", "指夹"],
        "呼吸健康套装",
        "制氧+血氧监测，呼吸系统全方位守护",
    ),
    (
        ["口罩", "N95", "KN95"],
        ["消毒", "酒精", "免洗"],
        "防护消毒套装",
        "防护+消毒，安心出行必备",
    ),
    (
        ["创可贴", "止血"],
        ["碘伏", "消毒液", "棉签", "纱布"],
        "家庭急救套装",
        "常备急救用品，小伤处理不慌张",
    ),
    (
        ["轮椅"],
        ["护理垫", "拐杖", "坐便器"],
        "行动不便护理套装",
        "出行+居家护理，照顾家人更周全",
    ),
    (
        ["雾化器", "雾化"],
        ["生理盐水", "雾化液"],
        "雾化治疗套装",
        "雾化仪器+耗材，居家雾化方便省事",
    ),
    (
        ["助听器"],
        ["助听器电池", "电池"],
        "助听器使用套装",
        "助听器+备用电池，听力无忧",
    ),
    (
        ["护腰", "腰带"],
        ["暖贴", "热敷", "膏药"],
        "腰部护理套装",
        "支撑+热敷，缓解腰部不适",
    ),
]

# 同品类不同价位组合（好+更好/高+低搭配）
UPSELL_RULES: list[dict[str, Any]] = [
    {
        "keywords": ["避孕套"],
        "name": "品质升级组合",
        "desc": "畅销款+高端款搭配，满足不同场景",
        "strategy": "price_ladder",  # 按价格高低搭配
    },
]


@dataclass
class ProductInfo:
    """从 hotsale_goods 提取的商品信息"""

    name: str
    sales: int
    revenue: float
    avg_price: float
    rank: int
    raw: dict = field(default_factory=dict)


@dataclass
class BundleRecommendation:
    """推荐的套餐"""

    bundle_id: str
    name: str
    description: str
    scene: str
    products: list[dict[str, Any]]
    original_total: float
    suggested_price: float
    discount_percent: float
    confidence: float
    reason: str


def _parse_number(val: str | int | float | None) -> float:
    """解析 QNH 数据中的数字（可能有逗号）"""
    if val is None:
        return 0.0
    if isinstance(val, int | float):
        return float(val)
    return float(str(val).replace(",", "").strip() or "0")


def _extract_data_value(record: dict, field_name: str) -> str:
    """从 QNH goldengateway 格式中提取 dataValue"""
    field_data = record.get(field_name)
    if isinstance(field_data, dict):
        return field_data.get("dataValue", "")
    return str(field_data or "")


def _matches_keywords(product_name: str, keywords: list[str]) -> bool:
    """检查商品名是否匹配关键词列表"""
    name_lower = product_name.lower()
    return any(kw.lower() in name_lower for kw in keywords)


async def get_hotsale_products() -> list[ProductInfo]:
    """从 PostgreSQL 获取热销商品数据（fallback 到 SQLite）"""
    rows = []

    # 优先从 PG 读
    try:
        from src.db import postgres as pg

        pool = pg.get_pool()
        pg_rows = await pool.fetch(
            "SELECT payload FROM qnh_dataset_records WHERE dataset='hotsale_goods'"
        )
        rows = [(r["payload"],) for r in pg_rows]
        logger.info("从 PG 加载 %d 条热销商品", len(rows))
    except Exception as e:
        logger.warning("PG 读取失败 (%s)，fallback 到 SQLite", e)

    # Fallback: SQLite
    if not rows:
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).resolve().parent.parent.parent / "data" / "qnh_sync.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                "SELECT payload FROM qnh_dataset_records WHERE dataset='hotsale_goods'"
            ).fetchall()
            conn.close()
            logger.info("从 SQLite 加载 %d 条热销商品", len(rows))
        else:
            logger.warning("SQLite 不存在: %s", db_path)
            return []

    products: list[ProductInfo] = []
    for row in rows:
        raw = row[0]
        data = raw if isinstance(raw, dict) else json.loads(raw)
        name = _extract_data_value(data, "product_name")
        if not name:
            continue
        products.append(
            ProductInfo(
                name=name,
                sales=int(_parse_number(_extract_data_value(data, "prod_sale_num_gmv"))),
                revenue=_parse_number(_extract_data_value(data, "prod_sale_amt")),
                avg_price=_parse_number(_extract_data_value(data, "prod_actual_pay_amt")),
                rank=int(_parse_number(_extract_data_value(data, "rank"))),
                raw=data,
            )
        )

    products.sort(key=lambda p: p.rank)
    return products


def _generate_bundles_from_rules(products: list[ProductInfo]) -> list[BundleRecommendation]:
    """基于品类互补规则生成套餐推荐"""
    bundles: list[BundleRecommendation] = []
    used_products: set[str] = set()

    for idx, (kw_a, kw_b, scene_name, scene_desc) in enumerate(COMPLEMENTARY_PAIRS):
        # 找匹配的商品
        group_a = [p for p in products if _matches_keywords(p.name, kw_a)]
        group_b = [p for p in products if _matches_keywords(p.name, kw_b)]

        if not group_a or not group_b:
            continue

        # 取每组销量最高的
        best_a = group_a[0]  # 已按 rank 排序
        best_b = group_b[0]

        # 跳过已使用的组合
        combo_key = f"{best_a.name}|{best_b.name}"
        if combo_key in used_products:
            continue
        used_products.add(combo_key)

        # 计算价格
        # avg_price 在 hotsale 里是商品实付总额，需要除以销量得到单价
        price_a = best_a.avg_price / max(best_a.sales, 1) if best_a.sales > 0 else best_a.avg_price
        price_b = best_b.avg_price / max(best_b.sales, 1) if best_b.sales > 0 else best_b.avg_price

        # 如果单价不合理（太大说明是总额），用平均值估算
        if price_a > 500:
            price_a = best_a.revenue / max(best_a.sales, 1) if best_a.sales > 0 else price_a
        if price_b > 500:
            price_b = best_b.revenue / max(best_b.sales, 1) if best_b.sales > 0 else price_b

        original_total = price_a + price_b
        if original_total <= 0:
            continue

        # 套餐折扣 5%-15%，销量越高折扣越大
        combined_sales = best_a.sales + best_b.sales
        if combined_sales > 500:
            discount = 0.12
        elif combined_sales > 200:
            discount = 0.10
        elif combined_sales > 50:
            discount = 0.08
        else:
            discount = 0.05

        suggested_price = round(original_total * (1 - discount), 2)

        # 信心度基于销量
        confidence = min(0.95, 0.5 + (combined_sales / 1000))

        bundles.append(
            BundleRecommendation(
                bundle_id=f"bnd_{idx + 1:03d}",
                name=scene_name,
                description=scene_desc,
                scene=scene_name,
                products=[
                    {
                        "name": best_a.name[:60],
                        "unit_price": round(price_a, 2),
                        "sales": best_a.sales,
                        "rank": best_a.rank,
                    },
                    {
                        "name": best_b.name[:60],
                        "unit_price": round(price_b, 2),
                        "sales": best_b.sales,
                        "rank": best_b.rank,
                    },
                ],
                original_total=round(original_total, 2),
                suggested_price=suggested_price,
                discount_percent=round(discount * 100, 1),
                confidence=round(confidence, 2),
                reason=f"品类互补 ({kw_a[0]}+{kw_b[0]})，合计销量{combined_sales}件",
            )
        )

    return bundles


def _generate_same_category_bundles(products: list[ProductInfo]) -> list[BundleRecommendation]:
    """同品类多规格/多品牌组合（量贩装逻辑）"""
    bundles: list[BundleRecommendation] = []

    # 找同品类多个商品
    category_groups: dict[str, list[ProductInfo]] = {}
    category_keywords = ["避孕套", "口罩", "创可贴", "消毒", "试纸"]

    for kw in category_keywords:
        matching = [p for p in products if _matches_keywords(p.name, [kw])]
        if len(matching) >= 2:
            category_groups[kw] = matching

    for kw, group in category_groups.items():
        if len(group) < 2:
            continue

        # 按价格排序，取最便宜和最贵的组合
        priced = []
        for p in group:
            unit = p.avg_price / max(p.sales, 1) if p.sales > 0 else p.avg_price
            if unit > 500:
                unit = p.revenue / max(p.sales, 1) if p.sales > 0 else unit
            priced.append((p, unit))
        priced.sort(key=lambda x: x[1])

        if len(priced) >= 2:
            cheap, cheap_price = priced[0]
            premium, premium_price = priced[-1]

            if cheap.name == premium.name:
                continue

            original = cheap_price + premium_price
            if original <= 0:
                continue

            discount = 0.10
            suggested = round(original * (1 - discount), 2)

            bundles.append(
                BundleRecommendation(
                    bundle_id=f"bnd_cat_{kw}",
                    name=f"{kw}超值组合",
                    description="畅销款+品质款搭配，不同场景灵活选择",
                    scene="品类组合",
                    products=[
                        {
                            "name": cheap.name[:60],
                            "unit_price": round(cheap_price, 2),
                            "sales": cheap.sales,
                            "rank": cheap.rank,
                        },
                        {
                            "name": premium.name[:60],
                            "unit_price": round(premium_price, 2),
                            "sales": premium.sales,
                            "rank": premium.rank,
                        },
                    ],
                    original_total=round(original, 2),
                    suggested_price=suggested,
                    discount_percent=round(discount * 100, 1),
                    confidence=0.65,
                    reason=f"同品类({kw})高低搭配，提升客单价",
                )
            )

    return bundles


async def generate_bundle_recommendations() -> dict[str, Any]:
    """生成套餐推荐 — 主入口"""
    products = await get_hotsale_products()
    if not products:
        return {
            "bundles": [],
            "total": 0,
            "message": "暂无热销商品数据，无法生成推荐",
        }

    logger.info("加载 %d 个热销商品，开始生成 bundle 推荐", len(products))

    # 规则1: 品类互补
    complementary = _generate_bundles_from_rules(products)
    # 规则2: 同品类组合
    same_cat = _generate_same_category_bundles(products)

    all_bundles = complementary + same_cat

    # 按信心度排序
    all_bundles.sort(key=lambda b: b.confidence, reverse=True)

    result_bundles = []
    for b in all_bundles:
        result_bundles.append(
            {
                "bundle_id": b.bundle_id,
                "name": b.name,
                "description": b.description,
                "scene": b.scene,
                "products": b.products,
                "original_total": b.original_total,
                "suggested_price": b.suggested_price,
                "discount_percent": b.discount_percent,
                "confidence": b.confidence,
                "reason": b.reason,
            }
        )

    total_potential = sum(b.original_total - b.suggested_price for b in all_bundles)

    return {
        "bundles": result_bundles,
        "total": len(result_bundles),
        "stats": {
            "products_analyzed": len(products),
            "complementary_bundles": len(complementary),
            "category_bundles": len(same_cat),
            "avg_discount": round(
                sum(b.discount_percent for b in all_bundles) / max(len(all_bundles), 1), 1
            ),
            "potential_revenue_uplift": round(total_potential, 2),
        },
        "message": f"基于 {len(products)} 个热销商品生成 {len(all_bundles)} 个套餐推荐",
    }
