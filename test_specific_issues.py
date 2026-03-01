#!/usr/bin/env python3
"""测试3个具体问题"""

import asyncio
import time

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


async def test_specific_issues():
    """测试3个具体问题"""

    print("🧪 测试3个具体问题")
    print(f"🌐 Base URL: {BASE_URL}")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 问题1: inventory/overview active_products=0
        print("1️⃣ 问题1: inventory/overview active_products=0")
        try:
            response = await client.get(f"{BASE_URL}/api/inventory/overview")
            if response.status_code == 200:
                data = response.json()
                inventory_data = data.get("data", {})
                active_products = inventory_data.get("active_products", 0)
                total_products = inventory_data.get("total_products", 0)

                print(f"   总商品数: {total_products}")
                print(f"   在售商品数: {active_products}")

                if active_products == 0:
                    print("   ❌ 问题1仍然存在: active_products = 0")
                else:
                    print(f"   ✅ 问题1已修复: active_products = {active_products}")
            else:
                print(f"   ❌ API错误: {response.status_code}")
        except Exception as e:
            print(f"   ❌ 请求失败: {e}")

        print()

        # 问题2: restock-suggestions 超时
        print("2️⃣ 问题2: /api/inventory/restock-suggestions 超时")
        try:
            start_time = time.time()
            response = await client.get(f"{BASE_URL}/api/inventory/restock-suggestions")
            end_time = time.time()

            duration = end_time - start_time
            print(f"   请求耗时: {duration:.2f}秒")

            if response.status_code == 200:
                data = response.json()
                suggestions = data.get("data", [])
                print(f"   ✅ 返回 {len(suggestions)} 个补货建议")

                if duration > 30:
                    print(f"   ⚠️  性能问题: 耗时 {duration:.2f}秒，过慢")
                elif duration > 10:
                    print(f"   ⚠️  轻微慢: 耗时 {duration:.2f}秒，可接受")
                else:
                    print(f"   ✅ 性能良好: 耗时 {duration:.2f}秒")
            else:
                print(f"   ❌ API错误: {response.status_code} - {response.text[:200]}")
        except TimeoutError:
            print("   ❌ 问题2仍然存在: 请求超时(60秒)")
        except Exception as e:
            print(f"   ❌ 请求失败: {e}")

        print()

        # 问题3: pricing margin 全0
        print("3️⃣ 问题3: pricing margin 全0")
        try:
            response = await client.get(f"{BASE_URL}/api/products/pricing")
            if response.status_code == 200:
                data = response.json()
                pricing_data = data.get("data", {})
                category_analysis = pricing_data.get("category_analysis", [])

                print(f"   获取到 {len(category_analysis)} 个品类的分析")

                # 检查是否所有margin都是0
                all_zero_margin = True
                has_margin_data = False

                for category in category_analysis[:5]:  # 检查前5个品类
                    margin = category.get("avg_margin_percent", 0)
                    print(f"   品类 '{category.get('category')}': 平均利润率 = {margin}%")

                    if margin != 0:
                        all_zero_margin = False
                    if margin is not None:
                        has_margin_data = True

                if not has_margin_data:
                    print("   ❌ 问题3: 没有利润率数据")
                elif all_zero_margin:
                    print("   ❌ 问题3仍然存在: 所有利润率都是0%")
                else:
                    print("   ✅ 问题3已修复: 有非零利润率数据")

            else:
                print(f"   ❌ API错误: {response.status_code}")
        except Exception as e:
            print(f"   ❌ 请求失败: {e}")

        print()
        print("=" * 60)
        print("🏁 测试完成!")


if __name__ == "__main__":
    asyncio.run(test_specific_issues())
