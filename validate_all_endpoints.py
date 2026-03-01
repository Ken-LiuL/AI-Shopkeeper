#!/usr/bin/env python3
"""验证所有相关端点的工作状态"""

import asyncio
import time

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


async def detailed_validation():
    """详细验证所有相关端点"""

    print("🔍 详细验证所有相关端点")
    print(f"🌐 Base URL: {BASE_URL}")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. 验证 inventory/overview
        print("1️⃣ 验证 inventory/overview 详细数据")
        try:
            response = await client.get(f"{BASE_URL}/api/inventory/overview")
            if response.status_code == 200:
                data = response.json()["data"]
                print(f"   ✅ 总商品数: {data.get('total_products')}")
                print(f"   ✅ 在售商品数: {data.get('active_products')}")
                print(f"   ✅ 总库存: {data.get('total_stock')}")
                print(f"   ✅ 缺货数: {data.get('out_of_stock_count')}")
                print(f"   ✅ 品类数: {len(data.get('category_breakdown', []))}")

                # 检查品类数据
                categories = data.get("category_breakdown", [])[:3]
                for cat in categories:
                    print(
                        f"      - {cat.get('category')}: {cat.get('active_count')}在售/{cat.get('product_count')}总数"
                    )
            else:
                print(f"   ❌ 失败: {response.status_code}")
        except Exception as e:
            print(f"   ❌ 异常: {e}")

        print()

        # 2. 验证 restock-suggestions 不同参数
        print("2️⃣ 验证 restock-suggestions 不同参数")

        # 测试默认参数
        try:
            start_time = time.time()
            response = await client.get(f"{BASE_URL}/api/inventory/restock-suggestions?limit=10")
            duration = time.time() - start_time

            if response.status_code == 200:
                data = response.json()["data"]
                print(f"   ✅ 默认参数 (limit=10): {len(data)}个建议, 耗时{duration:.2f}秒")
            else:
                print(f"   ❌ 默认参数失败: {response.status_code}")
        except Exception as e:
            print(f"   ❌ 默认参数异常: {e}")

        # 测试更大limit
        try:
            start_time = time.time()
            response = await client.get(f"{BASE_URL}/api/inventory/restock-suggestions?limit=30")
            duration = time.time() - start_time

            if response.status_code == 200:
                data = response.json()["data"]
                print(f"   ✅ limit=30: {len(data)}个建议, 耗时{duration:.2f}秒")

                # 检查建议内容
                if data:
                    example = data[0]
                    print(
                        f"      示例建议: {example.get('name')[:30]}... 紧急度={example.get('urgency')}"
                    )
            else:
                print(f"   ❌ limit=30 失败: {response.status_code}")
        except Exception as e:
            print(f"   ❌ limit=30 异常: {e}")

        print()

        # 3. 验证 pricing 详细数据
        print("3️⃣ 验证 pricing 详细数据")
        try:
            response = await client.get(f"{BASE_URL}/api/products/pricing")
            if response.status_code == 200:
                data = response.json()["data"]

                print(f"   ✅ 数据源说明: {data.get('data_source_note')}")

                # 品类分析
                categories = data.get("category_analysis", [])
                print(f"   ✅ 品类分析: {len(categories)}个品类")

                # 检查是否有非零margin
                non_zero_count = 0
                for cat in categories[:10]:
                    margin = cat.get("avg_margin_percent", 0)
                    if margin > 0:
                        non_zero_count += 1
                        print(f"      - {cat.get('category')[:40]}: {margin}% margin")

                print(f"   ✅ 非零利润率品类: {non_zero_count}/{len(categories[:10])}")

                # 价格区间分析
                price_ranges = data.get("price_range_analysis", [])
                print(f"   ✅ 价格区间: {len(price_ranges)}个区间")
                for pr in price_ranges:
                    print(
                        f"      - {pr.get('price_range')}: {pr.get('product_count')}个商品, {pr.get('avg_margin_percent')}%利润率"
                    )

                # 定价建议
                suggestions = data.get("pricing_suggestions", [])
                print(f"   ✅ 定价建议: {len(suggestions)}个")
                if suggestions:
                    example = suggestions[0]
                    print(
                        f"      示例: {example.get('name')[:30]}... {example.get('action')} {example.get('current_price')}→{example.get('suggested_price')}"
                    )

            else:
                print(f"   ❌ 失败: {response.status_code}")
        except Exception as e:
            print(f"   ❌ 异常: {e}")

        print()
        print("=" * 80)
        print("🏁 详细验证完成!")


if __name__ == "__main__":
    asyncio.run(detailed_validation())
