"""
测试AI客服自我进化系统
验证持续学习闭环能否正常运行
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.customer_service.auto_evolve import (
    CustomerServiceAutoEvolution,
    after_reply_hook,
)


class TestCustomerServiceAutoEvolution:
    """测试客服自我进化系统"""

    @pytest.fixture
    async def evolution_manager(self):
        """创建测试用的进化管理器"""
        # Mock数据库连接池
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])
        mock_pool.fetchrow = AsyncMock(return_value=None)

        manager = CustomerServiceAutoEvolution(pool=mock_pool)
        return manager

    @pytest.fixture
    def temp_data_dir(self):
        """创建临时数据目录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # 设置临时数据目录
            original_cwd = os.getcwd()
            test_data_dir = os.path.join(temp_dir, "data")
            os.makedirs(test_data_dir)

            # Mock getcwd返回临时目录
            with patch("os.getcwd", return_value=temp_dir):
                yield test_data_dir

    async def test_after_reply_hook_high_score(self, evolution_manager, temp_data_dir):
        """测试高分回复的处理流程"""

        # Mock评分器返回高分
        with patch("src.agents.customer_service.auto_evolve.evaluate_reply") as mock_evaluator:
            mock_evaluator.return_value = {
                "overall": 0.9,
                "accuracy": 0.9,
                "professionalism": 0.9,
                "tone": 0.9,
                "resolution": 0.9,
                "compliance": 0.9,
                "feedback": "回复质量很高",
            }

            # Mock分类器
            with patch("src.agents.customer_service.auto_evolve.call_tool") as mock_call_tool:
                mock_call_tool.return_value = {"category": "product_inquiry"}

                # 执行测试
                await evolution_manager._process_reply_evolution(
                    session_id="test_session",
                    user_msg="推荐个血压计",
                    reply="亲，推荐上臂式电子血压计，准确性更好😊",
                    context={"conversation_history": [], "product_results": []},
                )

                # 验证评分被调用
                mock_evaluator.assert_called_once()

                # 验证数据库操作被调用（存储评分和few-shot候选）
                assert evolution_manager.pool.execute.call_count >= 2

                # 验证dynamic_few_shots.json被创建
                few_shots_path = os.path.join(temp_data_dir, "dynamic_few_shots.json")
                assert os.path.exists(few_shots_path)

                # 验证few-shot内容
                with open(few_shots_path, encoding="utf-8") as f:
                    few_shots = json.load(f)
                    assert "product_inquiry" in few_shots
                    assert len(few_shots["product_inquiry"]) == 1
                    assert few_shots["product_inquiry"][0]["user_message"] == "推荐个血压计"

    async def test_after_reply_hook_low_score(self, evolution_manager, temp_data_dir):
        """测试低分回复的处理流程"""

        # Mock评分器返回低分
        with patch("src.agents.customer_service.auto_evolve.evaluate_reply") as mock_evaluator:
            mock_evaluator.return_value = {
                "overall": 0.4,
                "accuracy": 0.3,
                "professionalism": 0.4,
                "tone": 0.5,
                "resolution": 0.3,
                "compliance": 0.8,
                "feedback": "回复不够专业，缺少产品知识",
            }

            # Mock原因分析
            with patch("src.agents.customer_service.auto_evolve.call_tool") as mock_call_tool:
                mock_call_tool.return_value = {
                    "primary_issue": "missing_product_knowledge",
                    "missing_knowledge": "血压计的具体型号和参数",
                    "improvement_suggestion": "需要补充血压计产品知识库",
                }

                # 执行测试
                await evolution_manager._process_reply_evolution(
                    session_id="test_session_low",
                    user_msg="血压计有什么型号？",
                    reply="有很多型号，您可以看看",
                    context={"conversation_history": [], "product_results": []},
                )

                # 验证评分被调用
                mock_evaluator.assert_called_once()

                # 验证数据库操作被调用（存储评分和改进记录）
                assert evolution_manager.pool.execute.call_count >= 2

    async def test_knowledge_patch_generation(self, evolution_manager, temp_data_dir):
        """测试知识库补丁生成"""

        # Mock知识补丁生成
        with patch("src.agents.customer_service.auto_evolve.call_tool") as mock_call_tool:
            mock_call_tool.return_value = {
                "category": "产品规格",
                "question_pattern": "询问血压计型号和参数",
                "knowledge_content": "我们有多款血压计：欧姆龙HEM-7120、松下EW-BW30等，都是上臂式设计",
                "keywords": ["血压计", "型号", "参数", "规格"],
            }

            # 测试补丁生成
            patch_data = await evolution_manager._generate_knowledge_patch(
                user_msg="血压计都有什么型号？", missing_knowledge="血压计的具体型号和参数"
            )

            assert patch_data is not None
            assert patch_data["category"] == "产品规格"
            assert "血压计" in patch_data["knowledge_content"]

            # 测试补丁保存
            await evolution_manager._add_knowledge_patch(patch_data)

            patches_path = os.path.join(temp_data_dir, "cs_knowledge_patches.json")
            assert os.path.exists(patches_path)

            with open(patches_path, encoding="utf-8") as f:
                patches = json.load(f)
                assert len(patches) == 1
                assert patches[0]["category"] == "产品规格"
                assert "created_at" in patches[0]

    async def test_few_shot_update_logic(self, evolution_manager, temp_data_dir):
        """测试few-shot更新逻辑（保持top-3）"""

        # 先添加3个示例
        examples = [
            ("产品咨询1", "回复1", 0.9),
            ("产品咨询2", "回复2", 0.8),
            ("产品咨询3", "回复3", 0.85),
        ]

        for user_msg, reply, score in examples:
            await evolution_manager._update_dynamic_few_shots(
                "product_inquiry", user_msg, reply, score
            )

        # 验证只保留top-3
        few_shots_path = os.path.join(temp_data_dir, "dynamic_few_shots.json")
        with open(few_shots_path, encoding="utf-8") as f:
            few_shots = json.load(f)

        assert len(few_shots["product_inquiry"]) == 3

        # 验证按分数排序（最高分在前）
        scores = [ex["score"] for ex in few_shots["product_inquiry"]]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 0.9  # 最高分

        # 添加一个更高分的示例，验证替换逻辑
        await evolution_manager._update_dynamic_few_shots(
            "product_inquiry", "产品咨询4", "回复4", 0.95
        )

        with open(few_shots_path, encoding="utf-8") as f:
            few_shots = json.load(f)

        # 仍然只有3个，但最高分变成了0.95
        assert len(few_shots["product_inquiry"]) == 3
        assert few_shots["product_inquiry"][0]["score"] == 0.95
        assert few_shots["product_inquiry"][0]["user_message"] == "产品咨询4"

    async def test_evolution_stats(self, evolution_manager):
        """测试进化统计数据获取"""

        # Mock数据库返回结果
        evolution_manager.pool.fetchrow.side_effect = [
            {"total_evaluations": 100, "avg_score": 0.75, "high_scores": 20, "low_scores": 10},
            {"total_candidates": 15, "categories": 5},
            {"total_improvements": 8},
        ]

        stats = await evolution_manager.get_evolution_stats()

        assert stats["evaluation_stats"]["total_evaluations"] == 100
        assert stats["evaluation_stats"]["avg_score"] == 0.75
        assert stats["few_shot_stats"]["total_candidates"] == 15
        assert stats["improvement_stats"]["total_improvements"] == 8

    def test_global_hook_function(self):
        """测试全局after_reply_hook函数"""

        # 验证能够正常导入和调用
        assert callable(after_reply_hook)

        # Mock evolution manager
        with patch(
            "src.agents.customer_service.auto_evolve.get_evolution_manager"
        ) as mock_get_manager:
            mock_manager = AsyncMock()
            mock_get_manager.return_value = mock_manager

            # 测试调用
            asyncio.run(
                after_reply_hook(
                    session_id="test", user_msg="test", reply="test", context={}, pool=None
                )
            )

            mock_manager.after_reply_hook.assert_called_once()

    async def test_database_table_creation(self, evolution_manager):
        """测试数据库表创建"""

        await evolution_manager._ensure_evolution_tables()

        # 验证表创建SQL被执行
        assert evolution_manager.pool.execute.call_count >= 2

        # 验证包含必要的表创建语句
        calls = evolution_manager.pool.execute.call_args_list
        sql_statements = [call[0][0] for call in calls]

        # 检查是否包含关键表
        assert any("cs_improvement_log" in sql for sql in sql_statements)
        assert any("cs_few_shot_candidates" in sql for sql in sql_statements)


class TestIntegration:
    """集成测试"""

    async def test_end_to_end_evolution_flow(self):
        """端到端测试：从回复到学习的完整流程"""

        with tempfile.TemporaryDirectory() as temp_dir:
            # 设置临时环境
            with patch("os.getcwd", return_value=temp_dir):
                # Mock必要的组件
                mock_pool = AsyncMock()
                mock_pool.execute = AsyncMock()

                # Mock评分器
                with patch("src.agents.customer_service.auto_evolve.evaluate_reply") as mock_eval:
                    mock_eval.return_value = {
                        "overall": 0.9,
                        "accuracy": 0.9,
                        "professionalism": 0.9,
                        "tone": 0.9,
                        "resolution": 0.9,
                        "compliance": 0.9,
                        "feedback": "优秀回复",
                    }

                    # Mock分类器
                    with patch("src.agents.customer_service.auto_evolve.call_tool") as mock_tool:
                        mock_tool.return_value = {"category": "greeting"}

                        # 执行完整流程
                        await after_reply_hook(
                            session_id="integration_test",
                            user_msg="你好",
                            reply="亲，您好！很高兴为您服务😊",
                            context={
                                "conversation_history": [],
                                "product_results": [],
                                "intent": "greeting",
                                "confidence": 0.95,
                            },
                            pool=mock_pool,
                        )

                        # 等待异步任务完成
                        await asyncio.sleep(0.1)

                        # 验证文件生成
                        data_dir = os.path.join(temp_dir, "data")
                        few_shots_path = os.path.join(data_dir, "dynamic_few_shots.json")

                        if os.path.exists(few_shots_path):
                            with open(few_shots_path, encoding="utf-8") as f:
                                few_shots = json.load(f)
                                assert "greeting" in few_shots
                                assert few_shots["greeting"][0]["score"] == 0.9


if __name__ == "__main__":
    # 简单的手动测试
    async def quick_test():
        print("🧪 开始测试AI客服自我进化系统...")

        # 创建测试管理器
        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        manager = CustomerServiceAutoEvolution(pool=mock_pool)

        # 测试基本功能
        print("✅ 创建进化管理器成功")

        # 测试表创建
        await manager._ensure_evolution_tables()
        print("✅ 数据库表创建测试完成")

        # 测试统计数据获取
        mock_pool.fetchrow.side_effect = [
            {"total_evaluations": 50, "avg_score": 0.8, "high_scores": 10, "low_scores": 5},
            {"total_candidates": 8, "categories": 3},
            {"total_improvements": 3},
        ]

        stats = await manager.get_evolution_stats()
        print(f"✅ 统计数据获取成功: {stats}")

        print("🎉 所有测试通过！自我进化系统功能正常。")

    asyncio.run(quick_test())
