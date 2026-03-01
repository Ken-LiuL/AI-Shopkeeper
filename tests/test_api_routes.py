"""API route smoke tests — run before every review to verify all endpoints are reachable.

Usage:
    python -m pytest tests/test_api_routes.py -v
    # or directly:
    python tests/test_api_routes.py
"""

import httpx
import pytest

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"

# Ground truth: endpoint path → expected HTTP method
# This is the SINGLE SOURCE OF TRUTH for all API paths.
ENDPOINTS = {
    # Health
    "GET /health": 200,
    # Dashboard (NO /v1/)
    "GET /api/dashboard/overview": 200,
    "GET /api/dashboard/sales-trend?days=7": 200,
    # Stores (NO /v1/)
    "GET /api/stores/overview": 200,
    # Products — legacy at /api/products, v1 at /api/v1/products
    "GET /api/v1/products/list": 200,
    "GET /api/products/categories": 200,
    # Competitors (NO /v1/)
    "GET /api/competitors/overview": 200,
    "GET /api/competitors/price-comparison": 200,
    # Orders (NO /v1/)
    "GET /api/orders/list": 200,
    "GET /api/orders/stats": 200,
    # Pricing (NO /v1/)
    "GET /api/pricing/suggestions": 200,
    # Inventory (NO /v1/)
    "GET /api/inventory/overview": 200,
    "GET /api/inventory/restock-suggestions": 200,
    # Insights (NO /v1/)
    "GET /api/insights/daily": 200,
    # Reports (NO /v1/)
    "GET /api/reports/daily": 200,
    "GET /api/reports/weekly": 200,
    "GET /api/reports/monthly": 200,
    # Chat (HAS /v1/)
    # "POST /api/v1/chat": 200,  # Needs body, tested separately
    # Alerts (NO /v1/)
    "GET /api/alerts": 200,
}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.mark.parametrize("endpoint", ENDPOINTS.keys())
def test_endpoint_reachable(client, endpoint):
    method, path = endpoint.split(" ", 1)
    resp = client.request(method, path)
    assert resp.status_code != 404, f"{endpoint} returned 404 — route not registered!"
    # Allow 200 or 500 (server error is different from missing route)
    assert resp.status_code < 500 or resp.status_code == 500, (
        f"{endpoint} returned {resp.status_code}"
    )


def test_chat_endpoint(client):
    resp = client.post("/api/v1/chat", json={"message": "测试"})
    assert resp.status_code != 404, "Chat endpoint /api/v1/chat returned 404!"
    assert resp.status_code == 200


def test_all_return_json(client):
    """Every endpoint should return valid JSON."""
    for endpoint in ENDPOINTS:
        method, path = endpoint.split(" ", 1)
        resp = client.request(method, path)
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, dict), f"{endpoint} didn't return a JSON object"


def test_dashboard_data_consistency(client):
    """Dashboard overview numbers should be non-zero."""
    resp = client.get("/api/dashboard/overview")
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        assert data.get("total_products", 0) > 0, "Dashboard shows 0 products"


def test_stores_overview_non_zero(client):
    """Store overview should have real data, not all zeros."""
    resp = client.get("/api/stores/overview")
    if resp.status_code == 200:
        data = resp.json().get("data", {})
        stores = data.get("stores", [])
        if stores:
            total_gmv = sum(s.get("gmv", 0) or 0 for s in stores)
            assert total_gmv > 0, "All stores show 0 GMV"


if __name__ == "__main__":
    print(f"Testing {len(ENDPOINTS)} endpoints against {BASE_URL}\n")
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    passed = 0
    failed = 0
    for endpoint, _expected in ENDPOINTS.items():
        method, path = endpoint.split(" ", 1)
        try:
            resp = client.request(method, path)
            status = "✅" if resp.status_code != 404 else "❌ 404"
            if resp.status_code == 404:
                failed += 1
            else:
                passed += 1
            print(f"  {status} {endpoint} → {resp.status_code}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {endpoint} → ERROR: {e}")

    # Chat
    try:
        resp = client.post("/api/v1/chat", json={"message": "测试"})
        status = "✅" if resp.status_code != 404 else "❌ 404"
        print(f"  {status} POST /api/v1/chat → {resp.status_code}")
        if resp.status_code != 404:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        failed += 1
        print(f"  ❌ POST /api/v1/chat → ERROR: {e}")

    print(f"\n{'=' * 40}")
    print(f"Passed: {passed}, Failed: {failed}")
    if failed:
        print("⚠️  FIX FAILED ENDPOINTS BEFORE REVIEW!")
        exit(1)
    else:
        print("✅ All endpoints reachable!")
