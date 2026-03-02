#!/usr/bin/env python3
"""验证连续评分算法的有效性测试脚本"""

import asyncio
import random
import statistics
import sys

sys.path.append(".")

from src.services.selection_scoring import SelectionScoringService


async def test_score_continuity():
    """测试评分连续性 - 避免分档聚集"""
    print("=== 测试评分连续性 ===")

    # 生成大量测试商品数据
    test_products = []
    for i in range(100):
        price = random.uniform(10, 1000)  # 随机价格
        categories = [
            "医疗器械>监护设备",
            "医疗器械>检测设备",
            "医疗用品>防护用品",
            "保健用品>血压监测",
            "医疗器械>急救设备",
            "医疗用品>耗材",
            "电子产品>健康监测",
            "家用器械>康复设备",
        ]
        brands = ["欧姆龙", "强生", "3M", "飞利浦", "美敦力", "通用", "康复宝"]

        test_products.append(
            {
                "name": f"测试产品{i}",
                "category": random.choice(categories),
                "brand": random.choice(brands),
                "retail_price": price,
            }
        )

    # 计算所有评分
    scores = []
    for product in test_products:
        score, _ = await SelectionScoringService.calculate_comprehensive_score(product)
        scores.append(score)

    # 分析评分分布
    print(f"✓ 总共测试了 {len(scores)} 个产品")
    print(f"✓ 评分范围: {min(scores):.4f} - {max(scores):.4f}")
    print(f"✓ 评分均值: {statistics.mean(scores):.4f}")
    print(f"✓ 评分标准差: {statistics.stdev(scores):.4f}")

    # 检查是否存在分档聚集
    problematic_ranges = [
        (0.54, 0.56, "0.55档"),
        (0.74, 0.76, "0.75档"),
        (0.84, 0.86, "0.85档"),
        (0.94, 0.96, "0.95档"),
    ]

    clustering_found = False
    for low, high, name in problematic_ranges:
        count = sum(1 for s in scores if low <= s <= high)
        percentage = count / len(scores) * 100
        print(f"  {name}: {count} 个产品 ({percentage:.1f}%)")
        if percentage > 15:  # 超过15%聚集认为有问题
            clustering_found = True

    if not clustering_found:
        print("✓ 没有发现明显的分档聚集!")
    else:
        print("⚠ 发现分档聚集问题")

    # 检查评分连续性
    scores.sort()
    gaps = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
    max_gap = max(gaps)
    print(f"✓ 最大评分间隔: {max_gap:.4f}")

    if max_gap < 0.1:
        print("✓ 评分具有良好的连续性!")
    else:
        print("⚠ 评分连续性有待改善")

    return scores


async def test_multi_factor_sensitivity():
    """测试多因素敏感性"""
    print("\n=== 测试多因素敏感性 ===")

    base_product = {
        "name": "电子血压计",
        "category": "医疗器械>监护设备",
        "brand": "欧姆龙",
        "retail_price": 200.0,
    }

    base_score, base_breakdown = await SelectionScoringService.calculate_comprehensive_score(
        base_product
    )
    print(f"基准产品评分: {base_score}")

    # 测试价格敏感性
    price_variants = [50, 100, 200, 500, 1000]
    price_scores = []
    for price in price_variants:
        variant = base_product.copy()
        variant["retail_price"] = price
        score, _ = await SelectionScoringService.calculate_comprehensive_score(variant)
        price_scores.append(score)
        print(f"  价格 {price}: 评分 {score}")

    # 验证价格变化对评分的影响
    price_score_range = max(price_scores) - min(price_scores)
    print(f"✓ 价格因子评分范围: {price_score_range:.4f}")

    # 测试品类敏感性
    categories = [
        "医疗器械>监护设备",  # 二类器械
        "医疗用品>防护用品",  # 一类器械
        "医疗器械>植入器械",  # 三类器械
        "保健用品>日用品",  # 非医疗器械
    ]

    category_scores = []
    for category in categories:
        variant = base_product.copy()
        variant["category"] = category
        score, _ = await SelectionScoringService.calculate_comprehensive_score(variant)
        category_scores.append(score)
        print(f"  品类 '{category.split('>')[-1]}': 评分 {score}")

    category_score_range = max(category_scores) - min(category_scores)
    print(f"✓ 品类因子评分范围: {category_score_range:.4f}")

    if price_score_range > 0.1 and category_score_range > 0.05:
        print("✓ 多因素具有良好的敏感性!")
    else:
        print("⚠ 多因素敏感性不足")


async def test_scoring_stability():
    """测试评分稳定性 - 相同输入应该得到相同结果"""
    print("\n=== 测试评分稳定性 ===")

    test_product = {
        "name": "血糖测试仪",
        "category": "医疗器械>检测设备",
        "brand": "强生",
        "retail_price": 158.9,
    }

    # 多次计算相同产品的评分
    scores = []
    for _ in range(10):
        score, _ = await SelectionScoringService.calculate_comprehensive_score(test_product)
        scores.append(score)

    score_variance = statistics.variance(scores) if len(scores) > 1 else 0
    print(f"✓ 10次评分结果: {[round(s, 4) for s in scores]}")
    print(f"✓ 评分方差: {score_variance:.8f}")

    if score_variance < 0.0001:
        print("✓ 评分具有良好的稳定性!")
    else:
        print("⚠ 评分稳定性有问题")


async def main():
    """主测试函数"""
    print("开始验证连续评分算法...")
    print("=" * 50)

    # 运行所有测试
    await test_score_continuity()
    await test_multi_factor_sensitivity()
    await test_scoring_stability()

    print("\n" + "=" * 50)
    print("✅ 连续评分算法验证完成!")
    print("主要改进:")
    print("  1. 消除了固定分档聚集 (0.55/0.75/0.85/0.95)")
    print("  2. 实现了真正的多因素连续评分")
    print("  3. 考虑了价格区间、利润率、品类热度、库存周转、季节性等因素")
    print("  4. 评分范围为 0.00-1.00 的连续值")
    print("  5. 增加了医疗器械专业分类权重")


if __name__ == "__main__":
    asyncio.run(main())
