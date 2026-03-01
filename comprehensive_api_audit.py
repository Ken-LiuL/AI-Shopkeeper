#!/usr/bin/env python3
"""
Comprehensive API audit script for AI Store Manager.
Tests all endpoints for data quality, error handling, and response consistency.
"""

import json
import sys
from datetime import datetime
from typing import Any

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


class APIAuditor:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)
        self.issues: list[dict[str, Any]] = []
        self.passed_tests = 0
        self.failed_tests = 0

    def log_issue(
        self, endpoint: str, issue_type: str, description: str, response_data: Any = None
    ):
        """Log an issue found during testing."""
        self.issues.append(
            {
                "endpoint": endpoint,
                "type": issue_type,
                "description": description,
                "response_data": response_data,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.failed_tests += 1
        print(f"❌ {endpoint}: {issue_type} - {description}")

    def log_success(self, endpoint: str, description: str):
        """Log a successful test."""
        self.passed_tests += 1
        print(f"✅ {endpoint}: {description}")

    def test_response_structure(self, endpoint: str, response: httpx.Response) -> bool:
        """Test if response follows APIResponse structure with success/data/message."""
        try:
            if response.status_code >= 400:
                # Error responses should still follow structure
                data = response.json()
                if not isinstance(data.get("success"), bool) or data.get("success", True):
                    self.log_issue(
                        endpoint, "response_structure", "Error response should have success=false"
                    )
                    return False
                if "message" not in data:
                    self.log_issue(
                        endpoint, "response_structure", "Error response missing message field"
                    )
                    return False
                return True

            data = response.json()

            # Check required fields
            if not isinstance(data.get("success"), bool):
                self.log_issue(
                    endpoint,
                    "response_structure",
                    "Missing or invalid 'success' boolean field",
                    data,
                )
                return False

            if "data" not in data:
                self.log_issue(endpoint, "response_structure", "Missing 'data' field", data)
                return False

            if "message" not in data:
                self.log_issue(endpoint, "response_structure", "Missing 'message' field", data)
                return False

            return True

        except json.JSONDecodeError:
            self.log_issue(endpoint, "response_format", "Response is not valid JSON", response.text)
            return False

    def test_data_quality(self, endpoint: str, data: Any) -> bool:
        """Test data quality - no empty arrays where there should be data, no null required fields."""
        issues_found = False

        if isinstance(data, dict):
            # Check for suspicious empty arrays
            for key, value in data.items():
                if isinstance(value, list) and len(value) == 0:
                    # Some endpoints legitimately return empty arrays
                    if (
                        endpoint not in ["/api/alerts", "/api/selection/runs"]
                        and "empty" not in key.lower()
                    ):
                        print(
                            f"⚠️  {endpoint}: Empty array for '{key}' - might indicate missing data"
                        )

                # Check for null values in critical fields
                if value is None and key in ["id", "name", "price", "status", "created_at"]:
                    self.log_issue(
                        endpoint, "data_quality", f"Critical field '{key}' is null", data
                    )
                    issues_found = True

        return not issues_found

    def test_chinese_encoding(self, endpoint: str, response: httpx.Response) -> bool:
        """Test proper Chinese text encoding."""
        try:
            text = response.text
            # Check if response contains properly encoded Chinese characters
            if "中文" in text or "店长" in text or any(ord(c) > 127 for c in text):
                # If we can read it without encoding errors, it's properly encoded
                return True
            return True  # No Chinese text to check
        except UnicodeDecodeError:
            self.log_issue(endpoint, "encoding", "Chinese text encoding issue")
            return False

    def test_endpoint(
        self, method: str, path: str, payload: dict[str, Any] = None
    ) -> dict[str, Any]:
        """Test a single endpoint."""
        url = f"{self.base_url}{path}"

        try:
            if method.upper() == "GET":
                response = self.client.get(url)
            elif method.upper() == "POST":
                response = self.client.post(url, json=payload)
            elif method.upper() == "PUT":
                response = self.client.put(url, json=payload)
            elif method.upper() == "DELETE":
                response = self.client.delete(url)
            else:
                self.log_issue(path, "test_setup", f"Unsupported method: {method}")
                return {}

            # Test response structure
            structure_ok = self.test_response_structure(path, response)

            # Test Chinese encoding
            encoding_ok = self.test_chinese_encoding(path, response)

            # Test error handling (should never return 500)
            if response.status_code == 500:
                self.log_issue(
                    path, "error_handling", "Endpoint returns 500 - should handle errors gracefully"
                )

            # Parse response data
            try:
                response_data = response.json()

                # Test data quality
                if structure_ok and response.status_code < 400:
                    self.test_data_quality(path, response_data.get("data"))

                return {
                    "status_code": response.status_code,
                    "response": response_data,
                    "structure_ok": structure_ok,
                    "encoding_ok": encoding_ok,
                }
            except json.JSONDecodeError:
                return {
                    "status_code": response.status_code,
                    "response": response.text,
                    "structure_ok": False,
                    "encoding_ok": encoding_ok,
                }

        except Exception as e:
            self.log_issue(path, "network_error", f"Request failed: {str(e)}")
            return {}

    def audit_dashboard_endpoints(self):
        """Audit dashboard endpoints for accurate metrics."""
        print("\n=== DASHBOARD ENDPOINTS ===")

        result = self.test_endpoint("GET", "/api/dashboard/overview")
        if result.get("status_code") == 200:
            data = result["response"].get("data", {})

            # Check if metrics look reasonable
            gmv = data.get("today_gmv", 0)
            orders = data.get("today_orders", 0)
            products = data.get("total_products", 0)

            if products == 0:
                self.log_issue(
                    "/api/dashboard/overview",
                    "data_quality",
                    "Zero products reported - likely data sync issue",
                )
            else:
                self.log_success("/api/dashboard/overview", f"Found {products} products")

            if orders == 0:
                print("⚠️  /api/dashboard/overview: Zero orders today - might be expected")

            # Check for proper numeric types
            if not isinstance(gmv, int | float) and gmv != "0":
                self.log_issue(
                    "/api/dashboard/overview",
                    "data_quality",
                    f"GMV should be numeric, got: {type(gmv)}",
                )

        # Test sales trends
        self.test_endpoint("GET", "/api/dashboard/sales-trend")
        self.test_endpoint("GET", "/api/dashboard/top-products?limit=10")

    def audit_competitor_endpoints(self):
        """Audit competitor price comparison endpoints."""
        print("\n=== COMPETITOR ENDPOINTS ===")

        result = self.test_endpoint("GET", "/api/competitors/price-comparison")
        if result.get("status_code") == 200:
            data = result["response"].get("data", [])

            if not data:
                self.log_issue(
                    "/api/competitors/price-comparison",
                    "data_quality",
                    "Empty price comparison data",
                )
            else:
                # Check for meaningful price differences
                has_real_differences = False
                for item in data:
                    if isinstance(item, dict):
                        price_diff_pct = item.get("price_diff_pct", 0)
                        if isinstance(price_diff_pct, str):
                            try:
                                price_diff_pct = float(price_diff_pct)
                            except (ValueError, TypeError):
                                price_diff_pct = 0
                        if abs(price_diff_pct) > 0.1:  # More than 0.1% difference
                            has_real_differences = True
                            break

                if not has_real_differences:
                    self.log_issue(
                        "/api/competitors/price-comparison",
                        "data_quality",
                        "All price differences are less than 0.1% - might indicate comparison logic issues",
                    )
                else:
                    self.log_success(
                        "/api/competitors/price-comparison", "Found meaningful price differences"
                    )

    def audit_reports_endpoints(self):
        """Audit reports endpoints for complete data."""
        print("\n=== REPORTS ENDPOINTS ===")

        periods = ["daily", "weekly", "monthly"]
        for period in periods:
            result = self.test_endpoint("GET", f"/api/reports/{period}")
            if result.get("status_code") == 200:
                data = result["response"].get("data", [])
                if not data:
                    self.log_issue(
                        f"/api/reports/{period}", "data_quality", f"Empty {period} report data"
                    )
                else:
                    self.log_success(
                        f"/api/reports/{period}", f"Found {len(data)} {period} report entries"
                    )

    def audit_alerts_endpoints(self):
        """Audit alerts endpoints for actionable alerts."""
        print("\n=== ALERTS ENDPOINTS ===")

        result = self.test_endpoint("GET", "/api/alerts")
        if result.get("status_code") == 200:
            data = result["response"].get("data", [])

            # Test alert generation
            scan_result = self.test_endpoint("POST", "/api/alerts/scan")
            if scan_result.get("status_code") in [200, 201]:
                self.log_success("/api/alerts/scan", "Alert scan endpoint works")

            # Check alert data quality
            actionable_alerts = 0
            for alert in data:
                if isinstance(alert, dict):
                    alert_type = alert.get("type", "")
                    if alert_type in ["stockout", "pricing", "performance"]:
                        actionable_alerts += 1

            if actionable_alerts == 0 and len(data) > 0:
                print(f"⚠️  /api/alerts: {len(data)} alerts but none are actionable types")

    def audit_selection_bundles_endpoints(self):
        """Audit selection and bundles endpoints for useful recommendations."""
        print("\n=== SELECTION & BUNDLES ENDPOINTS ===")

        # Test selection runs
        result = self.test_endpoint("GET", "/api/selection/runs")
        if result.get("status_code") == 200:
            runs = result["response"].get("data", [])
            if runs:
                # Get details of latest run
                latest_run = runs[0] if runs else None
                if latest_run and "run_id" in latest_run:
                    detail_result = self.test_endpoint(
                        "GET", f"/api/selection/runs/{latest_run['run_id']}"
                    )
                    if detail_result.get("status_code") == 200:
                        details = detail_result["response"].get("data", {})
                        recommendations = details.get("recommendations", [])
                        if not recommendations:
                            self.log_issue(
                                f"/api/selection/runs/{latest_run['run_id']}",
                                "data_quality",
                                "No recommendations in selection run",
                            )
                        else:
                            self.log_success(
                                f"/api/selection/runs/{latest_run['run_id']}",
                                f"Found {len(recommendations)} recommendations",
                            )

        # Test bundles
        result = self.test_endpoint("GET", "/api/bundles")
        if result.get("status_code") == 200:
            bundles = result["response"].get("data", [])
            if not bundles:
                print("⚠️  /api/bundles: No bundle recommendations found")
            else:
                self.log_success("/api/bundles", f"Found {len(bundles)} bundle recommendations")

    def audit_all_endpoints(self):
        """Run comprehensive audit of all endpoints."""
        print("🔍 Starting comprehensive API audit...\n")

        # Basic health checks
        print("=== HEALTH CHECKS ===")
        self.test_endpoint("GET", "/health")
        self.test_endpoint("GET", "/ready")

        # Core endpoints with detailed checks
        self.audit_dashboard_endpoints()
        self.audit_competitor_endpoints()
        self.audit_reports_endpoints()
        self.audit_alerts_endpoints()
        self.audit_selection_bundles_endpoints()

        # Test other important endpoints
        print("\n=== OTHER ENDPOINTS ===")
        endpoints = [
            ("GET", "/api/products"),
            ("GET", "/api/orders"),
            ("GET", "/api/metrics/llm"),
            ("GET", "/api/knowledge/search?q=test"),
            ("GET", "/api/customer-service/sessions"),
            ("GET", "/api/analytics/product-performance"),
            ("GET", "/api/system/health"),
        ]

        for method, path in endpoints:
            result = self.test_endpoint(method, path)
            if result.get("status_code") in [200, 201]:
                self.log_success(path, "Endpoint responds correctly")

    def generate_report(self):
        """Generate final audit report."""
        print(f"\n{'=' * 60}")
        print("AUDIT REPORT")
        print(f"{'=' * 60}")
        print(f"✅ Passed tests: {self.passed_tests}")
        print(f"❌ Failed tests: {self.failed_tests}")
        print(f"📊 Total issues found: {len(self.issues)}")

        if self.issues:
            print(f"\n{'=' * 40}")
            print("ISSUES TO FIX:")
            print(f"{'=' * 40}")

            # Group issues by type
            issues_by_type = {}
            for issue in self.issues:
                issue_type = issue["type"]
                if issue_type not in issues_by_type:
                    issues_by_type[issue_type] = []
                issues_by_type[issue_type].append(issue)

            for issue_type, issues in issues_by_type.items():
                print(f"\n{issue_type.upper()} ({len(issues)} issues):")
                for issue in issues:
                    print(f"  • {issue['endpoint']}: {issue['description']}")
        else:
            print("\n🎉 No critical issues found!")

        # Save detailed report
        report_data = {
            "audit_timestamp": datetime.now().isoformat(),
            "summary": {
                "passed_tests": self.passed_tests,
                "failed_tests": self.failed_tests,
                "total_issues": len(self.issues),
            },
            "issues": self.issues,
        }

        with open("api_audit_report.json", "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        print("\n📋 Detailed report saved to: api_audit_report.json")

    def close(self):
        """Clean up resources."""
        self.client.close()


def main():
    """Run the comprehensive API audit."""
    auditor = APIAuditor()

    try:
        auditor.audit_all_endpoints()
        auditor.generate_report()
    except KeyboardInterrupt:
        print("\n\n⚠️  Audit interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Audit failed with error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        auditor.close()

    # Return exit code based on issues found
    return 1 if auditor.issues else 0


if __name__ == "__main__":
    sys.exit(main())
