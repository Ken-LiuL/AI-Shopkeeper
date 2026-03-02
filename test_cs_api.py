#!/usr/bin/env python3
"""
测试客服API的简单脚本
"""

import json

import requests

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


def test_cs_stats():
    """测试客服统计接口"""
    try:
        url = f"{BASE_URL}/api/customer-service/stats"
        print(f"Testing: {url}")

        response = requests.get(url, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")

        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"Error Response: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("Request timeout")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def test_cs_chat():
    """测试客服聊天接口"""
    try:
        # 先创建会话
        session_url = f"{BASE_URL}/api/customer-service/sessions"
        print(f"Creating session: {session_url}")

        session_resp = requests.post(session_url, json={}, timeout=30)
        print(f"Session Status: {session_resp.status_code}")

        if session_resp.status_code != 200:
            print(f"Failed to create session: {session_resp.text}")
            return False

        session_data = session_resp.json()
        session_id = session_data["data"]["session_id"]
        print(f"Session ID: {session_id}")

        # 测试聊天
        chat_url = f"{BASE_URL}/api/customer-service/chat"
        chat_data = {"session_id": session_id, "message": "你好，我想咨询血压计产品"}

        print(f"Testing chat: {chat_url}")
        chat_resp = requests.post(chat_url, json=chat_data, timeout=60)
        print(f"Chat Status: {chat_resp.status_code}")

        if chat_resp.status_code == 200:
            data = chat_resp.json()
            print(f"Chat Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"Chat Error: {chat_resp.text}")
            return False

    except Exception as e:
        print(f"Chat test error: {e}")
        return False


if __name__ == "__main__":
    print("=== 测试客服API ===")

    print("\n1. 测试统计接口...")
    stats_ok = test_cs_stats()

    print("\n2. 测试聊天接口...")
    chat_ok = test_cs_chat()

    print("\n=== 测试结果 ===")
    print(f"统计接口: {'✅ 正常' if stats_ok else '❌ 异常'}")
    print(f"聊天接口: {'✅ 正常' if chat_ok else '❌ 异常'}")

    if not stats_ok and not chat_ok:
        print("\n❌ 客服功能完全不可用，需要修复")
    elif not chat_ok:
        print("\n⚠️ 聊天功能有问题，需要修复")
    else:
        print("\n✅ 客服功能基本正常")
