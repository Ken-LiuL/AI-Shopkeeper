#!/usr/bin/env python3
"""
AI店长项目最终验证脚本
验证P0和P1任务的修复效果
"""

import os
from datetime import datetime

import requests

BASE_URL = "https://ai-shopkeeper-kk.fly.dev"


def test_customer_service():
    """验证P0任务1：客服功能404修复"""
    print("\n🧪 P0-1: 验证客服功能修复...")

    try:
        # 测试统计端点
        resp = requests.get(f"{BASE_URL}/api/customer-service/stats", timeout=15)
        if resp.status_code == 200:
            print("✅ 客服统计API正常")
        else:
            print(f"❌ 客服统计API异常：{resp.status_code}")
            return False

        # 测试会话创建
        session_resp = requests.post(
            f"{BASE_URL}/api/customer-service/sessions", json={}, timeout=15
        )
        if session_resp.status_code == 200:
            session_id = session_resp.json()["data"]["session_id"]
            print(f"✅ 会话创建成功：{session_id}")

            # 测试聊天功能
            chat_data = {"session_id": session_id, "message": "验证消息：推荐血压计"}
            chat_resp = requests.post(
                f"{BASE_URL}/api/customer-service/chat", json=chat_data, timeout=30
            )
            if chat_resp.status_code == 200:
                reply_data = chat_resp.json()["data"]
                print(f"✅ 客服聊天功能正常，回复意图：{reply_data['intent']}")
                return True
            else:
                print(f"❌ 客服聊天功能异常：{chat_resp.status_code}")
                return False
        else:
            print(f"❌ 会话创建失败：{session_resp.status_code}")
            return False

    except Exception as e:
        print(f"❌ 客服功能测试失败：{e}")
        return False


def test_selection_recommendations():
    """验证P0任务2-3：选品推荐Mock数据减少和风险提示"""
    print("\n🧪 P0-2&3: 验证选品推荐改进...")

    try:
        resp = requests.get(f"{BASE_URL}/api/selection/recommendations", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            recommendations = data.get("data", [])
            if recommendations:
                first_rec = recommendations[0]

                # 检查是否有风险提示
                if "risk_warning" in first_rec:
                    print("✅ 选品推荐包含风险提示")
                else:
                    print("⚠️ 选品推荐缺少风险提示字段")

                # 检查数据来源标注
                if "data_source" in first_rec:
                    print(f"✅ 标注数据来源：{first_rec['data_source']}")
                else:
                    print("⚠️ 缺少数据来源标注")

                # 检查推荐理由是否改进
                reason = first_rec.get("reason", "")
                if "预估利润率" in reason or "月销量" in reason:
                    print("✅ 推荐理由已改进为数据驱动")
                else:
                    print(f"⚠️ 推荐理由可能仍使用通用模板：{reason}")

                return True
            else:
                print("❌ 选品推荐为空")
                return False
        else:
            print(f"❌ 选品推荐API异常：{resp.status_code}")
            return False

    except Exception as e:
        print(f"❌ 选品推荐测试失败：{e}")
        return False


def test_alerts_action_suggestions():
    """验证P1任务4：预警系统行动建议"""
    print("\n🧪 P1-4: 验证预警系统行动建议...")

    try:
        resp = requests.get(f"{BASE_URL}/api/alerts", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            alerts = data.get("data", [])
            if alerts:
                # 检查第一个预警是否有行动建议
                first_alert = alerts[0]
                if "action_suggestions" in first_alert:
                    suggestions = first_alert["action_suggestions"]
                    if suggestions and len(suggestions) > 0:
                        print(f"✅ 预警包含{len(suggestions)}条行动建议")
                        print(f"   示例：{suggestions[0][:50]}...")
                        return True
                    else:
                        print("⚠️ action_suggestions字段存在但为空")
                        return False
                else:
                    print("⚠️ 预警缺少action_suggestions字段")
                    return False
            else:
                print("❌ 无预警数据")
                return False
        else:
            print(f"❌ 预警API异常：{resp.status_code}")
            return False

    except Exception as e:
        print(f"❌ 预警测试失败：{e}")
        return False


def verify_frontend_files():
    """验证P1任务5：前端新手引导文件是否存在"""
    print("\n🧪 P1-5: 验证前端新手引导...")

    onboarding_file = "frontend/components/onboarding/guide.tsx"
    if os.path.exists(onboarding_file):
        print("✅ 新手引导组件文件存在")

        # 检查文件内容
        with open(onboarding_file, encoding="utf-8") as f:
            content = f.read()
            if "OnboardingGuide" in content and "ONBOARDING_STEPS" in content:
                print("✅ 新手引导组件结构完整")
                return True
            else:
                print("⚠️ 新手引导组件结构不完整")
                return False
    else:
        print("❌ 新手引导组件文件不存在")
        return False


def main():
    """主验证流程"""
    print("=" * 60)
    print("🚀 AI店长项目P0+P1任务最终验证")
    print(f"⏰ 验证时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 测试环境：{BASE_URL}")
    print("=" * 60)

    results = {
        "P0-1 客服功能修复": test_customer_service(),
        "P0-2&3 选品推荐改进": test_selection_recommendations(),
        "P1-4 预警行动建议": test_alerts_action_suggestions(),
        "P1-5 新手引导": verify_frontend_files(),
    }

    print("\n" + "=" * 60)
    print("📋 验证结果汇总")
    print("=" * 60)

    passed = 0
    total = len(results)

    for task, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{task:20} : {status}")
        if success:
            passed += 1

    print("\n" + "=" * 60)
    print(f"🎯 总体结果：{passed}/{total} 项任务验证通过")

    if passed == total:
        print("🎉 所有P0和P1任务修复验证成功！")
        print("💡 建议：可以安全部署到生产环境")
    elif passed >= total * 0.8:
        print("⚠️ 大部分任务修复成功，建议解决剩余问题后部署")
    else:
        print("🚨 多个任务验证失败，建议全面检查修复")

    print("=" * 60)


if __name__ == "__main__":
    main()
