#!/usr/bin/env python3
"""
Focused API test script for the specific requirements mentioned in the task.
Tests the key functionality areas that need production-grade fixes.
"""

import json
from typing import Any

import httpx

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


def test_endpoint(
    client: httpx.Client, method: str, path: str, payload: dict[str, Any] = None
) -> dict[str, Any]:
    """Test a single endpoint and return results."""
    url = f"{BASE_URL}{path}"

    try:
        if method.upper() == "GET":
            response = client.get(url)
        elif method.upper() == "POST":
            response = client.post(url, json=payload)
        else:
            return {"error": f"Unsupported method: {method}"}

        return {
            "status_code": response.status_code,
            "response": response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else response.text,
            "headers": dict(response.headers),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    """Run focused tests for production-grade requirements."""
    print("🔍 Running focused API tests for production requirements...\n")

    client = httpx.Client(timeout=30.0)

    try:
        # 1. Test Response Consistency (All use APIResponse wrapper)
        print("=== 1. RESPONSE CONSISTENCY ===")
        consistency_endpoints = [
            "/health",
            "/ready",
            "/api/dashboard/overview",
            "/api/competitors/price-comparison",
            "/api/reports/daily",
            "/api/alerts",
            "/api/bundles",
            "/api/selection/runs",
        ]

        for endpoint in consistency_endpoints:
            result = test_endpoint(client, "GET", endpoint)
            if result.get("error"):
                print(f"❌ {endpoint}: Network error - {result['error']}")
                continue

            response = result.get("response", {})
            if isinstance(response, dict):
                has_success = "success" in response
                has_data = "data" in response
                has_message = "message" in response

                if has_success and has_data and has_message:
                    print(f"✅ {endpoint}: Proper APIResponse structure")
                else:
                    missing = []
                    if not has_success:
                        missing.append("success")
                    if not has_data:
                        missing.append("data")
                    if not has_message:
                        missing.append("message")
                    print(f"❌ {endpoint}: Missing fields - {missing}")
            else:
                print(f"❌ {endpoint}: Not JSON response or malformed")

        # 2. Test Data Quality
        print("\n=== 2. DATA QUALITY ===")

        # Dashboard metrics accuracy
        print("Dashboard Metrics:")
        result = test_endpoint(client, "GET", "/api/dashboard/overview")
        if result.get("status_code") == 200:
            data = result["response"].get("data", {})

            # Check GMV is numeric
            gmv = data.get("today_gmv")
            if isinstance(gmv, (int, float)) or (
                isinstance(gmv, str) and gmv.replace(".", "").replace("-", "").isdigit()
            ):
                print(f"✅ GMV is numeric: {gmv}")
            else:
                print(f"❌ GMV is not numeric: {gmv} (type: {type(gmv)})")

            # Check products count is reasonable
            products = data.get("total_products", 0)
            if products > 0:
                print(f"✅ Products count: {products}")
            else:
                print("❌ Zero products - possible data sync issue")

            # Check order metrics
            orders = data.get("today_orders", 0)
            print(f"ℹ️  Today's orders: {orders}")

        # 3. Test Price Comparison Quality
        print("\nPrice Comparison:")
        result = test_endpoint(client, "GET", "/api/competitors/price-comparison?limit=10")
        if result.get("status_code") == 200:
            comparisons = result["response"].get("data", [])
            if comparisons:
                meaningful_diffs = 0
                for comp in comparisons:
                    price_diff = comp.get("price_diff_pct", 0)
                    if isinstance(price_diff, str):
                        try:
                            price_diff = float(price_diff)
                        except:
                            price_diff = 0
                    if abs(price_diff) > 0.1:  # More than 0.1%
                        meaningful_diffs += 1

                if meaningful_diffs > 0:
                    print(
                        f"✅ Found {meaningful_diffs}/{len(comparisons)} meaningful price differences"
                    )
                else:
                    print(
                        f"⚠️  All {len(comparisons)} price differences are < 0.1% - might indicate comparison issues"
                    )
            else:
                print("❌ No price comparison data found")

        # 4. Test Reports Completeness
        print("\n=== 3. REPORTS COMPLETENESS ===")
        report_periods = ["daily", "weekly", "monthly"]

        for period in report_periods:
            result = test_endpoint(client, "GET", f"/api/reports/{period}")
            if result.get("status_code") == 200:
                reports = result["response"].get("data", [])
                if reports:
                    print(f"✅ {period.title()} reports: {len(reports)} entries")

                    # Check data completeness in first report
                    if reports and isinstance(reports[0], dict):
                        first_report = reports[0]
                        required_fields = ["date", "revenue", "orders"]
                        missing_fields = [
                            field for field in required_fields if field not in first_report
                        ]
                        if missing_fields:
                            print(f"⚠️  {period.title()} report missing fields: {missing_fields}")
                else:
                    print(f"❌ {period.title()} reports: No data")
            else:
                print(f"❌ {period.title()} reports: HTTP {result.get('status_code')}")

        # 5. Test Alerts Quality
        print("\n=== 4. ALERTS QUALITY ===")

        # Test alert generation
        result = test_endpoint(client, "POST", "/api/alerts/scan")
        if result.get("status_code") in [200, 201]:
            print("✅ Alert scan endpoint functional")
        else:
            print(f"❌ Alert scan failed: HTTP {result.get('status_code')}")

        # Check existing alerts
        result = test_endpoint(client, "GET", "/api/alerts")
        if result.get("status_code") == 200:
            alerts = result["response"].get("data", [])
            actionable_types = ["stockout", "pricing", "performance", "quality", "inventory"]
            actionable_alerts = 0

            for alert in alerts:
                if isinstance(alert, dict):
                    alert_type = alert.get("type", "").lower()
                    if any(actionable in alert_type for actionable in actionable_types):
                        actionable_alerts += 1

            if alerts:
                print(f"✅ Alerts: {len(alerts)} total, {actionable_alerts} actionable")
            else:
                print("ℹ️  No alerts currently active")

        # 6. Test Selection & Bundle Recommendations
        print("\n=== 5. RECOMMENDATIONS QUALITY ===")

        # Test bundles
        result = test_endpoint(client, "GET", "/api/bundles")
        if result.get("status_code") == 200:
            bundles = result["response"].get("data", [])
            if bundles:
                print(f"✅ Bundle recommendations: {len(bundles)} available")

                # Check bundle quality
                useful_bundles = 0
                for bundle in bundles:
                    if isinstance(bundle, dict):
                        products = bundle.get("products", [])
                        if len(products) >= 2:  # Bundles should have 2+ products
                            useful_bundles += 1

                if useful_bundles > 0:
                    print(f"✅ Useful bundles: {useful_bundles}/{len(bundles)}")
                else:
                    print("⚠️  No multi-product bundles found")
            else:
                print("❌ No bundle recommendations")

        # Test selection runs
        result = test_endpoint(client, "GET", "/api/selection/runs")
        if result.get("status_code") == 200:
            runs = result["response"].get("data", [])
            if runs:
                print(f"✅ Selection runs: {len(runs)} available")

                # Test latest run details
                latest_run = runs[0] if runs else None
                if latest_run and "run_id" in latest_run:
                    detail_result = test_endpoint(
                        client, "GET", f"/api/selection/runs/{latest_run['run_id']}"
                    )
                    if detail_result.get("status_code") == 200:
                        details = detail_result["response"].get("data", {})
                        recommendations = details.get("recommendations", [])
                        if recommendations:
                            print(f"✅ Latest run has {len(recommendations)} recommendations")
                        else:
                            print("❌ Latest run has no recommendations")
            else:
                print("ℹ️  No selection runs found")

        # 7. Test Error Handling (Never return 500)
        print("\n=== 6. ERROR HANDLING ===")

        # Test non-existent endpoints for proper error structure
        test_endpoints = ["/api/nonexistent", "/api/products/99999999", "/api/orders/invalid-id"]

        for endpoint in test_endpoints:
            result = test_endpoint(client, "GET", endpoint)
            status_code = result.get("status_code", 0)
            response = result.get("response", {})

            if status_code == 500:
                print(f"❌ {endpoint}: Returns 500 - should handle errors gracefully")
            elif status_code in [404, 400] and isinstance(response, dict) and "success" in response:
                print(f"✅ {endpoint}: Proper error response (HTTP {status_code})")
            else:
                print(f"⚠️  {endpoint}: HTTP {status_code}, response format might need review")

        print("\n=== 7. CHINESE TEXT ENCODING ===")

        # Test Chinese text endpoints
        chinese_endpoints = [
            "/api/products?limit=5",
            "/api/knowledge/search?q=消毒液",
        ]

        for endpoint in chinese_endpoints:
            result = test_endpoint(client, "GET", endpoint)
            if result.get("status_code") == 200:
                response_text = json.dumps(result["response"], ensure_ascii=False)
                if (
                    "中" in response_text
                    or "医" in response_text
                    or any(ord(c) > 127 for c in response_text[:1000])
                ):
                    print(f"✅ {endpoint}: Chinese text properly encoded")
                else:
                    print(f"ℹ️  {endpoint}: No Chinese text to verify encoding")
            else:
                print(f"⚠️  {endpoint}: Failed to test encoding (HTTP {result.get('status_code')})")

    except Exception as e:
        print(f"❌ Test suite failed: {e}")
    finally:
        client.close()

    print("\n" + "=" * 60)
    print("🏁 FOCUSED API TEST COMPLETE")
    print("Review the output above for issues to fix.")
    print("=" * 60)


if __name__ == "__main__":
    main()
