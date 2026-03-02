#!/usr/bin/env python3
"""
全面测试客服API功能
"""

import requests

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


def test_all_cs_endpoints():
    """测试所有客服端点"""

    print("=== 客服API全面测试 ===\n")

    # 1. 测试健康检查
    print("1. 测试健康检查...")
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"   /health: {resp.status_code} - {'✅' if resp.status_code == 200 else '❌'}")
    except Exception as e:
        print(f"   /health: ❌ - {e}")

    # 2. 测试客服统计
    print("\n2. 测试客服统计...")
    try:
        resp = requests.get(f"{BASE_URL}/api/customer-service/stats", timeout=10)
        print(
            f"   /api/customer-service/stats: {resp.status_code} - {'✅' if resp.status_code == 200 else '❌'}"
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"      会话总数: {data.get('data', {}).get('total_sessions', 0)}")
    except Exception as e:
        print(f"   /api/customer-service/stats: ❌ - {e}")

    # 3. 测试客服分析
    print("\n3. 测试客服分析...")
    try:
        resp = requests.get(f"{BASE_URL}/api/customer-service/analytics", timeout=10)
        print(
            f"   /api/customer-service/analytics: {resp.status_code} - {'✅' if resp.status_code == 200 else '❌'}"
        )
    except Exception as e:
        print(f"   /api/customer-service/analytics: ❌ - {e}")

    # 4. 创建会话并测试聊天
    print("\n4. 测试会话创建和聊天...")
    session_id = None
    try:
        # 创建会话
        resp = requests.post(f"{BASE_URL}/api/customer-service/sessions", json={}, timeout=10)
        if resp.status_code == 200:
            session_data = resp.json()
            session_id = session_data["data"]["session_id"]
            print(f"   会话创建: ✅ - 会话ID: {session_id}")
        else:
            print(f"   会话创建: ❌ - {resp.status_code}")
    except Exception as e:
        print(f"   会话创建: ❌ - {e}")

    if session_id:
        # 5. 测试各种类型的问题
        test_messages = [
            ("血压计咨询", "我想买血压计，有哪些推荐？"),
            ("专业问题", "糖尿病患者应该用什么样的血糖仪？"),
            ("售后问题", "我的血压计测量不准确，怎么办？"),
            ("价格比较", "你们的血压计比其他店便宜多少？"),
            ("使用方法", "电子血压计怎么正确使用？"),
        ]

        print("\n5. 测试不同类型的客服问题...")
        for test_name, message in test_messages:
            try:
                chat_data = {"session_id": session_id, "message": message}
                resp = requests.post(
                    f"{BASE_URL}/api/customer-service/chat", json=chat_data, timeout=30
                )

                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["data"]["reply"]
                    intent = data["data"]["intent"]
                    sources_count = len(data["data"]["sources"])
                    needs_human = data["data"]["needs_human"]

                    print(f"   {test_name}: ✅")
                    print(f"      意图: {intent}")
                    print(f"      相关商品: {sources_count}个")
                    print(f"      需要人工: {'是' if needs_human else '否'}")
                    print(f"      回复: {reply[:50]}...")
                else:
                    print(f"   {test_name}: ❌ - {resp.status_code}")

            except Exception as e:
                print(f"   {test_name}: ❌ - {e}")

        # 6. 测试会话历史
        print("\n6. 测试会话历史...")
        try:
            resp = requests.get(
                f"{BASE_URL}/api/customer-service/sessions/{session_id}/messages", timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                message_count = len(data["data"]["messages"])
                print(f"   会话历史: ✅ - {message_count}条消息")
            else:
                print(f"   会话历史: ❌ - {resp.status_code}")
        except Exception as e:
            print(f"   会话历史: ❌ - {e}")

    # 7. 测试反馈提交
    print("\n7. 测试反馈提交...")
    if session_id:
        try:
            feedback_data = {
                "session_id": session_id,
                "message_id": "test_message",
                "rating": 5,
                "comment": "测试反馈",
            }
            resp = requests.post(
                f"{BASE_URL}/api/customer-service/feedback", json=feedback_data, timeout=10
            )
            print(f"   反馈提交: {resp.status_code} - {'✅' if resp.status_code == 200 else '❌'}")
        except Exception as e:
            print(f"   反馈提交: ❌ - {e}")

    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_all_cs_endpoints()
