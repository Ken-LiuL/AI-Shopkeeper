"""Category Mapping ETL — 从已上架商品 + QNH 分类 API 构建类目映射表。

数据来源:
  1. qnh_products 表的 category 字段（已上架商品的实际平台类目）
  2. QNH storeCategory API（商家配置的分类树）
  3. competitor_products 表的类目（竞品参考）

输出:
  category_mapping 表 — 供上架 Agent 匹配新商品类目
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def ensure_tables(pool: asyncpg.Pool) -> None:
    """确保类目映射相关表存在。"""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS category_mapping (
            id SERIAL PRIMARY KEY,
            category_name TEXT NOT NULL,
            source TEXT NOT NULL,           -- 'product' | 'store_api' | 'competitor'
            parent_category TEXT,
            product_count INT DEFAULT 0,
            sample_products TEXT[],         -- 该类目下的示例商品名
            keywords TEXT[],               -- 关联关键词（用于匹配新商品）
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(category_name, source)
        );

        CREATE TABLE IF NOT EXISTS store_category_tree (
            id SERIAL PRIMARY KEY,
            category_id TEXT,
            category_name TEXT NOT NULL,
            parent_id TEXT,
            parent_name TEXT,
            level INT DEFAULT 1,
            raw_data JSONB,
            synced_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(category_id)
        );
    """)


async def extract_from_products(pool: asyncpg.Pool) -> int:
    """从 qnh_products 表提取所有已用类目 + 示例商品 + 关键词。"""
    rows = await pool.fetch("""
        SELECT
            category,
            COUNT(*) as cnt,
            ARRAY_AGG(DISTINCT name ORDER BY name) FILTER (WHERE name IS NOT NULL) as samples
        FROM qnh_products
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category
        ORDER BY cnt DESC
    """)

    count = 0
    for row in rows:
        cat = row["category"].strip()
        if not cat:
            continue

        samples = (row["samples"] or [])[:5]  # 最多 5 个示例

        # 从类目名和示例商品中提取关键词
        keywords = _extract_keywords(cat, samples)

        await pool.execute("""
            INSERT INTO category_mapping
                (category_name, source, product_count, sample_products, keywords, updated_at)
            VALUES ($1, 'product', $2, $3, $4, NOW())
            ON CONFLICT (category_name, source) DO UPDATE SET
                product_count = EXCLUDED.product_count,
                sample_products = EXCLUDED.sample_products,
                keywords = EXCLUDED.keywords,
                updated_at = NOW()
        """, cat, row["cnt"], samples, keywords)
        count += 1

    return count


async def extract_from_competitors(pool: asyncpg.Pool) -> int:
    """从竞品商品表提取类目参考。"""
    # 检查表是否存在
    exists = await pool.fetchval("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'competitor_products'
        )
    """)
    if not exists:
        logger.info("competitor_products 表不存在，跳过竞品类目提取")
        return 0

    rows = await pool.fetch("""
        SELECT
            category,
            COUNT(*) as cnt,
            ARRAY_AGG(DISTINCT product_name ORDER BY product_name) FILTER (
                WHERE product_name IS NOT NULL
            ) as samples
        FROM competitor_products
        WHERE category IS NOT NULL AND category != ''
        GROUP BY category
        ORDER BY cnt DESC
    """)

    count = 0
    for row in rows:
        cat = row["category"].strip()
        if not cat:
            continue

        samples = (row["samples"] or [])[:5]
        keywords = _extract_keywords(cat, samples)

        await pool.execute("""
            INSERT INTO category_mapping
                (category_name, source, product_count, sample_products, keywords, updated_at)
            VALUES ($1, 'competitor', $2, $3, $4, NOW())
            ON CONFLICT (category_name, source) DO UPDATE SET
                product_count = EXCLUDED.product_count,
                sample_products = EXCLUDED.sample_products,
                keywords = EXCLUDED.keywords,
                updated_at = NOW()
        """, cat, row["cnt"], samples, keywords)
        count += 1

    return count


async def sync_store_categories(pool: asyncpg.Pool, client: Any | None = None) -> int:
    """从 QNH storeCategory API 同步分类树。

    如果 client 为 None，跳过 API 调用。
    """
    if client is None:
        logger.info("无 QNH client，跳过 storeCategory API 同步")
        return 0

    try:
        categories = await client.get_store_categories()
    except Exception as e:
        logger.warning("storeCategory API 调用失败: %s", e)
        return 0

    count = 0
    for cat in categories:
        cat_id = str(cat.get("id", cat.get("categoryId", "")))
        cat_name = cat.get("name", cat.get("categoryName", ""))
        parent_id = str(cat.get("parentId", "")) or None
        parent_name = cat.get("parentName", "") or None
        level = cat.get("level", 1)

        if not cat_name:
            continue

        await pool.execute("""
            INSERT INTO store_category_tree
                (category_id, category_name, parent_id, parent_name, level, raw_data, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (category_id) DO UPDATE SET
                category_name = EXCLUDED.category_name,
                parent_id = EXCLUDED.parent_id,
                parent_name = EXCLUDED.parent_name,
                level = EXCLUDED.level,
                raw_data = EXCLUDED.raw_data,
                synced_at = NOW()
        """, cat_id, cat_name, parent_id, parent_name, level,
            json.dumps(cat, ensure_ascii=False, default=str))

        # 也写入 category_mapping
        await pool.execute("""
            INSERT INTO category_mapping
                (category_name, source, parent_category, updated_at)
            VALUES ($1, 'store_api', $2, NOW())
            ON CONFLICT (category_name, source) DO UPDATE SET
                parent_category = EXCLUDED.parent_category,
                updated_at = NOW()
        """, cat_name, parent_name)

        count += 1

        # 递归处理子分类
        children = cat.get("children", cat.get("subCategories", []))
        if children:
            for child in children:
                child["parentId"] = cat_id
                child["parentName"] = cat_name
                child["level"] = level + 1
            # 扁平化处理
            categories.extend(children)

    return count


async def run_category_mapping_etl(pool: asyncpg.Pool, qnh_client: Any | None = None) -> dict:
    """执行完整的类目映射 ETL。"""
    await ensure_tables(pool)

    results = {}

    # 1. 从已上架商品提取
    try:
        results["from_products"] = await extract_from_products(pool)
        logger.info("从商品表提取 %d 个类目", results["from_products"])
    except Exception as e:
        logger.error("商品类目提取失败: %s", e)
        results["from_products"] = 0

    # 2. 从竞品提取
    try:
        results["from_competitors"] = await extract_from_competitors(pool)
        logger.info("从竞品表提取 %d 个类目", results["from_competitors"])
    except Exception as e:
        logger.error("竞品类目提取失败: %s", e)
        results["from_competitors"] = 0

    # 3. 从 QNH API 同步
    try:
        results["from_store_api"] = await sync_store_categories(pool, qnh_client)
        logger.info("从 storeCategory API 同步 %d 个类目", results["from_store_api"])
    except Exception as e:
        logger.error("storeCategory API 同步失败: %s", e)
        results["from_store_api"] = 0

    total = sum(results.values())
    logger.info("类目映射 ETL 完成: 共 %d 个类目 (%s)", total, results)
    results["total"] = total
    return results


def _extract_keywords(category_name: str, sample_products: list[str]) -> list[str]:
    """从类目名和示例商品中提取关键词。"""
    keywords = set()

    # 从类目名提取
    keywords.add(category_name)
    # 拆分常见分隔符
    for sep in ["/", ">", "-", "·", "、"]:
        if sep in category_name:
            keywords.update(part.strip() for part in category_name.split(sep) if part.strip())

    # 药品类目常见关键词映射
    pharma_keywords = {
        "感冒": ["感冒", "流感", "发热", "退烧"],
        "止痛": ["止痛", "镇痛", "头痛", "牙痛"],
        "消化": ["消化", "胃", "肠", "腹泻", "便秘"],
        "心血管": ["降压", "心脏", "血压", "心血管"],
        "皮肤": ["皮肤", "外用", "软膏", "湿疹"],
        "眼科": ["眼", "滴眼", "近视"],
        "维生素": ["维生素", "补充剂", "钙", "铁", "锌"],
        "医疗器械": ["血糖仪", "体温计", "血压计", "试纸"],
        "中药": ["中药", "中成药", "颗粒", "丸"],
        "抗生素": ["抗生素", "消炎", "头孢", "阿莫西林"],
        "儿科": ["儿童", "小儿", "婴幼儿"],
        "妇科": ["妇科", "妇炎", "经期"],
        "防护": ["口罩", "消毒", "防护", "酒精"],
        "保健": ["保健", "营养", "滋补"],
    }

    cat_lower = category_name.lower()
    for _group, kws in pharma_keywords.items():
        if any(k in cat_lower for k in kws):
            keywords.update(kws)

    # 从示例商品提取（取前 3 个字作为关键词）
    for prod in (sample_products or [])[:3]:
        if prod and len(prod) >= 2:
            keywords.add(prod[:4] if len(prod) >= 4 else prod)

    return sorted(keywords)[:20]  # 最多 20 个关键词
