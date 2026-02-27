#!/usr/bin/env python3
"""
测试新版客服系统
"""
import asyncio
import logging
from src.agents.customer_service.nodes import chat
from src.db import postgres as pg_db

logging.basicConfig(level=logging.INFO)


async def test_chat():
    """测试客服聊天功能"""
    # 初始化数据库连接
    await pg_db.init_pool()
    pool = pg_db.get_pool()
    
    if not pool:
        print("❌ 无法连接到数据库")
        return
    
    try:
        # 测试场景1：问候
        print("🧪 测试1：问候")
        result = await chat(
            session_id="test_001",
            message="你好",
            pool=pool
        )
        print(f"回复: {result['reply']}")
        print(f"意图: {result['intent']}")
        print(f"需要人工: {result['needs_human']}")
        print()
        
        # 测试场景2：商品咨询
        print("🧪 测试2：商品咨询")
        result = await chat(
            session_id="test_002", 
            message="你们有血压计吗？推荐一个",
            pool=pool
        )
        print(f"回复: {result['reply']}")
        print(f"意图: {result['intent']}")
        print(f"找到商品: {len(result['sources'])} 个")
        if result['sources']:
            for source in result['sources'][:3]:
                print(f"  - {source.get('name', '未知')} (分数: {source.get('score', 0)})")
        print(f"需要人工: {result['needs_human']}")
        print()
        
        # 测试场景3：健康咨询（应该合规拒答）
        print("🧪 测试3：健康咨询")
        result = await chat(
            session_id="test_003",
            message="我血压150，该怎么办",
            pool=pool
        )
        print(f"回复: {result['reply']}")
        print(f"意图: {result['intent']}")
        print(f"需要人工: {result['needs_human']}")
        print()
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pg_db.close_pool()


if __name__ == "__main__":
    asyncio.run(test_chat())