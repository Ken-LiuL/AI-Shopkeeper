#!/usr/bin/env python3
"""检查竞品数据表中的真实数据情况"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

from src.db.postgres import get_pool, init_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def check_competitor_data():
    """检查竞品表数据情况"""
    await init_pool()
    pool = get_pool()

    tables = {
        "competitor_stores": "竞品店铺",
        "competitor_products": "竞品商品",
        "competitor_keywords": "关键词数据",
    }

    print("=== 竞品数据表检查 ===\n")

    for table_name, desc in tables.items():
        try:
            total = await pool.fetchval(f"SELECT COUNT(*) FROM {table_name}")
            recent = await pool.fetchval(f"""
                SELECT COUNT(*) FROM {table_name}
                WHERE last_synced >= NOW() - INTERVAL '7 days'
            """)

            print(f"📊 {desc} ({table_name}):")
            print(f"   总数据量: {total}")
            print(f"   近7天数据: {recent}")

            if total > 0:
                # 显示样本数据
                sample = await pool.fetchrow(f"SELECT * FROM {table_name} LIMIT 1")
                print(f"   样本数据: {dict(sample)}")
                print()
            else:
                print("   ❌ 表为空 - 需要生成真实数据源")
                print()

        except Exception as e:
            print(f"❌ {desc}: 查询失败 - {e}\n")

    # 检查主产品表
    try:
        product_count = await pool.fetchval(
            "SELECT COUNT(*) FROM qnh_products WHERE retail_price > 0"
        )
        print(f"📦 产品数据 (qnh_products): {product_count} 个有价格商品")
    except Exception as e:
        print(f"❌ 产品表查询失败: {e}")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(check_competitor_data())
