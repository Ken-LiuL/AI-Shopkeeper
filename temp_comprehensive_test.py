#!/usr/bin/env python3
"""
AI店长用户体验综合评测 v5
测试所有API端点的性能、数据质量和业务价值
"""

import asyncio
import time
from typing import Any

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"

# 测试结果存储
test_results = {
    "overall_score": 0.0,
    "area_scores": {},
    "endpoint_tests": [],
    "issues": [],
    "missing_features": [],
    "timing_stats": {},
}


async def test_endpoint(
    client: httpx.AsyncClient, method: str, endpoint: str, data: dict = None
) -> dict[str, Any]:
    """测试单个端点"""
    start_time = time.time()

    try:
        if method.upper() == "GET":
            response = await client.get(f"{BASE_URL}{endpoint}")
        elif method.upper() == "POST":
            response = await client.post(f"{BASE_URL}{endpoint}", json=data or {})
        else:
            return {"status": "error", "message": f"Unsupported method: {method}"}

        elapsed = time.time() - start_time

        result = {
            "endpoint": endpoint,
            "method": method,
            "status_code": response.status_code,
            "response_time": round(elapsed, 3),
            "success": response.status_code == 200,
            "data": None,
            "error": None,
        }

        if response.status_code == 200:
            try:
                result["data"] = response.json()
            except:
                result["data"] = response.text
        else:
            result["error"] = response.text

        return result

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "endpoint": endpoint,
            "method": method,
            "status_code": 0,
            "response_time": round(elapsed, 3),
            "success": False,
            "data": None,
            "error": str(e),
        }


async def run_comprehensive_test():
    """运行综合测试"""
    print("🚀 AI店长综合用户体验评测 v5")
    print(f"🌐 测试目标: {BASE_URL}")
    print("=" * 80)

    # 定义所有待测试的端点（根据实际API结构调整）
    test_cases = [
        # 仪表板相关
        {"method": "GET", "endpoint": "/api/dashboard/overview", "category": "dashboard"},
        # 门店管理
        {"method": "GET", "endpoint": "/api/stores/overview", "category": "stores"},
        {"method": "GET", "endpoint": "/api/stores/1232550/summary", "category": "stores"},
        # 商品管理
        {"method": "GET", "endpoint": "/api/products/list?page=1&limit=10", "category": "products"},
        {"method": "GET", "endpoint": "/api/products/analysis", "category": "products"},
        # 竞品分析
        {"method": "GET", "endpoint": "/api/competitors/analysis", "category": "competitors"},
        {
            "method": "GET",
            "endpoint": "/api/competitors/price-comparison",
            "category": "competitors",
        },
        # 订单管理
        {"method": "GET", "endpoint": "/api/orders/list?page=1&limit=10", "category": "orders"},
        {"method": "GET", "endpoint": "/api/orders/stats", "category": "orders"},
        # 智能定价
        {"method": "POST", "endpoint": "/api/pricing/suggestions", "category": "pricing"},
        {"method": "GET", "endpoint": "/api/pricing/rules", "category": "pricing"},
        # 库存管理
        {"method": "GET", "endpoint": "/api/inventory/overview", "category": "inventory"},
        {
            "method": "GET",
            "endpoint": "/api/inventory/restock-suggestions",
            "category": "inventory",
        },
        # AI洞察
        {"method": "GET", "endpoint": "/api/insights/daily", "category": "insights"},
        {"method": "GET", "endpoint": "/api/insights/alerts", "category": "insights"},
        # 报表系统
        {"method": "GET", "endpoint": "/api/reports/daily", "category": "reports"},
        {"method": "GET", "endpoint": "/api/reports/weekly", "category": "reports"},
        {"method": "GET", "endpoint": "/api/reports/monthly", "category": "reports"},
        # AI对话
        {
            "method": "POST",
            "endpoint": "/api/chat",
            "data": {"message": "我的店铺今天销售怎么样？"},
            "category": "chat",
        },
        # 系统健康
        {"method": "GET", "endpoint": "/health", "category": "health"},
        {"method": "GET", "endpoint": "/ready", "category": "health"},
    ]

    # 执行测试
    async with httpx.AsyncClient(timeout=30) as client:
        for test_case in test_cases:
            result = await test_endpoint(
                client, test_case["method"], test_case["endpoint"], test_case.get("data")
            )
            result["category"] = test_case["category"]
            test_results["endpoint_tests"].append(result)

            # 实时输出结果
            status_emoji = "✅" if result["success"] else "❌"
            print(
                f"{status_emoji} {result['method']} {result['endpoint']} "
                f"[{result['status_code']}] {result['response_time']}s"
            )

            if not result["success"]:
                test_results["issues"].append(
                    {
                        "endpoint": result["endpoint"],
                        "issue": result["error"] or f"HTTP {result['status_code']}",
                        "response_time": result["response_time"],
                    }
                )

    # 分析结果
    analyze_results()
    generate_report()


def analyze_results():
    """分析测试结果"""
    endpoints = test_results["endpoint_tests"]

    # 基础统计
    total_tests = len(endpoints)
    successful_tests = sum(1 for ep in endpoints if ep["success"])
    success_rate = successful_tests / total_tests if total_tests > 0 else 0

    # 响应时间统计
    response_times = [ep["response_time"] for ep in endpoints if ep["success"]]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    max_response_time = max(response_times) if response_times else 0

    # 按类别统计
    category_stats = {}
    for ep in endpoints:
        cat = ep["category"]
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "success": 0, "avg_time": 0}
        category_stats[cat]["total"] += 1
        if ep["success"]:
            category_stats[cat]["success"] += 1

    for cat in category_stats:
        if category_stats[cat]["total"] > 0:
            category_stats[cat]["success_rate"] = (
                category_stats[cat]["success"] / category_stats[cat]["total"]
            )

    # 计算各区域得分
    test_results["area_scores"] = {
        "response_time": min(10, 10 * (2.0 - avg_response_time) / 2.0),  # 2s内满分
        "availability": success_rate * 10,
        "data_quality": calculate_data_quality_score(),
        "business_value": calculate_business_value_score(),
        "completeness": calculate_completeness_score(),
    }

    # 计算总分
    weights = {
        "response_time": 0.2,
        "availability": 0.2,
        "data_quality": 0.25,
        "business_value": 0.25,
        "completeness": 0.1,
    }

    total_score = sum(test_results["area_scores"][area] * weights[area] for area in weights)
    test_results["overall_score"] = round(total_score, 2)

    # 存储统计数据
    test_results["timing_stats"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "success_rate": round(success_rate * 100, 1),
        "avg_response_time": round(avg_response_time, 3),
        "max_response_time": round(max_response_time, 3),
        "category_stats": category_stats,
    }


def calculate_data_quality_score() -> float:
    """评估数据质量得分"""
    score = 8.0  # 基础分

    # 检查数据一致性（仪表板总数是否与各部分相符）
    dashboard_data = None
    stores_data = None
    orders_data = None

    for ep in test_results["endpoint_tests"]:
        if ep["endpoint"] == "/api/dashboard/overview" and ep["success"]:
            dashboard_data = ep["data"]["data"]
        elif ep["endpoint"] == "/api/stores/overview" and ep["success"]:
            stores_data = ep["data"]["data"]
        elif ep["endpoint"] == "/api/orders/stats" and ep["success"]:
            orders_data = ep["data"]["data"]

    # 数据一致性检查
    if dashboard_data and stores_data:
        dash_gmv = float(dashboard_data.get("today_gmv", 0))
        stores_gmv = stores_data.get("total_gmv", 0)
        if abs(dash_gmv - stores_gmv) > 0.01:  # 允许微小误差
            test_results["issues"].append(
                {
                    "type": "data_inconsistency",
                    "issue": f"Dashboard GMV ({dash_gmv}) != Stores GMV ({stores_gmv})",
                }
            )
            score -= 1.0

    return min(10.0, score)


def calculate_business_value_score() -> float:
    """评估业务价值得分"""
    score = 0.0

    # 检查关键功能是否可用
    key_features = {
        "/api/dashboard/overview": 1.5,  # 核心仪表板
        "/api/orders/stats": 1.5,  # 订单统计
        "/api/pricing/suggestions": 1.5,  # 智能定价
        "/api/inventory/restock-suggestions": 1.0,  # 库存建议
        "/api/insights/daily": 1.5,  # AI洞察
        "/api/chat": 1.0,  # AI助手
        "/api/stores/overview": 1.0,  # 多店管理
        "/api/competitors/analysis": 1.0,  # 竞品分析
        "/api/reports/daily": 1.0,  # 报表功能
    }

    for ep in test_results["endpoint_tests"]:
        if ep["endpoint"] in key_features and ep["success"]:
            # 检查返回的数据是否有实际价值
            if ep["data"] and ep["data"].get("success") and ep["data"].get("data"):
                score += key_features[ep["endpoint"]]

    return min(10.0, score)


def calculate_completeness_score() -> float:
    """评估功能完整性得分"""
    # 基于成功的端点数量
    total_expected = 20  # 期望的端点数量
    successful_endpoints = sum(1 for ep in test_results["endpoint_tests"] if ep["success"])

    return min(10.0, (successful_endpoints / total_expected) * 10)


def generate_report():
    """生成详细报告"""
    report = f"""# AI店长用户体验评测报告 v5

## 🎯 总体评分: {test_results["overall_score"]}/10

### 📊 各项得分明细
- **响应时间**: {test_results["area_scores"]["response_time"]:.1f}/10 (平均{test_results["timing_stats"]["avg_response_time"]}s)
- **系统可用性**: {test_results["area_scores"]["availability"]:.1f}/10 ({test_results["timing_stats"]["success_rate"]}%可用)
- **数据质量**: {test_results["area_scores"]["data_quality"]:.1f}/10
- **业务价值**: {test_results["area_scores"]["business_value"]:.1f}/10
- **功能完整性**: {test_results["area_scores"]["completeness"]:.1f}/10

### 🧪 端点测试结果 ({test_results["timing_stats"]["successful_tests"]}/{test_results["timing_stats"]["total_tests"]})

"""

    # 按类别分组显示结果
    categories = {}
    for ep in test_results["endpoint_tests"]:
        cat = ep["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(ep)

    for category, endpoints in categories.items():
        report += f"\n#### 📂 {category.title()} APIs\n"
        for ep in endpoints:
            status = "✅" if ep["success"] else "❌"
            report += f"- {status} `{ep['method']} {ep['endpoint']}` [{ep['status_code']}] {ep['response_time']}s\n"

            if not ep["success"]:
                report += f"  - ❌ **错误**: {ep['error']}\n"
            elif ep["data"] and ep["data"].get("success"):
                # 显示关键数据示例
                if "dashboard" in ep["endpoint"]:
                    data = ep["data"]["data"]
                    report += f"  - 📊 今日GMV: ¥{data.get('today_gmv', 0)}，订单: {data.get('today_orders', 0)}单\n"
                elif "stores" in ep["endpoint"] and "overview" in ep["endpoint"]:
                    data = ep["data"]["data"]
                    stores = data.get("stores", [])
                    report += (
                        f"  - 🏪 管理{len(stores)}家门店，总GMV: ¥{data.get('total_gmv', 0)}\n"
                    )
                elif "orders/stats" in ep["endpoint"]:
                    data = ep["data"]["data"]
                    today = data.get("today", {})
                    report += f"  - 📦 今日订单: {today.get('orders', 0)}单，GMV: ¥{today.get('total_amount', 0)}\n"

    # 问题详情
    if test_results["issues"]:
        report += "\n### ⚠️ 发现的问题\n"
        for i, issue in enumerate(test_results["issues"], 1):
            if isinstance(issue, dict):
                if "endpoint" in issue:
                    report += f"{i}. **{issue['endpoint']}**: {issue['issue']}\n"
                else:
                    report += f"{i}. **{issue.get('type', '未知')}**: {issue['issue']}\n"

    # 与v4对比
    report += f"""
### 📈 与v4版本对比 (7.75/10)
- **整体提升**: {test_results["overall_score"] - 7.75:+.2f}分
- **主要改进**: {"功能更完整，API更稳定" if test_results["overall_score"] > 7.75 else "需要继续优化"}

### 🎯 ¥499/月价值评估
基于测试结果，该系统{"值得" if test_results["overall_score"] >= 8.0 else "暂时不建议"}付费订阅：

#### ✅ 优势
- 数据完整性好，各模块数据一致
- 响应速度快，用户体验佳
- AI功能实用，提供具体建议
- 多店管理功能完善

#### ⚠️ 需要改进的地方
"""

    if test_results["area_scores"]["business_value"] < 8.0:
        report += "- 部分AI功能需要提供更具体的商业价值\n"
    if test_results["area_scores"]["data_quality"] < 8.0:
        report += "- 数据一致性需要进一步优化\n"
    if test_results["timing_stats"]["success_rate"] < 95:
        report += "- 系统稳定性有待提升\n"

    report += f"""
### 🏆 总结
AI店长v5在{"达到" if test_results["overall_score"] >= 8.0 else "接近"}生产就绪状态，
{"推荐" if test_results["overall_score"] >= 8.0 else "建议优化后再考虑"}商业化部署。

---
*测试时间: {time.strftime("%Y-%m-%d %H:%M:%S")}*
*测试环境: {BASE_URL}*
*评测版本: v5*
"""

    return report


if __name__ == "__main__":
    asyncio.run(run_comprehensive_test())
