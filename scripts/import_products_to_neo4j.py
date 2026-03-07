#!/usr/bin/env python3
"""
Import all products from PostgreSQL to Neo4j knowledge graph.

Creates:
  - Product nodes (product_id, name, category, brand, description, retail_price, monthly_sales, stock)
  - Population nodes (7 groups)
  - SAME_CATEGORY relationships (products in same category)
  - SUITABLE_FOR / CONTRAINDICATED_FOR relationships (inferred from category)

Usage (inside aishop-app container):
    python3 scripts/import_products_to_neo4j.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import psycopg2
import psycopg2.extras
from neo4j import GraphDatabase

# ── Config from env ──────────────────────────────────────────────────────────

PG_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:aishop2026@postgres:5432/ai_store")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "aishop2026neo4j")

BATCH_SIZE = 100

# ── Population 节点定义 ────────────────────────────────────────────────────────

POPULATIONS = [
    {"name": "老人", "description": "60岁及以上老年群体，需注意用药安全和操作便捷性"},
    {"name": "孕妇", "description": "妊娠期女性，用药需格外谨慎"},
    {"name": "婴儿", "description": "0-3岁婴幼儿，需使用专用产品"},
    {"name": "高血压患者", "description": "确诊高血压需长期监测和管理的患者"},
    {"name": "糖尿病患者", "description": "确诊糖尿病需长期血糖监测和管理的患者"},
    {"name": "术后康复", "description": "手术后需要护理和康复的患者"},
    {"name": "慢性病患者", "description": "需要长期用药和监测的慢性病人群"},
]

# ── 分类 → 适用/禁用人群映射 ─────────────────────────────────────────────────

CATEGORY_SUITABLE: dict[str, list[str]] = {
    "血压检测": ["高血压患者", "老人", "慢性病患者"],
    "血糖检测": ["糖尿病患者", "老人", "慢性病患者"],
    "制氧机": ["老人", "慢性病患者", "术后康复"],
    "雾化器": ["婴儿", "老人"],
    "体温检测": ["婴儿", "老人", "孕妇"],
    "孕期检测": ["孕妇"],
    "婴儿用品": ["婴儿"],
    "宝妈用品": ["孕妇"],
    "儿童保健": ["婴儿"],
    "十月结晶": ["孕妇"],
    "胎心检测": ["孕妇"],
    "女性健康": ["孕妇"],
    "轮椅": ["老人", "术后康复"],
    "拐杖助行器": ["老人", "术后康复"],
    "病床护理": ["老人", "术后康复", "慢性病患者"],
    "造口护理": ["术后康复"],
    "成人护理": ["老人"],
    "腰部护具": ["老人", "术后康复"],
    "腿部护具": ["老人", "术后康复"],
    "手部护具": ["老人", "术后康复"],
    "颈部护具": ["老人", "术后康复"],
    "胸背护具": ["老人", "术后康复"],
    "创伤急救": ["老人", "术后康复"],
    "改善睡眠": ["老人", "慢性病患者"],
    "增强免疫力": ["老人", "慢性病患者"],
    "保健食品": ["老人", "慢性病患者"],
    "维生素": ["老人", "孕妇"],
    "尿酸检测": ["慢性病患者", "老人"],
    "血氧检测": ["老人", "慢性病患者", "术后康复"],
    "其他检测": ["老人", "慢性病患者"],
    "艾灸针灸": ["老人", "慢性病患者"],
    "神灯理疗": ["老人", "慢性病患者"],
    "护肝解酒": ["慢性病患者"],
    "润肠健胃": ["老人", "慢性病患者"],
    "姜茶暖宫": ["孕妇", "女性健康"],
    "热敷暖宫": ["孕妇"],
}

CATEGORY_CONTRAINDICATED: dict[str, list[tuple[str, str]]] = {
    "避孕套": [("孕妇", "孕期不适用")],
    "男用延时": [("孕妇", "孕期慎用")],
    "润滑液喷剂": [("婴儿", "婴儿禁用")],
    "杀菌消毒": [("婴儿", "需稀释后使用，婴儿皮肤慎用")],
    "净痘脱毛": [("婴儿", "婴儿禁用"), ("孕妇", "孕期慎用")],
    "男性健康": [("婴儿", "仅成人使用")],
    "女用快感": [("婴儿", "仅成人使用")],
    "幽门螺杆菌检测": [("婴儿", "不适用")],
    "HPV检测": [("婴儿", "不适用")],
    "艾滋TP检测": [("婴儿", "不适用")],
    "养生茶饮": [("婴儿", "婴儿禁用")],
    "护肝解酒": [("孕妇", "孕期禁用"), ("婴儿", "婴儿禁用")],
    "活血化瘀": [("孕妇", "孕期慎用")],
}


def create_populations(session: Any) -> None:
    """创建/更新 Population 节点。"""
    print("Creating Population nodes...")
    for pop in POPULATIONS:
        session.run(
            "MERGE (p:Population {name: $name}) SET p.description = $description",
            name=pop["name"],
            description=pop["description"],
        )
    print(f"  ✓ {len(POPULATIONS)} Population nodes created/updated")


def import_products_batch(session: Any, products: list[dict]) -> int:
    """批量导入 Product 节点，返回成功数量。"""
    query = """
    UNWIND $products AS p
    MERGE (n:Product {product_id: p.product_id})
    SET n.name = p.name,
        n.category = p.category,
        n.brand = p.brand,
        n.description = p.description,
        n.retail_price = p.retail_price,
        n.monthly_sales = p.monthly_sales,
        n.stock = p.stock,
        n.status = p.status
    RETURN count(n) AS cnt
    """
    result = session.run(query, products=products)
    record = result.single()
    return record["cnt"] if record else 0


def create_same_category_relationships(session: Any) -> int:
    """为同类商品创建 SAME_CATEGORY 关系（按类目聚合）。"""
    print("Creating SAME_CATEGORY relationships...")
    # 按分类匹配，但避免自连接，且只创建单向关系（避免组合爆炸，每类最多取前50个商品互联）
    query = """
    MATCH (a:Product), (b:Product)
    WHERE a.category = b.category
      AND a.product_id < b.product_id
      AND a.category IS NOT NULL
    WITH a, b
    LIMIT 50000
    MERGE (a)-[:SAME_CATEGORY]->(b)
    RETURN count(*) AS cnt
    """
    result = session.run(query)
    record = result.single()
    cnt = record["cnt"] if record else 0
    print(f"  ✓ {cnt} SAME_CATEGORY relationships created")
    return cnt


def create_population_relationships(session: Any) -> tuple[int, int]:
    """创建 SUITABLE_FOR 和 CONTRAINDICATED_FOR 关系。"""
    print("Creating SUITABLE_FOR / CONTRAINDICATED_FOR relationships...")
    suitable_cnt = 0
    contra_cnt = 0

    for category, populations in CATEGORY_SUITABLE.items():
        for pop_name in populations:
            result = session.run(
                """
                MATCH (p:Product {category: $category}), (pop:Population {name: $pop_name})
                MERGE (p)-[:SUITABLE_FOR]->(pop)
                RETURN count(*) AS cnt
                """,
                category=category,
                pop_name=pop_name,
            )
            record = result.single()
            suitable_cnt += record["cnt"] if record else 0

    for category, contra_list in CATEGORY_CONTRAINDICATED.items():
        for pop_name, reason in contra_list:
            result = session.run(
                """
                MATCH (p:Product {category: $category}), (pop:Population {name: $pop_name})
                MERGE (p)-[r:CONTRAINDICATED_FOR]->(pop)
                SET r.reason = $reason
                RETURN count(*) AS cnt
                """,
                category=category,
                pop_name=pop_name,
                reason=reason,
            )
            record = result.single()
            contra_cnt += record["cnt"] if record else 0

    print(f"  ✓ {suitable_cnt} SUITABLE_FOR relationships created")
    print(f"  ✓ {contra_cnt} CONTRAINDICATED_FOR relationships created")
    return suitable_cnt, contra_cnt


def main() -> None:
    print("=" * 60)
    print("AI-Shopkeeper: PostgreSQL → Neo4j Product Import")
    print("=" * 60)

    # ── Connect to PostgreSQL ──────────────────────────────────────
    print(f"\nConnecting to PostgreSQL: {PG_DSN[:40]}...")
    pg_conn = psycopg2.connect(PG_DSN)
    pg_cursor = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── Connect to Neo4j ───────────────────────────────────────────
    print(f"Connecting to Neo4j: {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    try:
        with driver.session() as neo4j_session:
            # Step 1: Create Population nodes
            create_populations(neo4j_session)

            # Step 2: Fetch and import products in batches
            pg_cursor.execute(
                "SELECT COUNT(*) FROM products WHERE status='active'"
            )
            total = pg_cursor.fetchone()["count"]
            print(f"\nImporting {total} active products in batches of {BATCH_SIZE}...")

            imported = 0
            offset = 0
            start_time = time.time()

            while offset < total:
                pg_cursor.execute(
                    """
                    SELECT product_id, name, category, brand, description,
                           CAST(retail_price AS FLOAT) AS retail_price,
                           monthly_sales, stock, status
                    FROM products
                    WHERE status = 'active'
                    ORDER BY product_id
                    LIMIT %s OFFSET %s
                    """,
                    (BATCH_SIZE, offset),
                )
                rows = pg_cursor.fetchall()
                if not rows:
                    break

                # Convert RealDictRow to plain dict
                batch = []
                for row in rows:
                    d = dict(row)
                    # Ensure no None for required fields
                    d["name"] = d["name"] or ""
                    d["category"] = d["category"] or "未分类"
                    d["brand"] = d["brand"] or ""
                    d["description"] = d["description"] or ""
                    d["retail_price"] = d["retail_price"] or 0.0
                    d["monthly_sales"] = d["monthly_sales"] or 0
                    d["stock"] = d["stock"] or 0
                    batch.append(d)

                cnt = import_products_batch(neo4j_session, batch)
                imported += cnt
                offset += BATCH_SIZE

                elapsed = time.time() - start_time
                pct = min(100, offset / total * 100)
                print(f"  Progress: {offset}/{total} ({pct:.1f}%) | Imported: {imported} | {elapsed:.1f}s elapsed")

            print(f"\n✓ Product import complete: {imported} nodes created/updated")

            # Step 3: SAME_CATEGORY relationships
            same_cat_cnt = create_same_category_relationships(neo4j_session)

            # Step 4: Population relationships
            suitable_cnt, contra_cnt = create_population_relationships(neo4j_session)

            # Step 5: Verify counts
            print("\n" + "=" * 60)
            print("Verification:")
            r = neo4j_session.run("MATCH (n:Product) RETURN count(n) AS cnt").single()
            print(f"  Product nodes:              {r['cnt']}")
            r = neo4j_session.run("MATCH (n:Population) RETURN count(n) AS cnt").single()
            print(f"  Population nodes:           {r['cnt']}")
            r = neo4j_session.run("MATCH ()-[r:SAME_CATEGORY]->() RETURN count(r) AS cnt").single()
            print(f"  SAME_CATEGORY relationships: {r['cnt']}")
            r = neo4j_session.run("MATCH ()-[r:SUITABLE_FOR]->() RETURN count(r) AS cnt").single()
            print(f"  SUITABLE_FOR relationships:  {r['cnt']}")
            r = neo4j_session.run("MATCH ()-[r:CONTRAINDICATED_FOR]->() RETURN count(r) AS cnt").single()
            print(f"  CONTRAINDICATED_FOR:         {r['cnt']}")
            print("=" * 60)

    finally:
        pg_cursor.close()
        pg_conn.close()
        driver.close()

    print("\n✅ Import complete!")


if __name__ == "__main__":
    main()
