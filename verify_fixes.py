#!/usr/bin/env python3

import asyncio
import json

import aiohttp


async def test_fixed_endpoints():
    """测试修复后的三个API端点"""

    base_url = "https://ai-shopkeeper-kk.fly.dev"  # Fly.io 部署地址

    tests = [
        {
            "name": "问题1: GET /api/products/pricing",
            "url": f"{base_url}/api/products/pricing",
            "expected_status": 200,
            "expected_fields": ["category_analysis", "price_range_analysis", "pricing_suggestions"],
        },
        {
            "name": "问题2: GET /api/store/overview",
            "url": f"{base_url}/api/store/overview",
            "expected_status": 200,
            "expected_fields": ["stores", "total_gmv", "best_performer"],
        },
        {
            "name": "问题3: GET /api/inventory/overview",
            "url": f"{base_url}/api/inventory/overview",
            "expected_status": 200,
            "expected_fields": ["total_products", "total_stock", "category_breakdown"],
        },
    ]

    async with aiohttp.ClientSession() as session:
        results = []

        for test in tests:
            print(f"\n{'=' * 60}")
            print(f"测试: {test['name']}")
            print(f"URL: {test['url']}")

            try:
                async with session.get(test["url"], timeout=30) as response:
                    status = response.status
                    print(f"状态码: {status}")

                    if status == 200:
                        data = await response.json()
                        print("✅ 成功返回 200")

                        # 检查响应结构
                        if data.get("success"):
                            response_data = data.get("data", {})
                            missing_fields = []

                            for field in test["expected_fields"]:
                                if field in response_data:
                                    if isinstance(response_data[field], (list, dict)):
                                        if response_data[field]:  # 非空
                                            print(f"  ✅ {field}: 有数据")
                                        else:
                                            print(f"  ⚠️  {field}: 空数据")
                                    else:
                                        print(f"  ✅ {field}: {response_data[field]}")
                                else:
                                    missing_fields.append(field)

                            if missing_fields:
                                print(f"  ❌ 缺少字段: {missing_fields}")

                            # 特殊检查：库存数据是否还是全0
                            if "total_stock" in response_data:
                                total_stock = response_data["total_stock"]
                                if total_stock > 0:
                                    print(f"  ✅ 库存数据已修复: 总库存 = {total_stock}")
                                else:
                                    print("  ❌ 库存数据仍为0")

                            # 打印部分数据
                            print(
                                f"  📊 示例数据: {json.dumps(response_data, ensure_ascii=False, indent=2)[:300]}..."
                            )

                        else:
                            print(f"  ❌ API返回失败: {data.get('message')}")

                        results.append(
                            {
                                "test": test["name"],
                                "status": "PASS" if status == test["expected_status"] else "FAIL",
                                "actual_status": status,
                                "has_data": bool(data.get("data")),
                            }
                        )

                    else:
                        text = await response.text()
                        print(f"❌ 返回状态码 {status}")
                        print(f"错误信息: {text[:200]}...")

                        results.append(
                            {
                                "test": test["name"],
                                "status": "FAIL",
                                "actual_status": status,
                                "error": text[:100],
                            }
                        )

            except TimeoutError:
                print("❌ 请求超时")
                results.append(
                    {
                        "test": test["name"],
                        "status": "TIMEOUT",
                        "actual_status": None,
                        "error": "Timeout",
                    }
                )

            except Exception as e:
                print(f"❌ 异常: {e}")
                results.append(
                    {
                        "test": test["name"],
                        "status": "ERROR",
                        "actual_status": None,
                        "error": str(e),
                    }
                )

        # 汇总结果
        print(f"\n{'=' * 60}")
        print("测试结果汇总:")
        print("=" * 60)

        passed = 0
        for result in results:
            status_emoji = "✅" if result["status"] == "PASS" else "❌"
            print(f"{status_emoji} {result['test']}: {result['status']}")
            if result["status"] == "PASS":
                passed += 1

        print(f"\n通过: {passed}/{len(results)}")

        if passed == len(results):
            print("🎉 所有测试通过！3个问题已修复。")
        else:
            print("⚠️  仍有问题需要修复。")


if __name__ == "__main__":
    asyncio.run(test_fixed_endpoints())
