#!/usr/bin/env python3
"""
Debug the remaining 2 issues to understand what needs to be fixed
"""

import json
import urllib.request


def debug_endpoint(endpoint, method="GET", data=None):
    url = "https://ai-shopkeeper-kk.fly.dev" + endpoint
    print(f"\n🔍 Debugging {method} {endpoint}")

    try:
        if method == "POST":
            post_data = json.dumps(data).encode("utf-8") if data else b""
            headers = {"Content-Type": "application/json"}
            req = urllib.request.Request(url, data=post_data, headers=headers, method=method)
        else:
            req = urllib.request.Request(url)

        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            headers = dict(response.headers)
            content = response.read()

            print(f"Status: {status}")
            print(f"Headers: {headers}")
            print(f"Content length: {len(content)}")
            print(f"Content type: {headers.get('content-type', 'unknown')}")

            # Try to decode as text
            try:
                text_content = content.decode("utf-8")
                print(f"Content preview: {text_content[:200]}...")

                # Try to parse as JSON
                try:
                    json_data = json.loads(text_content)
                    print(f"JSON structure: {type(json_data)}")
                    if isinstance(json_data, dict):
                        print(f"JSON keys: {list(json_data.keys())}")
                except json.JSONDecodeError:
                    print("Content is not JSON")

            except UnicodeDecodeError:
                print("Content is binary data")

    except Exception as e:
        print(f"Error: {e}")


def main():
    print("🐛 Debugging Remaining Issues")
    print("=" * 40)

    # Debug issue 1: Reports export
    debug_endpoint("/api/reports/export", "POST", {"report_type": "daily", "format": "csv"})

    # Try with query parameters instead
    debug_endpoint("/api/reports/export?report_type=daily&format=csv", "POST")

    # Debug issue 2: Price comparison data format
    debug_endpoint("/api/competitors/price-comparison")


if __name__ == "__main__":
    main()
