#!/usr/bin/env python3
"""AI店长 - 种子数据脚本。

Usage:
    python scripts/seed_data.py \
        --postgres-url postgresql://postgres:postgres@localhost:5432/ai_store \
        --neo4j-url bolt://localhost:7687 \
        --neo4j-user neo4j \
        --neo4j-password neo4j
"""

from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Product catalog: 30 medical device products
# ---------------------------------------------------------------------------

PRODUCTS: list[dict] = [
    # 血压计 (5)
    {"id": "BP001", "name": "欧姆龙 U726 上臂式电子血压计", "barcode": "4975479412769", "category": "血压计", "brand": "欧姆龙", "cost": 198, "retail": 329, "stock": 45, "monthly": 62},
    {"id": "BP002", "name": "鱼跃 YE680A 臂式电子血压计", "barcode": "6926264400122", "category": "血压计", "brand": "鱼跃", "cost": 128, "retail": 219, "stock": 38, "monthly": 55},
    {"id": "BP003", "name": "迈克大夫 BP A100 Plus 血压计", "barcode": "4719003390012", "category": "血压计", "brand": "迈克大夫", "cost": 168, "retail": 289, "stock": 22, "monthly": 30},
    {"id": "BP004", "name": "欧姆龙 T30J 腕式电子血压计", "barcode": "4975479412806", "category": "血压计", "brand": "欧姆龙", "cost": 148, "retail": 259, "stock": 18, "monthly": 25},
    {"id": "BP005", "name": "九安 KD-5008 电子血压计", "barcode": "6937492000078", "category": "血压计", "brand": "九安", "cost": 88, "retail": 159, "stock": 30, "monthly": 20},
    # 血糖仪 (4)
    {"id": "BG001", "name": "三诺 安稳+ 血糖仪套装", "barcode": "6922067600019", "category": "血糖仪", "brand": "三诺", "cost": 58, "retail": 99, "stock": 60, "monthly": 48},
    {"id": "BG002", "name": "鱼跃 580 血糖仪（含50条试纸）", "barcode": "6926264401580", "category": "血糖仪", "brand": "鱼跃", "cost": 68, "retail": 129, "stock": 40, "monthly": 35},
    {"id": "BG003", "name": "罗氏 逸动II 血糖仪", "barcode": "7613326014021", "category": "血糖仪", "brand": "罗氏", "cost": 188, "retail": 368, "stock": 15, "monthly": 18},
    {"id": "BG004", "name": "三诺 GA-3 血糖试纸50支", "barcode": "6922067600088", "category": "血糖耗材", "brand": "三诺", "cost": 35, "retail": 68, "stock": 120, "monthly": 95},
    # 体温计 (3)
    {"id": "TH001", "name": "欧姆龙 MC-246 电子体温计", "barcode": "4975479414596", "category": "体温计", "brand": "欧姆龙", "cost": 22, "retail": 39, "stock": 80, "monthly": 70},
    {"id": "TH002", "name": "鱼跃 YT-1 红外额温枪", "barcode": "6926264402011", "category": "体温计", "brand": "鱼跃", "cost": 68, "retail": 129, "stock": 35, "monthly": 28},
    {"id": "TH003", "name": "博朗 IRT6520 耳温枪", "barcode": "5765400001208", "category": "体温计", "brand": "博朗", "cost": 188, "retail": 349, "stock": 12, "monthly": 10},
    # 口罩 (3)
    {"id": "MK001", "name": "振德 N95 医用防护口罩 30只", "barcode": "6903883300188", "category": "口罩", "brand": "振德", "cost": 28, "retail": 49.9, "stock": 200, "monthly": 180},
    {"id": "MK002", "name": "稳健 一次性医用外科口罩 50只", "barcode": "6926756800012", "category": "口罩", "brand": "稳健", "cost": 12, "retail": 24.9, "stock": 300, "monthly": 250},
    {"id": "MK003", "name": "3M 9501V+ KN95 防护口罩 25只", "barcode": "7100172426001", "category": "口罩", "brand": "3M", "cost": 45, "retail": 79.9, "stock": 100, "monthly": 60},
    # 创可贴/外伤护理 (3)
    {"id": "FA001", "name": "云南白药 创可贴 100片", "barcode": "6902188001014", "category": "创可贴", "brand": "云南白药", "cost": 15, "retail": 29.9, "stock": 150, "monthly": 130},
    {"id": "FA002", "name": "邦迪 防水弹性创可贴 30片", "barcode": "4891199078996", "category": "创可贴", "brand": "邦迪", "cost": 10, "retail": 19.9, "stock": 120, "monthly": 95},
    {"id": "FA003", "name": "海氏海诺 碘伏棉棒 50支", "barcode": "6926456000123", "category": "消毒用品", "brand": "海氏海诺", "cost": 8, "retail": 16.9, "stock": 100, "monthly": 80},
    # 轮椅 (2)
    {"id": "WC001", "name": "鱼跃 H062 铝合金折叠轮椅", "barcode": "6926264406201", "category": "轮椅", "brand": "鱼跃", "cost": 580, "retail": 999, "stock": 5, "monthly": 3},
    {"id": "WC002", "name": "互邦 HBG25 轻便折叠轮椅", "barcode": "6937812000058", "category": "轮椅", "brand": "互邦", "cost": 450, "retail": 799, "stock": 4, "monthly": 2},
    # 制氧机 (2)
    {"id": "OX001", "name": "鱼跃 8F-5AW 5L制氧机", "barcode": "6926264408015", "category": "制氧机", "brand": "鱼跃", "cost": 1680, "retail": 2899, "stock": 3, "monthly": 2},
    {"id": "OX002", "name": "欧姆龙 HAO-2210 3L制氧机", "barcode": "4975479422101", "category": "制氧机", "brand": "欧姆龙", "cost": 1280, "retail": 2199, "stock": 4, "monthly": 3},
    # 雾化器 (2)
    {"id": "NB001", "name": "欧姆龙 NE-C28 压缩式雾化器", "barcode": "4975479416280", "category": "雾化器", "brand": "欧姆龙", "cost": 258, "retail": 459, "stock": 10, "monthly": 8},
    {"id": "NB002", "name": "鱼跃 403AI 雾化器", "barcode": "6926264404031", "category": "雾化器", "brand": "鱼跃", "cost": 158, "retail": 289, "stock": 12, "monthly": 10},
    # 其他 (6)
    {"id": "PO001", "name": "鱼跃 YX306 指夹式血氧仪", "barcode": "6926264403061", "category": "血氧仪", "brand": "鱼跃", "cost": 88, "retail": 159, "stock": 25, "monthly": 20},
    {"id": "HT001", "name": "仙鹤 CQ-29 神灯理疗仪", "barcode": "6938726000291", "category": "理疗仪", "brand": "仙鹤", "cost": 128, "retail": 229, "stock": 8, "monthly": 5},
    {"id": "GL001", "name": "英科 一次性乳胶手套 100只 M码", "barcode": "6973208000122", "category": "手套", "brand": "英科", "cost": 18, "retail": 35.9, "stock": 80, "monthly": 60},
    {"id": "BN001", "name": "3M 弹性绷带 7.5cm×4.5m", "barcode": "7100150001011", "category": "绷带", "brand": "3M", "cost": 12, "retail": 24.9, "stock": 60, "monthly": 40},
    {"id": "CT001", "name": "仲景 医用棉签 500支", "barcode": "6926000000501", "category": "棉签", "brand": "仲景", "cost": 5, "retail": 12.9, "stock": 200, "monthly": 150},
    {"id": "AB001", "name": "利尔康 75%酒精消毒液 500ml", "barcode": "6933456000501", "category": "消毒用品", "brand": "利尔康", "cost": 8, "retail": 18.9, "stock": 100, "monthly": 85, "status": "inactive"},
]

# 竞品店铺
COMPETITOR_STORES = [
    {"id": "COMP001", "name": "大参林药房（望京店）", "distance": 0.8, "rating": 4.7, "reviews": 2350, "threat": "high"},
    {"id": "COMP002", "name": "海王星辰药房（朝阳路店）", "distance": 1.2, "rating": 4.5, "reviews": 1820, "threat": "high"},
    {"id": "COMP003", "name": "益丰大药房（工体北路店）", "distance": 1.8, "rating": 4.6, "reviews": 1560, "threat": "medium"},
    {"id": "COMP004", "name": "国大药房（安贞桥店）", "distance": 2.5, "rating": 4.3, "reviews": 980, "threat": "medium"},
    {"id": "COMP005", "name": "叮当快药（CBD店）", "distance": 3.0, "rating": 4.8, "reviews": 3200, "threat": "low"},
]

# 竞品商品模板（每个竞品会从中选取10-15个并加价格波动）
_COMP_PRODUCT_TEMPLATES = [
    ("欧姆龙 U726 血压计", "4975479412769", 319),
    ("鱼跃 YE680A 血压计", "6926264400122", 209),
    ("迈克大夫 BP A100 Plus 血压计", "4719003390012", 279),
    ("三诺 安稳+ 血糖仪套装", "6922067600019", 95),
    ("鱼跃 580 血糖仪", "6926264401580", 125),
    ("罗氏 逸动II 血糖仪", "7613326014021", 359),
    ("三诺 GA-3 血糖试纸50支", "6922067600088", 65),
    ("欧姆龙 MC-246 体温计", "4975479414596", 36),
    ("鱼跃 YT-1 额温枪", "6926264402011", 125),
    ("振德 N95 口罩 30只", "6903883300188", 45),
    ("稳健 医用外科口罩 50只", "6926756800012", 22),
    ("云南白药 创可贴 100片", "6902188001014", 28),
    ("鱼跃 YX306 血氧仪", "6926264403061", 155),
    ("鱼跃 H062 轮椅", "6926264406201", 969),
    ("鱼跃 8F-5AW 制氧机", "6926264408015", 2799),
]

# Neo4j 关系数据

POPULATIONS = ["老年人", "高血压患者", "糖尿病患者", "孕妇", "儿童", "成年人"]
SCENARIOS = ["日常血压监测", "血糖管理", "感冒护理", "外伤处理", "居家康复", "婴儿护理"]
SYMPTOMS = ["头晕", "高血压", "低血糖", "发烧", "咳嗽", "外伤"]

# SUITABLE_FOR: product_id -> [(population, confidence)]
SUITABLE_FOR = {
    "BP001": [("老年人", 0.95), ("高血压患者", 0.99), ("成年人", 0.8)],
    "BP002": [("老年人", 0.92), ("高血压患者", 0.98), ("成年人", 0.8)],
    "BP003": [("老年人", 0.90), ("高血压患者", 0.97), ("成年人", 0.8)],
    "BP004": [("老年人", 0.80), ("高血压患者", 0.90), ("成年人", 0.85)],
    "BP005": [("老年人", 0.85), ("高血压患者", 0.95), ("成年人", 0.8)],
    "BG001": [("糖尿病患者", 0.98), ("老年人", 0.85), ("成年人", 0.7)],
    "BG002": [("糖尿病患者", 0.97), ("老年人", 0.85), ("成年人", 0.7)],
    "BG003": [("糖尿病患者", 0.99), ("老年人", 0.88)],
    "BG004": [("糖尿病患者", 0.99)],
    "TH001": [("儿童", 0.90), ("孕妇", 0.85), ("老年人", 0.80), ("成年人", 0.80)],
    "TH002": [("儿童", 0.95), ("孕妇", 0.90), ("老年人", 0.85)],
    "TH003": [("儿童", 0.97), ("孕妇", 0.92)],
    "MK001": [("成年人", 0.95), ("老年人", 0.90)],
    "MK002": [("成年人", 0.90), ("儿童", 0.80), ("老年人", 0.85)],
    "NB001": [("儿童", 0.90), ("老年人", 0.85), ("成年人", 0.80)],
    "NB002": [("儿童", 0.88), ("老年人", 0.82)],
    "WC001": [("老年人", 0.95), ("成年人", 0.70)],
    "WC002": [("老年人", 0.93), ("成年人", 0.65)],
    "OX001": [("老年人", 0.92), ("成年人", 0.70)],
    "OX002": [("老年人", 0.90), ("成年人", 0.68)],
    "PO001": [("老年人", 0.90), ("成年人", 0.80)],
}

# CONTRAINDICATED_FOR: product_id -> [(population, reason)]
CONTRAINDICATED_FOR = {
    "BP004": [("老年人", "腕式血压计对动脉硬化严重的老年人测量偏差较大，建议使用臂式")],
    "BG001": [("儿童", "采血针可能造成儿童恐惧，建议在家长陪同下使用")],
    "OX001": [("儿童", "5L大流量制氧机不适合儿童使用，可能造成氧中毒")],
    "OX002": [("儿童", "制氧机浓度和流量需医生指导，不建议儿童自行使用")],
    "WC001": [("儿童", "成人轮椅尺寸不适合儿童，请选购儿童专用型号")],
    "HT001": [("孕妇", "红外理疗仪可能影响胎儿，孕期禁用")],
}

# USED_IN: product_id -> [scenario]
USED_IN = {
    "BP001": ["日常血压监测"], "BP002": ["日常血压监测"], "BP003": ["日常血压监测"],
    "BP004": ["日常血压监测"], "BP005": ["日常血压监测"],
    "BG001": ["血糖管理"], "BG002": ["血糖管理"], "BG003": ["血糖管理"], "BG004": ["血糖管理"],
    "TH001": ["感冒护理", "婴儿护理"], "TH002": ["感冒护理", "婴儿护理"], "TH003": ["婴儿护理"],
    "MK001": ["感冒护理"], "MK002": ["感冒护理"],
    "FA001": ["外伤处理"], "FA002": ["外伤处理"], "FA003": ["外伤处理"],
    "GL001": ["外伤处理"], "BN001": ["外伤处理"], "CT001": ["外伤处理"],
    "WC001": ["居家康复"], "WC002": ["居家康复"],
    "OX001": ["居家康复"], "OX002": ["居家康复"],
    "NB001": ["感冒护理", "居家康复"], "NB002": ["感冒护理", "居家康复"],
    "HT001": ["居家康复"],
    "PO001": ["居家康复"],
}

# HELPS_WITH: product_id -> [symptom]
HELPS_WITH = {
    "BP001": ["高血压", "头晕"], "BP002": ["高血压", "头晕"], "BP003": ["高血压"],
    "BG001": ["低血糖"], "BG002": ["低血糖"], "BG003": ["低血糖"],
    "TH001": ["发烧"], "TH002": ["发烧"], "TH003": ["发烧"],
    "MK001": ["咳嗽"], "MK002": ["咳嗽"],
    "NB001": ["咳嗽"], "NB002": ["咳嗽"],
    "FA001": ["外伤"], "FA002": ["外伤"], "FA003": ["外伤"],
    "BN001": ["外伤"], "PO001": ["头晕"],
}

# OFTEN_BOUGHT_WITH: (product_a, product_b, support, confidence, lift)
OFTEN_BOUGHT_WITH = [
    ("BG001", "BG004", 0.35, 0.72, 3.2),  # 血糖仪+试纸
    ("BG002", "BG004", 0.28, 0.65, 2.9),
    ("BP001", "PO001", 0.15, 0.32, 2.1),  # 血压计+血氧仪
    ("BP002", "PO001", 0.12, 0.28, 1.9),
    ("FA001", "FA003", 0.22, 0.55, 3.5),  # 创可贴+碘伏棉棒
    ("FA001", "BN001", 0.18, 0.42, 2.8),  # 创可贴+绷带
    ("FA002", "FA003", 0.20, 0.50, 3.1),
    ("MK001", "TH001", 0.10, 0.22, 1.5),  # N95+体温计
    ("MK002", "GL001", 0.12, 0.25, 1.8),  # 口罩+手套
    ("FA003", "CT001", 0.25, 0.60, 3.8),  # 碘伏+棉签
    ("FA003", "GL001", 0.15, 0.38, 2.5),  # 碘伏+手套
    ("OX001", "PO001", 0.08, 0.55, 4.2),  # 制氧机+血氧仪
    ("TH002", "MK002", 0.10, 0.22, 1.4),
    ("AB001", "CT001", 0.18, 0.45, 3.0),  # 酒精+棉签
]

# FAQ 节点
FAQS = [
    {"id": "FAQ001", "q": "电子血压计和水银血压计哪个准？", "a": "电子血压计经过校准后与水银血压计一样准确。对家庭用户来说，电子血压计更方便、更安全（无汞），推荐选择臂式电子血压计。", "products": ["BP001", "BP002", "BP003"]},
    {"id": "FAQ002", "q": "血糖仪试纸可以通用吗？", "a": "不可以。每个品牌的血糖仪都需要使用配套试纸，不同品牌试纸不能混用，否则会导致结果不准确。", "products": ["BG001", "BG002", "BG003", "BG004"]},
    {"id": "FAQ003", "q": "N95口罩和医用外科口罩有什么区别？", "a": "N95口罩过滤效率≥95%，防护性更强，适合高风险环境；医用外科口罩过滤效率≥80%，适合日常防护，透气性更好。", "products": ["MK001", "MK002", "MK003"]},
    {"id": "FAQ004", "q": "老人用哪种血压计好？", "a": "推荐老人使用臂式电子血压计（不推荐腕式），因为老年人血管弹性差，腕式测量偏差较大。选择大屏显示、一键操作的型号更好。", "products": ["BP001", "BP002", "BP003"]},
    {"id": "FAQ005", "q": "制氧机几升的合适？", "a": "家庭保健用1-3L即可；慢阻肺等疾病患者建议5L以上。建议遵医嘱选购。", "products": ["OX001", "OX002"]},
    {"id": "FAQ006", "q": "雾化器压缩式和网式哪种好？", "a": "压缩式雾化器雾化颗粒更均匀，药物利用率高，适合各年龄段；网式更便携安静但价格较高。家庭常备推荐压缩式。", "products": ["NB001", "NB002"]},
    {"id": "FAQ007", "q": "血氧仪正常值是多少？", "a": "正常血氧饱和度为95%-100%。低于94%建议就医，低于90%需紧急处理。指甲油、冰冷的手指可能影响测量准确性。", "products": ["PO001"]},
    {"id": "FAQ008", "q": "轮椅怎么选尺寸？", "a": "座宽=臀宽+2-3cm，座深=大腿长度-5cm。折叠轮椅便于出行，铝合金材质更轻便。建议到店试坐。", "products": ["WC001", "WC002"]},
    {"id": "FAQ009", "q": "创可贴能用在伤口发炎的地方吗？", "a": "不建议。创可贴适用于小型、清洁的伤口。如果伤口已发炎、化脓、较深或面积较大，应先消毒后就医处理。", "products": ["FA001", "FA002"]},
    {"id": "FAQ010", "q": "额温枪和耳温枪哪个准？", "a": "耳温枪测量鼓膜温度，更接近核心体温，准确性更高；额温枪受环境温度影响较大但使用更快捷。婴幼儿推荐耳温枪。", "products": ["TH002", "TH003"]},
    {"id": "FAQ011", "q": "酒精和碘伏消毒有什么区别？", "a": "75%酒精适合皮肤和物体表面消毒，但有刺激性；碘伏刺激性小，适合伤口消毒。伤口建议用碘伏，物体表面用酒精。", "products": ["FA003", "AB001"]},
    {"id": "FAQ012", "q": "血糖什么时候测最准？", "a": "空腹血糖：早上起床后未进食测量；餐后血糖：从吃第一口饭开始计时2小时后测量。建议固定时间测量以便对比。", "products": ["BG001", "BG002", "BG003"]},
]

# ---------------------------------------------------------------------------
# Common purchase patterns for order generation
# ---------------------------------------------------------------------------
_PURCHASE_PATTERNS = [
    # (products, weight) - weight = likelihood of this combination
    (["BP001"], 8),
    (["BP002"], 7),
    (["BP001", "PO001"], 4),
    (["BP002", "PO001"], 3),
    (["BG001", "BG004"], 6),
    (["BG002", "BG004"], 4),
    (["BG001", "BG004", "BG004"], 2),  # buy 2 boxes of strips
    (["TH001"], 5),
    (["TH002"], 4),
    (["MK002"], 10),
    (["MK001"], 6),
    (["MK002", "MK002"], 3),
    (["MK001", "GL001"], 2),
    (["MK002", "GL001"], 2),
    (["FA001"], 6),
    (["FA001", "FA003"], 5),
    (["FA001", "FA003", "CT001"], 3),
    (["FA002", "FA003"], 3),
    (["FA001", "BN001", "FA003"], 2),
    (["BN001", "GL001", "FA003", "CT001"], 1),
    (["WC001"], 1),
    (["OX001", "PO001"], 1),
    (["OX001"], 1),
    (["NB001"], 2),
    (["NB002"], 2),
    (["TH002", "MK002"], 2),
    (["CT001", "AB001"], 3),
    (["HT001"], 1),
    (["GL001"], 3),
    (["CT001"], 4),
    (["AB001"], 3),
    (["MK003"], 3),
    (["FA002"], 4),
    (["PO001"], 2),
    (["BG003"], 1),
    (["BP003"], 2),
    (["TH001", "MK002", "CT001"], 2),
]


def _product_map() -> dict[str, dict]:
    return {p["id"]: p for p in PRODUCTS}


# ============================================================
# PostgreSQL seeding
# ============================================================

async def seed_postgres(pg_url: str) -> None:
    import asyncpg  # type: ignore[import-untyped]

    print("[PG] Connecting …")
    conn: asyncpg.Connection = await asyncpg.connect(pg_url)

    try:
        pmap = _product_map()
        today = date.today()
        tz = timezone.utc

        # --- Products ---
        print("[PG] Inserting products …")
        for p in PRODUCTS:
            status = p.get("status", "active")
            await conn.execute(
                """INSERT INTO products (product_id, name, barcode, category, brand, description,
                   cost_price, retail_price, stock, monthly_sales, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (product_id) DO NOTHING""",
                p["id"], p["name"], p["barcode"], p["category"], p["brand"],
                f'{p["brand"]} {p["name"]}',
                Decimal(str(p["cost"])), Decimal(str(p["retail"])),
                p["stock"], p["monthly"], status,
            )
        print(f"[PG] {len(PRODUCTS)} products inserted.")

        # --- Competitor stores ---
        print("[PG] Inserting competitor stores …")
        for cs in COMPETITOR_STORES:
            await conn.execute(
                """INSERT INTO competitor_stores (competitor_id, name, platform, distance_km,
                   rating, review_count, threat_level, last_crawl_at)
                   VALUES ($1,$2,'meituan',$3,$4,$5,$6,$7)
                   ON CONFLICT (competitor_id) DO NOTHING""",
                cs["id"], cs["name"], Decimal(str(cs["distance"])),
                Decimal(str(cs["rating"])), cs["reviews"], cs["threat"],
                datetime.now(tz),
            )

        # --- Competitor products ---
        print("[PG] Inserting competitor products …")
        random.seed(42)
        for cs in COMPETITOR_STORES:
            n = random.randint(10, 15)
            chosen = random.sample(_COMP_PRODUCT_TEMPLATES, min(n, len(_COMP_PRODUCT_TEMPLATES)))
            for name, barcode, base_price in chosen:
                price_var = base_price * random.uniform(0.90, 1.10)
                monthly = random.randint(5, 120)
                await conn.execute(
                    """INSERT INTO competitor_products (competitor_id, product_name, barcode, price, monthly_sales, is_stockout)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    cs["id"], name, barcode,
                    Decimal(str(round(price_var, 2))), monthly,
                    random.random() < 0.05,
                )

        # --- Orders (200, last 90 days) ---
        print("[PG] Inserting 200 orders …")
        random.seed(123)
        weighted_patterns = []
        for pattern, weight in _PURCHASE_PATTERNS:
            weighted_patterns.extend([pattern] * weight)

        for i in range(200):
            order_id = f"MT{today.strftime('%Y%m%d')}{i:04d}"
            days_ago = random.randint(0, 89)
            hour = random.choice([8, 9, 10, 11, 14, 15, 16, 17, 18, 19, 20, 21])
            minute = random.randint(0, 59)
            order_time = datetime(
                today.year, today.month, today.day, hour, minute, 0, tzinfo=tz
            ) - timedelta(days=days_ago)

            pattern = random.choice(weighted_patterns)
            total = Decimal("0")
            items = []
            for pid in pattern:
                p = pmap[pid]
                qty = 1
                price = Decimal(str(p["retail"]))
                total += price * qty
                items.append((pid, qty, price))

            status = random.choices(["completed", "completed", "completed", "cancelled", "refunded"], weights=[85, 5, 5, 3, 2])[0]
            addr_type = random.choice(["home", "office", "hospital", "nursing_home"])
            phone_suffix = f"{random.randint(0, 9999):04d}"

            await conn.execute(
                """INSERT INTO orders (order_id, platform, customer_phone_suffix, total_amount,
                   status, order_time, delivery_address_type)
                   VALUES ($1,'meituan',$2,$3,$4,$5,$6)
                   ON CONFLICT (order_id) DO NOTHING""",
                order_id, phone_suffix, total, status, order_time, addr_type,
            )
            for pid, qty, price in items:
                await conn.execute(
                    """INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                       VALUES ($1,$2,$3,$4)""",
                    order_id, pid, qty, price,
                )

        # --- Sales history (90 days × 30 products) ---
        print("[PG] Inserting sales_history (90 days × 30 products) …")
        random.seed(456)
        rows = []
        for p in PRODUCTS:
            base_daily = max(1, p["monthly"] // 30)
            for d in range(90):
                sale_date = today - timedelta(days=d)
                # Add some variance + weekend bump + random promotion
                weekday = sale_date.weekday()
                factor = 1.15 if weekday >= 5 else 1.0
                qty = max(0, int(base_daily * factor * random.uniform(0.5, 1.8)))
                revenue = Decimal(str(round(qty * p["retail"], 2)))
                is_promo = random.random() < 0.08
                if is_promo:
                    qty = int(qty * 1.5)
                    revenue = Decimal(str(round(qty * p["retail"] * 0.9, 2)))
                rows.append((p["id"], sale_date, qty, revenue, is_promo, False))

        # Batch insert
        await conn.executemany(
            """INSERT INTO sales_history (product_id, sale_date, quantity, revenue, is_promotion, is_weather_event)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (product_id, sale_date) DO NOTHING""",
            rows,
        )
        print(f"[PG] {len(rows)} sales_history rows inserted.")

    finally:
        await conn.close()
    print("[PG] Done ✅")


# ============================================================
# Neo4j seeding
# ============================================================

def seed_neo4j(neo4j_url: str, neo4j_user: str, neo4j_password: str) -> None:
    from neo4j import GraphDatabase  # type: ignore[import-untyped]

    print("[Neo4j] Connecting …")
    driver = GraphDatabase.driver(neo4j_url, auth=(neo4j_user, neo4j_password))

    with driver.session() as session:
        # --- Population nodes ---
        print("[Neo4j] Creating Population nodes …")
        for pop in POPULATIONS:
            session.run("MERGE (:Population {name: $name})", name=pop)

        # --- Scenario nodes ---
        print("[Neo4j] Creating Scenario nodes …")
        for sc in SCENARIOS:
            session.run("MERGE (:Scenario {name: $name})", name=sc)

        # --- Symptom nodes ---
        print("[Neo4j] Creating Symptom nodes …")
        for sym in SYMPTOMS:
            session.run("MERGE (:Symptom {name: $name})", name=sym)

        # --- Product nodes ---
        print("[Neo4j] Creating Product nodes …")
        for p in PRODUCTS:
            session.run(
                """MERGE (p:Product {product_id: $pid})
                   SET p.name = $name,
                       p.category = $category,
                       p.brand = $brand,
                       p.description = $desc,
                       p.retail_price = $price,
                       p.embedding = null""",
                pid=p["id"], name=p["name"], category=p["category"],
                brand=p["brand"], desc=f'{p["brand"]} {p["name"]}',
                price=float(p["retail"]),
            )

        # --- SUITABLE_FOR ---
        print("[Neo4j] Creating SUITABLE_FOR relationships …")
        for pid, pops in SUITABLE_FOR.items():
            for pop_name, conf in pops:
                session.run(
                    """MATCH (p:Product {product_id: $pid}), (pop:Population {name: $pop})
                       MERGE (p)-[r:SUITABLE_FOR]->(pop)
                       SET r.confidence = $conf""",
                    pid=pid, pop=pop_name, conf=conf,
                )

        # --- CONTRAINDICATED_FOR ---
        print("[Neo4j] Creating CONTRAINDICATED_FOR relationships …")
        for pid, pops in CONTRAINDICATED_FOR.items():
            for pop_name, reason in pops:
                session.run(
                    """MATCH (p:Product {product_id: $pid}), (pop:Population {name: $pop})
                       MERGE (p)-[r:CONTRAINDICATED_FOR]->(pop)
                       SET r.reason = $reason""",
                    pid=pid, pop=pop_name, reason=reason,
                )

        # --- USED_IN ---
        print("[Neo4j] Creating USED_IN relationships …")
        for pid, scenarios in USED_IN.items():
            for sc in scenarios:
                session.run(
                    """MATCH (p:Product {product_id: $pid}), (s:Scenario {name: $sc})
                       MERGE (p)-[:USED_IN]->(s)""",
                    pid=pid, sc=sc,
                )

        # --- HELPS_WITH ---
        print("[Neo4j] Creating HELPS_WITH relationships …")
        for pid, symptoms in HELPS_WITH.items():
            for sym in symptoms:
                session.run(
                    """MATCH (p:Product {product_id: $pid}), (s:Symptom {name: $sym})
                       MERGE (p)-[:HELPS_WITH]->(s)""",
                    pid=pid, sym=sym,
                )

        # --- OFTEN_BOUGHT_WITH ---
        print("[Neo4j] Creating OFTEN_BOUGHT_WITH relationships …")
        for pa, pb, support, confidence, lift in OFTEN_BOUGHT_WITH:
            session.run(
                """MATCH (a:Product {product_id: $pa}), (b:Product {product_id: $pb})
                   MERGE (a)-[r:OFTEN_BOUGHT_WITH]->(b)
                   SET r.support = $support, r.confidence = $confidence, r.lift = $lift""",
                pa=pa, pb=pb, support=support, confidence=confidence, lift=lift,
            )

        # --- FAQ nodes ---
        print("[Neo4j] Creating FAQ nodes and ANSWERS relationships …")
        for faq in FAQS:
            session.run(
                """MERGE (f:FAQ {faq_id: $fid})
                   SET f.question = $q, f.answer = $a, f.question_embedding = null""",
                fid=faq["id"], q=faq["q"], a=faq["a"],
            )
            for pid in faq["products"]:
                session.run(
                    """MATCH (f:FAQ {faq_id: $fid}), (p:Product {product_id: $pid})
                       MERGE (f)-[:ANSWERS]->(p)""",
                    fid=faq["id"], pid=pid,
                )

    driver.close()
    print("[Neo4j] Done ✅")


# ============================================================
# Main
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="AI店长 种子数据")
    parser.add_argument("--postgres-url", default="postgresql://postgres:postgres@localhost:5432/ai_store")
    parser.add_argument("--neo4j-url", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="neo4j")
    parser.add_argument("--skip-pg", action="store_true")
    parser.add_argument("--skip-neo4j", action="store_true")
    args = parser.parse_args()

    if not args.skip_pg:
        asyncio.run(seed_postgres(args.postgres_url))

    if not args.skip_neo4j:
        seed_neo4j(args.neo4j_url, args.neo4j_user, args.neo4j_password)

    print("\n🎉 All seed data loaded!")


if __name__ == "__main__":
    main()
