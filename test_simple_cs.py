#!/usr/bin/env python3
"""
简单的客服API测试
用于调试API连接问题
"""

import asyncio
import os
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv

load_dotenv(project_root / ".env")

# Check environment variables
print("Environment check:")
print(f"LLM_PROVIDER: {os.getenv('LLM_PROVIDER', 'not set')}")
print(f"OPENROUTER_API_KEY: {os.getenv('OPENROUTER_API_KEY', 'not set')[:20]}...")
print(f"ANTHROPIC_API_KEY: {os.getenv('ANTHROPIC_API_KEY', 'not set')[:20]}...")


async def test_simple_llm():
    """测试简单的LLM调用"""
    try:
        from src.agents.llm import MODEL_DEEPSEEK, call_tool

        tool = {
            "name": "test_response",
            "description": "简单测试",
            "input_schema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        }

        result = await call_tool(
            prompt="你好，回复'测试成功'",
            tool=tool,
            model=MODEL_DEEPSEEK,
        )

        print(f"✅ LLM 测试成功: {result}")
        return True

    except Exception as e:
        print(f"❌ LLM 测试失败: {e}")
        return False


async def test_cs_direct():
    """直接测试客服功能"""
    try:
        from src.agents.customer_service.nodes import chat

        result = await chat(
            session_id="test_simple",
            message="你好",
            pool=None,  # 不使用数据库
            conversation_history=None,
        )

        print("✅ 客服测试成功:")
        print(f"  回复: {result['reply']}")
        print(f"  意图: {result['intent']}")
        print(f"  需要人工: {result['needs_human']}")
        return True

    except Exception as e:
        print(f"❌ 客服测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    print("🔧 简单客服API测试\n")

    # Test 1: Simple LLM call
    print("1. 测试基础LLM调用...")
    llm_ok = await test_simple_llm()

    if not llm_ok:
        print("基础LLM调用失败，无法继续测试")
        return

    # Test 2: Customer service
    print("\n2. 测试客服系统...")
    cs_ok = await test_cs_direct()

    if cs_ok:
        print("\n✅ 所有测试通过！")
    else:
        print("\n❌ 客服测试失败")


if __name__ == "__main__":
    asyncio.run(main())
