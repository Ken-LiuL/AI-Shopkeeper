#!/usr/bin/env python3
"""
Comprehensive AI Store Manager Review
站在付费用户角度全面审查系统功能
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


class StoreManagerReviewer:
    def __init__(self, base_url: str = "https://ai-shopkeeper-kk.fly.dev"):
        self.base_url = base_url
        self.issues = []
        self.test_results = {}
        self.performance_issues = []

    def log_issue(self, category: str, severity: str, description: str, endpoint: str = None):
        """记录发现的问题"""
        issue = {
            "category": category,
            "severity": severity,
            "description": description,
            "endpoint": endpoint,
            "timestamp": datetime.now().isoformat(),
        }
        self.issues.append(issue)
        print(f"❌ [{severity}] {category}: {description}")
        if endpoint:
            print(f"   Endpoint: {endpoint}")

    def request_api(
        self, endpoint: str, method: str = "GET", data: dict = None, timeout: int = 10
    ) -> dict[str, Any]:
        """发送API请求并测量响应时间"""
        url = self.base_url + endpoint
        start_time = time.time()

        try:
            if method == "GET":
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    status = response.getcode()
                    content = response.read().decode("utf-8")
            else:
                post_data = json.dumps(data).encode("utf-8") if data else None
                headers = {"Content-Type": "application/json"} if data else {}
                req = urllib.request.Request(url, data=post_data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    status = response.getcode()
                    content = response.read().decode("utf-8")

            response_time = time.time() - start_time

            # Check performance
            if response_time > 2.0:
                self.log_issue(
                    "Performance",
                    "HIGH",
                    f"Response time {response_time:.2f}s > 2s threshold",
                    endpoint,
                )
                self.performance_issues.append(
                    {"endpoint": endpoint, "response_time": response_time}
                )

            try:
                response_data = json.loads(content)
            except json.JSONDecodeError:
                response_data = {"raw_content": content}

            return {
                "success": True,
                "status": status,
                "data": response_data,
                "response_time": response_time,
            }

        except Exception as e:
            response_time = time.time() - start_time
            return {"success": False, "error": str(e), "response_time": response_time}

    def test_data_reasonableness(self):
        """测试1: 数据合理性"""
        print("\n🔍 测试数据合理性...")

        # 测试竞品价格对比
        print("检查竞品价格对比...")
        result = self.request_api("/api/competitors/price-comparison")
        if result["success"]:
            data = result["data"]
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    try:
                        our_price = float(item.get("our_price", 0))
                        competitor_price = float(item.get("competitor_price", 0))
                    except (ValueError, TypeError):
                        continue

                    if our_price > 0 and competitor_price > 0:
                        price_diff = abs(our_price - competitor_price) / our_price
                        if price_diff > 5:  # 价格相差500%以上不合理
                            self.log_issue(
                                "Data Reasonableness",
                                "HIGH",
                                f"Price difference too extreme: ¥{our_price} vs ¥{competitor_price}",
                                "/api/competitors/price-comparison",
                            )

        # 测试补货建议
        print("检查补货建议...")
        result = self.request_api("/api/products/recommendations")
        if result["success"]:
            data = result["data"]
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    try:
                        suggested_qty = int(item.get("suggested_quantity", 0))
                        current_stock = int(item.get("current_stock", 0))
                    except (ValueError, TypeError):
                        continue

                    # 检查补货数量是否合理
                    if suggested_qty > current_stock * 50:  # 建议补货超过现有库存50倍不合理
                        self.log_issue(
                            "Data Reasonableness",
                            "MEDIUM",
                            f"Excessive restock suggestion: {suggested_qty} vs current {current_stock}",
                            "/api/products/recommendations",
                        )

        # 测试定价建议
        print("检查定价建议...")
        result = self.request_api("/api/pricing/suggestions")
        if result["success"]:
            data = result["data"]
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    try:
                        current_price = float(item.get("current_price", 0))
                        suggested_price = float(item.get("suggested_price", 0))
                    except (ValueError, TypeError):
                        continue

                    if current_price > 0 and suggested_price > 0:
                        price_change = (suggested_price - current_price) / current_price
                        if abs(price_change) > 0.9:  # 价格变动超过90%不合理
                            self.log_issue(
                                "Data Reasonableness",
                                "HIGH",
                                f"Extreme price suggestion: ¥{current_price} -> ¥{suggested_price}",
                                "/api/pricing/suggestions",
                            )

    def test_function_completeness(self):
        """测试2: 功能完整性"""
        print("\n🔧 测试功能完整性...")

        # 测试客服聊天多轮对话
        print("测试客服聊天功能...")
        chat_data = {"message": "你好，我想了解轮椅产品"}
        result = self.request_api("/api/customer-service/chat", "POST", chat_data)
        if not result["success"]:
            self.log_issue(
                "Function Completeness",
                "HIGH",
                "Customer service chat not working",
                "/api/customer-service/chat",
            )

        # 测试知识搜索
        print("测试知识搜索...")
        search_endpoints = [
            "/api/knowledge/search?q=轮椅",
            "/api/knowledge/v1/search?q=轮椅",
            "/api/knowledge/search?q=",  # 空搜索测试
            "/api/knowledge/search?q=不存在的产品xyz123",  # 无结果搜索测试
        ]

        for endpoint in search_endpoints:
            result = self.request_api(endpoint)
            if not result["success"]:
                self.log_issue(
                    "Function Completeness", "HIGH", "Knowledge search not working", endpoint
                )

        # 测试导出功能
        print("测试导出功能...")
        result = self.request_api("/api/reports/export")
        if not result["success"]:
            self.log_issue(
                "Function Completeness",
                "HIGH",
                "Export function not working",
                "/api/reports/export",
            )

        # 测试筛选参数
        print("测试筛选参数...")
        filter_tests = [
            "/api/orders?days=7",
            "/api/orders?days=30",
            "/api/orders?page=1&limit=10",
            "/api/products?category=药品",
            "/api/analytics/trends?days=14",
        ]

        for endpoint in filter_tests:
            result = self.request_api(endpoint)
            if not result["success"]:
                self.log_issue(
                    "Function Completeness", "MEDIUM", "Filter parameters not working", endpoint
                )

    def test_error_handling(self):
        """测试错误处理"""
        print("\n⚠️  测试错误处理...")

        # 测试不存在的ID
        error_tests = [
            "/api/products/999999999",
            "/api/pricing/analysis/999999999",
            "/api/orders/999999999",
            "/api/customer-service/sessions/999999999",
        ]

        for endpoint in error_tests:
            result = self.request_api(endpoint)
            if result["success"] and result["status"] == 200:
                # 应该返回404或错误信息，如果返回200可能是错误处理不当
                data = result.get("data", {})
                if not isinstance(data, dict) or "error" not in data:
                    self.log_issue(
                        "Error Handling",
                        "MEDIUM",
                        "Missing error handling for non-existent ID",
                        endpoint,
                    )

    def test_consistency(self):
        """测试4: 一致性检查"""
        print("\n📊 测试数据一致性...")

        # 获取多个endpoint的相同指标进行对比
        dashboard_result = self.request_api("/api/dashboard/overview")
        orders_result = self.request_api("/api/orders/stats")
        analytics_result = self.request_api("/api/analytics/overview")

        if all(r["success"] for r in [dashboard_result, orders_result, analytics_result]):
            # 比较订单数量一致性
            dashboard_orders = dashboard_result["data"].get("data", {}).get("today_orders", 0)
            orders_stats = orders_result["data"].get("data", {}).get("today_count", 0)
            analytics_orders = analytics_result["data"].get("data", {}).get("orders_today", 0)

            if not (dashboard_orders == orders_stats == analytics_orders):
                self.log_issue(
                    "Consistency",
                    "HIGH",
                    f"Inconsistent order counts: dashboard={dashboard_orders}, "
                    f"orders={orders_stats}, analytics={analytics_orders}",
                )

        # 检查日期格式一致性
        date_endpoints = ["/api/dashboard/sales-trend", "/api/orders/trend", "/api/reports/daily"]

        date_formats = set()
        for endpoint in date_endpoints:
            result = self.request_api(endpoint)
            if result["success"] and "data" in result["data"]:
                data_list = result["data"]["data"]
                if isinstance(data_list, list) and len(data_list) > 0:
                    first_item = data_list[0]
                    if "date" in first_item:
                        date_str = first_item["date"]
                        date_formats.add(type(date_str).__name__ + ":" + str(date_str)[:10])

        if len(date_formats) > 1:
            self.log_issue(
                "Consistency",
                "MEDIUM",
                f"Inconsistent date formats across endpoints: {date_formats}",
            )

    def test_edge_cases(self):
        """测试5: 边界情况"""
        print("\n🚨 测试边界情况...")

        # 测试分页边界
        pagination_tests = [
            "/api/products?page=0",  # 无效页码
            "/api/products?page=-1",  # 负数页码
            "/api/products?page=999999",  # 超大页码
            "/api/products?limit=0",  # 无效限制
            "/api/products?limit=-5",  # 负数限制
            "/api/products?limit=10000",  # 超大限制
        ]

        for endpoint in pagination_tests:
            result = self.request_api(endpoint)
            if result["success"]:
                # 检查是否有合理的分页处理
                data = result["data"]
                if not isinstance(data.get("data"), list):
                    self.log_issue("Edge Cases", "LOW", "Poor pagination handling", endpoint)

        # 测试特殊字符搜索
        special_char_tests = [
            "/api/knowledge/search?q=" + urllib.parse.quote("'\"<>&"),
            "/api/products/search?q=" + urllib.parse.quote("测试%20SQL注入"),
            "/api/knowledge/search?q=" + urllib.parse.quote("💊🏥💉"),  # emoji
        ]

        for endpoint in special_char_tests:
            result = self.request_api(endpoint)
            if not result["success"]:
                self.log_issue(
                    "Edge Cases", "MEDIUM", "Poor handling of special characters", endpoint
                )

    def run_comprehensive_review(self):
        """执行完整审查"""
        print("🏥 AI Store Manager 生产级 Review")
        print("=" * 60)
        print(f"测试目标: {self.base_url}")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 执行所有测试
        self.test_data_reasonableness()
        self.test_function_completeness()
        self.test_error_handling()
        self.test_consistency()
        self.test_edge_cases()

        # 汇总结果
        print("\n" + "=" * 60)
        print("📋 审查结果汇总")
        print("=" * 60)

        if not self.issues:
            print("🎉 恭喜！系统通过全面审查，无严重问题发现")
        else:
            print(f"⚠️  发现 {len(self.issues)} 个问题需要修复:")

            # 按严重程度分类
            high_issues = [i for i in self.issues if i["severity"] == "HIGH"]
            medium_issues = [i for i in self.issues if i["severity"] == "MEDIUM"]
            low_issues = [i for i in self.issues if i["severity"] == "LOW"]

            if high_issues:
                print(f"\n🚨 HIGH priority issues ({len(high_issues)}):")
                for issue in high_issues:
                    print(f"  • {issue['description']}")
                    if issue["endpoint"]:
                        print(f"    {issue['endpoint']}")

            if medium_issues:
                print(f"\n⚠️  MEDIUM priority issues ({len(medium_issues)}):")
                for issue in medium_issues:
                    print(f"  • {issue['description']}")

            if low_issues:
                print(f"\n💡 LOW priority issues ({len(low_issues)}):")
                for issue in low_issues:
                    print(f"  • {issue['description']}")

        # 性能报告
        if self.performance_issues:
            print(f"\n🐌 性能问题 ({len(self.performance_issues)}):")
            for perf in self.performance_issues:
                print(f"  • {perf['endpoint']}: {perf['response_time']:.2f}s")

        print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return self.issues


if __name__ == "__main__":
    reviewer = StoreManagerReviewer()
    issues = reviewer.run_comprehensive_review()

    # 返回问题数量作为退出码
    exit(min(len(issues), 1))
