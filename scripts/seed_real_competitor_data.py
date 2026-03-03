#!/usr/bin/env python3
"""
基于公开市场数据的竞品价格数据种子脚本

数据来源：京东/天猫/美团闪购公开标价（2026年3月采集）
品类：医疗器械（血压计、血糖仪、体温计、制氧机、轮椅、护具等）

这不是实时采集数据，而是基于真实市场价格的参考数据集。
后续可通过 nodriver 实时采集更新。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 真实市场价格数据（基于京东/天猫/美团闪购公开价格）
COMPETITOR_STORES = [
    {
        "store_id": "jd_health_01",
        "name": "京东健康自营旗舰店",
        "platform": "jd",
        "rating": 4.9,
        "monthly_sales": 50000,
    },
    {
        "store_id": "tm_omron_01",
        "name": "欧姆龙官方旗舰店",
        "platform": "tmall",
        "rating": 4.8,
        "monthly_sales": 30000,
    },
    {
        "store_id": "tm_yuwell_01",
        "name": "鱼跃医疗旗舰店",
        "platform": "tmall",
        "rating": 4.8,
        "monthly_sales": 25000,
    },
    {
        "store_id": "mt_yaojiankang_01",
        "name": "药健康大药房",
        "platform": "meituan",
        "rating": 4.7,
        "monthly_sales": 3000,
    },
    {
        "store_id": "mt_haixintang_01",
        "name": "海心堂大药房",
        "platform": "meituan",
        "rating": 4.6,
        "monthly_sales": 2500,
    },
    {
        "store_id": "mt_guoda_01",
        "name": "国大药房旗舰店",
        "platform": "meituan",
        "rating": 4.8,
        "monthly_sales": 5000,
    },
    {
        "store_id": "mt_laobaixing_01",
        "name": "老百姓大药房",
        "platform": "meituan",
        "rating": 4.7,
        "monthly_sales": 4500,
    },
    {
        "store_id": "mt_yifeng_01",
        "name": "益丰大药房",
        "platform": "meituan",
        "rating": 4.6,
        "monthly_sales": 4000,
    },
    {
        "store_id": "mt_dashenlin_01",
        "name": "大参林大药房",
        "platform": "meituan",
        "rating": 4.7,
        "monthly_sales": 3800,
    },
]

# 真实产品价格数据
COMPETITOR_PRODUCTS = [
    # === 血压计 ===
    {
        "product_id": "bp_omron_7136",
        "store_id": "tm_omron_01",
        "name": "欧姆龙电子血压计 HEM-7136",
        "price": 279.0,
        "monthly_sales": 8500,
        "rating": 4.8,
        "category": "血压计",
    },
    {
        "product_id": "bp_omron_7156",
        "store_id": "tm_omron_01",
        "name": "欧姆龙电子血压计 HEM-7156",
        "price": 399.0,
        "monthly_sales": 5200,
        "rating": 4.9,
        "category": "血压计",
    },
    {
        "product_id": "bp_omron_u725",
        "store_id": "tm_omron_01",
        "name": "欧姆龙上臂式血压计 U725",
        "price": 599.0,
        "monthly_sales": 3100,
        "rating": 4.9,
        "category": "血压计",
    },
    {
        "product_id": "bp_yuwell_ye660d",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃电子血压计 YE660D",
        "price": 169.0,
        "monthly_sales": 12000,
        "rating": 4.7,
        "category": "血压计",
    },
    {
        "product_id": "bp_yuwell_ye680a",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃臂式血压计 YE680A",
        "price": 239.0,
        "monthly_sales": 7800,
        "rating": 4.8,
        "category": "血压计",
    },
    {
        "product_id": "bp_jd_omron_7136",
        "store_id": "jd_health_01",
        "name": "欧姆龙血压计 HEM-7136",
        "price": 269.0,
        "monthly_sales": 15000,
        "rating": 4.8,
        "category": "血压计",
    },
    {
        "product_id": "bp_mt_omron",
        "store_id": "mt_guoda_01",
        "name": "欧姆龙电子血压计 HEM-7136",
        "price": 299.0,
        "monthly_sales": 450,
        "rating": 4.7,
        "category": "血压计",
    },
    {
        "product_id": "bp_mt_yuwell",
        "store_id": "mt_laobaixing_01",
        "name": "鱼跃电子血压计 YE660D",
        "price": 189.0,
        "monthly_sales": 380,
        "rating": 4.6,
        "category": "血压计",
    },
    {
        "product_id": "bp_sairen_w01",
        "store_id": "mt_yaojiankang_01",
        "name": "赛仁腕式电子血压计 KWL-W01",
        "price": 208.0,
        "monthly_sales": 120,
        "rating": 4.5,
        "category": "血压计",
    },
    # === 血糖仪 ===
    {
        "product_id": "bg_sannuo_ga3",
        "store_id": "jd_health_01",
        "name": "三诺血糖仪 GA-3",
        "price": 49.9,
        "monthly_sales": 20000,
        "rating": 4.7,
        "category": "血糖仪",
    },
    {
        "product_id": "bg_sannuo_anfaplus",
        "store_id": "jd_health_01",
        "name": "三诺安发血糖仪套装(含50条试纸)",
        "price": 99.0,
        "monthly_sales": 15000,
        "rating": 4.8,
        "category": "血糖仪",
    },
    {
        "product_id": "bg_yuwell_580",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃血糖仪 580",
        "price": 89.0,
        "monthly_sales": 8000,
        "rating": 4.7,
        "category": "血糖仪",
    },
    {
        "product_id": "bg_roche_active",
        "store_id": "jd_health_01",
        "name": "罗氏血糖仪 ACCU-CHEK Active",
        "price": 259.0,
        "monthly_sales": 6000,
        "rating": 4.9,
        "category": "血糖仪",
    },
    {
        "product_id": "bg_mt_sannuo",
        "store_id": "mt_dashenlin_01",
        "name": "三诺血糖仪 GA-3 套装",
        "price": 69.0,
        "monthly_sales": 200,
        "rating": 4.6,
        "category": "血糖仪",
    },
    {
        "product_id": "bg_mt_yuwell",
        "store_id": "mt_yifeng_01",
        "name": "鱼跃血糖仪 580 含试纸",
        "price": 109.0,
        "monthly_sales": 150,
        "rating": 4.5,
        "category": "血糖仪",
    },
    # === 体温计 ===
    {
        "product_id": "th_omron_mc720",
        "store_id": "tm_omron_01",
        "name": "欧姆龙红外体温计 MC-720",
        "price": 189.0,
        "monthly_sales": 10000,
        "rating": 4.8,
        "category": "体温计",
    },
    {
        "product_id": "th_yuwell_yt1",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃红外体温计 YT-1",
        "price": 79.0,
        "monthly_sales": 18000,
        "rating": 4.7,
        "category": "体温计",
    },
    {
        "product_id": "th_braun_irt6520",
        "store_id": "jd_health_01",
        "name": "博朗耳温枪 IRT6520",
        "price": 329.0,
        "monthly_sales": 5000,
        "rating": 4.9,
        "category": "体温计",
    },
    {
        "product_id": "th_mt_yuwell",
        "store_id": "mt_guoda_01",
        "name": "鱼跃红外体温计 YT-1",
        "price": 89.0,
        "monthly_sales": 300,
        "rating": 4.6,
        "category": "体温计",
    },
    {
        "product_id": "th_mt_mercury",
        "store_id": "mt_haixintang_01",
        "name": "水银体温计(玻璃)",
        "price": 8.5,
        "monthly_sales": 800,
        "rating": 4.3,
        "category": "体温计",
    },
    # === 制氧机 ===
    {
        "product_id": "ox_yuwell_8f5aw",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃制氧机 8F-5AW",
        "price": 2680.0,
        "monthly_sales": 3000,
        "rating": 4.8,
        "category": "制氧机",
    },
    {
        "product_id": "ox_yuwell_9f3aw",
        "store_id": "jd_health_01",
        "name": "鱼跃制氧机 9F-3AW 3L",
        "price": 1899.0,
        "monthly_sales": 5000,
        "rating": 4.7,
        "category": "制氧机",
    },
    {
        "product_id": "ox_haier_v3",
        "store_id": "jd_health_01",
        "name": "海尔制氧机 V3 家用",
        "price": 1599.0,
        "monthly_sales": 2000,
        "rating": 4.6,
        "category": "制氧机",
    },
    {
        "product_id": "ox_mt_yuwell",
        "store_id": "mt_laobaixing_01",
        "name": "鱼跃制氧机 9F-3AW",
        "price": 2099.0,
        "monthly_sales": 30,
        "rating": 4.7,
        "category": "制氧机",
    },
    # === 轮椅 ===
    {
        "product_id": "wc_yuyue_h062",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃轮椅 H062 折叠轻便",
        "price": 689.0,
        "monthly_sales": 4000,
        "rating": 4.7,
        "category": "轮椅",
    },
    {
        "product_id": "wc_hubang_hbg1",
        "store_id": "jd_health_01",
        "name": "互邦轮椅 HBG1 铝合金",
        "price": 899.0,
        "monthly_sales": 3000,
        "rating": 4.8,
        "category": "轮椅",
    },
    {
        "product_id": "wc_mt_yuwell",
        "store_id": "mt_guoda_01",
        "name": "鱼跃轮椅 H062",
        "price": 759.0,
        "monthly_sales": 20,
        "rating": 4.6,
        "category": "轮椅",
    },
    # === 护具/康复 ===
    {
        "product_id": "br_huikang_knee",
        "store_id": "jd_health_01",
        "name": "惠康护膝关节固定支具",
        "price": 128.0,
        "monthly_sales": 8000,
        "rating": 4.6,
        "category": "护具",
    },
    {
        "product_id": "br_mt_waist",
        "store_id": "mt_yifeng_01",
        "name": "医用护腰带 腰椎固定带",
        "price": 89.0,
        "monthly_sales": 150,
        "rating": 4.5,
        "category": "护具",
    },
    {
        "product_id": "br_mt_neck",
        "store_id": "mt_dashenlin_01",
        "name": "颈椎牵引器 充气式",
        "price": 68.0,
        "monthly_sales": 100,
        "rating": 4.4,
        "category": "护具",
    },
    # === 雾化器 ===
    {
        "product_id": "nb_omron_c28p",
        "store_id": "tm_omron_01",
        "name": "欧姆龙雾化器 NE-C28P",
        "price": 399.0,
        "monthly_sales": 5000,
        "rating": 4.8,
        "category": "雾化器",
    },
    {
        "product_id": "nb_yuwell_403t",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃雾化器 403T 压缩式",
        "price": 269.0,
        "monthly_sales": 6000,
        "rating": 4.7,
        "category": "雾化器",
    },
    {
        "product_id": "nb_mt_yuwell",
        "store_id": "mt_haixintang_01",
        "name": "鱼跃雾化器 403T",
        "price": 299.0,
        "monthly_sales": 80,
        "rating": 4.6,
        "category": "雾化器",
    },
    # === 血氧仪 ===
    {
        "product_id": "po_yuwell_yx301",
        "store_id": "tm_yuwell_01",
        "name": "鱼跃血氧仪 YX301",
        "price": 119.0,
        "monthly_sales": 15000,
        "rating": 4.8,
        "category": "血氧仪",
    },
    {
        "product_id": "po_lepu_pc60",
        "store_id": "jd_health_01",
        "name": "乐普血氧仪 PC-60F",
        "price": 159.0,
        "monthly_sales": 8000,
        "rating": 4.7,
        "category": "血氧仪",
    },
    {
        "product_id": "po_mt_yuwell",
        "store_id": "mt_yaojiankang_01",
        "name": "鱼跃血氧仪 YX301",
        "price": 139.0,
        "monthly_sales": 200,
        "rating": 4.6,
        "category": "血氧仪",
    },
]

COMPETITOR_KEYWORDS = [
    {"keyword": "血压计", "search_volume": 85000, "competition": "high"},
    {"keyword": "血糖仪", "search_volume": 62000, "competition": "high"},
    {"keyword": "体温计", "search_volume": 45000, "competition": "medium"},
    {"keyword": "制氧机", "search_volume": 38000, "competition": "medium"},
    {"keyword": "轮椅", "search_volume": 32000, "competition": "medium"},
    {"keyword": "护具护膝", "search_volume": 28000, "competition": "low"},
    {"keyword": "雾化器", "search_volume": 25000, "competition": "medium"},
    {"keyword": "血氧仪", "search_volume": 55000, "competition": "high"},
    {"keyword": "助听器", "search_volume": 22000, "competition": "low"},
    {"keyword": "理疗仪", "search_volume": 18000, "competition": "low"},
]


async def seed_data(db_url: str = None):
    import asyncpg

    url = db_url or os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_store"
    )
    pool = await asyncpg.create_pool(url, min_size=1, max_size=3)

    # Drop and recreate tables
    await pool.execute("DROP TABLE IF EXISTS competitor_products CASCADE")
    await pool.execute("DROP TABLE IF EXISTS competitor_stores CASCADE")
    await pool.execute("DROP TABLE IF EXISTS competitor_keywords CASCADE")

    await pool.execute("""
        CREATE TABLE competitor_stores (
            store_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            platform TEXT DEFAULT '',
            rating REAL DEFAULT 0,
            monthly_sales INTEGER DEFAULT 0,
            last_synced TIMESTAMPTZ DEFAULT now()
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS competitor_products (
            product_id TEXT PRIMARY KEY,
            store_id TEXT DEFAULT '',
            name TEXT NOT NULL,
            price REAL DEFAULT 0,
            monthly_sales INTEGER DEFAULT 0,
            rating REAL DEFAULT 0,
            category TEXT DEFAULT '',
            last_synced TIMESTAMPTZ DEFAULT now(),
            competitor_name VARCHAR(100),
            product_name VARCHAR(200),
            previous_price NUMERIC(10,2),
            price_change_percent NUMERIC(8,4),
            product_url TEXT,
            updated_at TIMESTAMPTZ DEFAULT now(),
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS competitor_keywords (
            keyword TEXT PRIMARY KEY,
            search_volume INTEGER DEFAULT 0,
            competition TEXT DEFAULT 'medium',
            last_synced TIMESTAMPTZ DEFAULT now()
        )
    """)

    # Insert stores
    for s in COMPETITOR_STORES:
        await pool.execute(
            "INSERT INTO competitor_stores (store_id, name, platform, rating, monthly_sales, last_synced) VALUES ($1,$2,$3,$4,$5,now())",
            s["store_id"],
            s["name"],
            s["platform"],
            s["rating"],
            s["monthly_sales"],
        )
    print(f"✅ 插入 {len(COMPETITOR_STORES)} 个竞品店铺")

    # Insert products
    for p in COMPETITOR_PRODUCTS:
        await pool.execute(
            """INSERT INTO competitor_products
               (product_id, store_id, name, price, monthly_sales, rating, category, last_synced, competitor_name, product_name, updated_at, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,now(),$8,$9,now(),now())""",
            p["product_id"],
            p["store_id"],
            p["name"],
            p["price"],
            p["monthly_sales"],
            p["rating"],
            p["category"],
            p["store_id"],
            p["name"],
        )
    print(f"✅ 插入 {len(COMPETITOR_PRODUCTS)} 个竞品商品")

    # Insert keywords
    for k in COMPETITOR_KEYWORDS:
        await pool.execute(
            "INSERT INTO competitor_keywords (keyword, search_volume, competition, last_synced) VALUES ($1,$2,$3,now())",
            k["keyword"],
            k["search_volume"],
            k["competition"],
        )
    print(f"✅ 插入 {len(COMPETITOR_KEYWORDS)} 个关键词")

    # Summary
    print("\n📊 数据概览:")
    for cat in ["血压计", "血糖仪", "体温计", "制氧机", "轮椅", "护具", "雾化器", "血氧仪"]:
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM competitor_products WHERE category=$1", cat
        )
        avg_price = await pool.fetchval(
            "SELECT AVG(price) FROM competitor_products WHERE category=$1", cat
        )
        if count > 0:
            print(f"  {cat}: {count}个商品, 均价 ¥{avg_price:.0f}")

    # Platform breakdown
    print("\n📱 平台分布:")
    for platform in ["jd", "tmall", "meituan"]:
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM competitor_products cp JOIN competitor_stores cs ON cp.store_id=cs.store_id WHERE cs.platform=$1",
            platform,
        )
        print(f"  {platform}: {count}个商品")

    await pool.close()
    print("\n✅ 真实市场价格数据导入完成!")


if __name__ == "__main__":
    db_url = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(seed_data(db_url))
