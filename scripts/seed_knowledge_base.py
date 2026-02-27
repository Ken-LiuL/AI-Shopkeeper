#!/usr/bin/env python3
"""
种子数据导入脚本 - 客服知识库

用法:
  python scripts/seed_knowledge_base.py          # 导入到本地数据库
  python scripts/seed_knowledge_base.py --remote # 导入到生产数据库
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import asyncpg
import click

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.postgres import get_connection_pool

logger = logging.getLogger(__name__)


async def load_seed_data(file_path: Path) -> list[dict]:
    """加载种子数据文件."""
    if not file_path.exists():
        raise FileNotFoundError(f"种子数据文件不存在: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"加载了 {len(data)} 条知识库记录")
    return data


async def clear_existing_data(pool: asyncpg.Pool) -> None:
    """清空现有知识库数据."""
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM knowledge_base")
        logger.info(f"清空现有数据，删除了 {result.split()[-1]} 条记录")


async def insert_knowledge_base_records(pool: asyncpg.Pool, records: list[dict]) -> None:
    """批量插入知识库记录."""
    insert_query = """
        INSERT INTO knowledge_base (
            category, subcategory, question, answer, keywords,
            priority, product_categories, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
    """

    async with pool.acquire() as conn:
        async with conn.transaction():
            for record in records:
                await conn.execute(
                    insert_query,
                    record["category"],
                    record.get("subcategory"),
                    record.get("question"),
                    record["answer"],
                    record.get("keywords", []),
                    record.get("priority", 0),
                    record.get("product_categories", []),
                )

    logger.info(f"成功插入 {len(records)} 条知识库记录")


async def validate_data(records: list[dict]) -> list[dict]:
    """验证数据格式."""
    valid_categories = {"faq", "usage_guide", "policy", "compliance"}
    valid_records = []

    for i, record in enumerate(records):
        try:
            # 检查必填字段
            if not record.get("category"):
                logger.warning(f"记录 {i}: 缺少 category 字段")
                continue

            if not record.get("answer"):
                logger.warning(f"记录 {i}: 缺少 answer 字段")
                continue

            # 检查 category 有效性
            if record["category"] not in valid_categories:
                logger.warning(f"记录 {i}: 无效的 category '{record['category']}'")
                continue

            # 检查回答长度
            if len(record["answer"]) > 500:
                logger.warning(f"记录 {i}: 回答过长 ({len(record['answer'])} 字符)")

            # 检查关键词
            keywords = record.get("keywords", [])
            if not isinstance(keywords, list):
                logger.warning(f"记录 {i}: keywords 应该是列表格式")
                record["keywords"] = []

            # 检查产品分类
            categories = record.get("product_categories", [])
            if not isinstance(categories, list):
                logger.warning(f"记录 {i}: product_categories 应该是列表格式")
                record["product_categories"] = []

            valid_records.append(record)

        except Exception as e:
            logger.error(f"记录 {i} 验证失败: {e}")
            continue

    logger.info(f"验证完成，有效记录 {len(valid_records)}/{len(records)}")
    return valid_records


async def show_statistics(pool: asyncpg.Pool) -> None:
    """显示导入统计信息."""
    async with pool.acquire() as conn:
        # 总数统计
        total = await conn.fetchval("SELECT COUNT(*) FROM knowledge_base")
        logger.info(f"知识库总记录数: {total}")

        # 按分类统计
        category_stats = await conn.fetch("""
            SELECT category, COUNT(*) as count
            FROM knowledge_base
            GROUP BY category
            ORDER BY count DESC
        """)

        logger.info("分类统计:")
        for row in category_stats:
            logger.info(f"  {row['category']}: {row['count']} 条")

        # 按产品品类统计
        category_stats = await conn.fetch("""
            SELECT
                unnest(product_categories) as product_category,
                COUNT(*) as count
            FROM knowledge_base
            WHERE product_categories != '{}'
            GROUP BY product_category
            ORDER BY count DESC
            LIMIT 10
        """)

        if category_stats:
            logger.info("热门产品品类:")
            for row in category_stats:
                logger.info(f"  {row['product_category']}: {row['count']} 条")


@click.command()
@click.option("--remote", is_flag=True, help="导入到生产数据库")
@click.option("--clear", is_flag=True, help="清空现有数据")
@click.option("--file", "-f", default="data/knowledge_base_seed.json", help="种子数据文件路径")
def main(remote: bool, clear: bool, file: str):
    """导入客服知识库种子数据."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    async def run():
        # 获取配置
        if remote:
            logger.info("使用生产数据库配置")
            # 这里可以切换到生产环境配置
        else:
            logger.info("使用本地数据库配置")

        # 加载数据
        seed_file = Path(file)
        if not seed_file.is_absolute():
            seed_file = Path(__file__).parent.parent / seed_file

        records = await load_seed_data(seed_file)

        # 验证数据
        valid_records = await validate_data(records)
        if not valid_records:
            logger.error("没有有效的记录可以导入")
            return

        # 连接数据库
        try:
            pool = await get_connection_pool()
            logger.info("数据库连接成功")
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return

        try:
            # 清空现有数据（如果指定）
            if clear:
                await clear_existing_data(pool)

            # 插入数据
            await insert_knowledge_base_records(pool, valid_records)

            # 显示统计
            await show_statistics(pool)

            logger.info("知识库种子数据导入完成 ✅")

        except Exception as e:
            logger.error(f"导入失败: {e}")
        finally:
            await pool.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
