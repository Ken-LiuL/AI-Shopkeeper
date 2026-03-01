#!/usr/bin/env python3
"""最终验证3个问题的修复状态"""

import asyncio
import time

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


async def test_all_fixes():
    """验证所有3个问题的修复状态"""

    print("🔧 验证3个问题的修复状态")
    print(f"🌐 Base URL: {BASE_URL}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=90.0) as client:
        results = {}

        # 测试1: inventory/overview active_products 问题
        print("1️⃣ 测试 inventory/overview active_products 修复")
        try:
            response = await client.get(f"{BASE_URL}/api/inventory/overview")
            if response.status_code == 200:
                data = response.json()["data"]
                active_products = data.get("active_products", 0)
                total_products = data.get("total_products", 0)

                print(f"   总商品数: {total_products}")
                print(f"   在售商品数: {active_products}")

                if active_products > 0:
                    print(f"   ✅ 问题1已修复! active_products = {active_products}")
                    results["problem1"] = "FIXED"
                else:
                    print("   ❌ 问题1未修复: active_products 仍为 0")
                    results["problem1"] = "NOT_FIXED"
            else:
                print(f"   ❌ API错误: {response.status_code}")
                results["problem1"] = "ERROR"
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            results["problem1"] = "ERROR"

        print()

        # 测试2: restock-suggestions 性能优化
        print("2️⃣ 测试 restock-suggestions 性能优化")
        try:
            start_time = time.time()
            response = await client.get(f"{BASE_URL}/api/inventory/restock-suggestions?limit=20")
            end_time = time.time()

            duration = end_time - start_time
            print(f"   请求耗时: {duration:.2f}秒")

            if response.status_code == 200:
                data = response.json()["data"]
                suggestions_count = len(data)
                print(f"   返回补货建议: {suggestions_count} 个")

                if duration < 10:
                    print(f"   ✅ 问题2已修复! 性能良好 ({duration:.2f}秒)")
                    results["problem2"] = "FIXED"
                elif duration < 30:
                    print(f"   ⚠️  问题2部分修复: 性能尚可 ({duration:.2f}秒)")
                    results["problem2"] = "PARTIAL"
                else:
                    print(f"   ❌ 问题2未修复: 仍然过慢 ({duration:.2f}秒)")
                    results["problem2"] = "NOT_FIXED"
            else:
                print(f"   ❌ API错误: {response.status_code}")
                results["problem2"] = "ERROR"
        except TimeoutError:
            print("   ❌ 问题2未修复: 请求仍然超时")
            results["problem2"] = "NOT_FIXED"
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            results["problem2"] = "ERROR"

        print()

        # 测试3: pricing margin 修复
        print("3️⃣ 测试 pricing margin 修复")
        try:
            response = await client.get(f"{BASE_URL}/api/products/pricing")
            if response.status_code == 200:
                data = response.json()["data"]

                # 检查数据源说明
                data_source_note = data.get("data_source_note", "")
                if data_source_note:
                    print(f"   数据源说明: {data_source_note}")

                # 检查category_analysis中的margin
                category_analysis = data.get("category_analysis", [])
                print(f"   获取到 {len(category_analysis)} 个品类分析")

                non_zero_margins = 0
                total_with_margin = 0

                for category in category_analysis[:5]:
                    margin = category.get("avg_margin_percent", 0)
                    category_name = category.get("category", "未知")[:30]
                    print(f"   品类 '{category_name}': 利润率 = {margin}%")

                    if margin > 0:
                        non_zero_margins += 1
                    total_with_margin += 1

                if non_zero_margins > 0:
                    print(
                        f"   ✅ 问题3已修复! {non_zero_margins}/{total_with_margin} 个品类有非零利润率"
                    )
                    results["problem3"] = "FIXED"
                else:
                    print("   ❌ 问题3未修复: 所有利润率仍为0%")
                    results["problem3"] = "NOT_FIXED"

            else:
                print(f"   ❌ API错误: {response.status_code}")
                results["problem3"] = "ERROR"
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            results["problem3"] = "ERROR"

        print()
        print("=" * 70)

        # 汇总结果
        print("🏁 修复结果汇总:")
        print("=" * 70)

        fixed_count = 0
        total_problems = 3

        for problem, status in results.items():
            if status == "FIXED":
                print(f"✅ {problem}: 已修复")
                fixed_count += 1
            elif status == "PARTIAL":
                print(f"⚠️  {problem}: 部分修复")
                fixed_count += 0.5
            elif status == "NOT_FIXED":
                print(f"❌ {problem}: 未修复")
            else:
                print(f"⚡ {problem}: 测试出错")

        print(f"\n修复进度: {fixed_count}/{total_problems} 个问题")

        if fixed_count == total_problems:
            print("🎉 所有问题已完全修复!")
        elif fixed_count > 0:
            print(f"🔧 已修复 {fixed_count} 个问题，还需继续优化")
        else:
            print("😅 所有问题仍需修复")


if __name__ == "__main__":
    asyncio.run(test_all_fixes())
