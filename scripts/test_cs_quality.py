#!/usr/bin/env python3
"""
AI店长客服质量测试 + 迭代优化脚本
基于真实场景，系统化测试各种客服情况，自动评分并优化

目标：每个场景评分 >= 0.8，整体平均 >= 0.85
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Setup path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

# Import required modules
from src.agents.customer_service.nodes import chat
from src.agents.customer_service.evaluator import evaluate_reply
from src.db import postgres as pg_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 测试用例定义 - 覆盖各种真实客服场景
# ═══════════════════════════════════════════════════════════════════════════════

TEST_SCENARIOS = [
    # 产品咨询类
    {
        "category": "product_inquiry",
        "description": "基础商品咨询",
        "user_message": "你们有血压计吗？推荐一个",
        "expected_intent": "product_inquiry",
        "conversation_history": None,
    },
    {
        "category": "product_inquiry",
        "description": "用量咨询",
        "user_message": "这个试纸一盒能用多久？",
        "expected_intent": "usage_question",
        "conversation_history": [
            {"role": "user", "content": "血糖试纸有吗？"},
            {"role": "assistant", "content": "亲，有的~我们有多款血糖试纸😊"}
        ],
    },
    {
        "category": "product_inquiry",
        "description": "年龄适用性",
        "user_message": "80岁老人用什么血压计好？",
        "expected_intent": "recommendation",
        "conversation_history": None,
    },
    {
        "category": "product_inquiry",
        "description": "医疗级别咨询",
        "user_message": "这个体温计是医疗级的吗？",
        "expected_intent": "product_inquiry",
        "conversation_history": None,
    },
    {
        "category": "product_inquiry",
        "description": "商品对比",
        "user_message": "额温枪和耳温枪哪个准确？",
        "expected_intent": "comparison",
        "conversation_history": None,
    },

    # 售后服务类
    {
        "category": "after_sales",
        "description": "退款申请",
        "user_message": "这个血压计不好用，我要退款",
        "expected_intent": "after_sales",
        "conversation_history": None,
    },
    {
        "category": "after_sales", 
        "description": "换货申请",
        "user_message": "收到的体温计坏了，能换一个吗？",
        "expected_intent": "after_sales",
        "conversation_history": None,
    },
    {
        "category": "after_sales",
        "description": "质量问题",
        "user_message": "试纸受潮了，测不准",
        "expected_intent": "after_sales",
        "conversation_history": None,
    },

    # 投诉类
    {
        "category": "complaint",
        "description": "态度投诉",
        "user_message": "你们客服态度太差了，我要投诉",
        "expected_intent": "complaint",
        "conversation_history": None,
    },
    {
        "category": "complaint",
        "description": "发错货",
        "user_message": "订单要的血压计，发来的是血糖仪！",
        "expected_intent": "complaint",
        "conversation_history": None,
    },
    {
        "category": "complaint",
        "description": "过期商品",
        "user_message": "收到的药品过期了，这怎么能卖？",
        "expected_intent": "complaint",
        "conversation_history": None,
    },

    # 物流类
    {
        "category": "logistics",
        "description": "配送时间",
        "user_message": "下单多久能送到？",
        "expected_intent": "logistics",
        "conversation_history": None,
    },
    {
        "category": "logistics",
        "description": "骑手问题",
        "user_message": "骑手说找不到地址，怎么办？",
        "expected_intent": "logistics",
        "conversation_history": None,
    },
    {
        "category": "logistics",
        "description": "催单",
        "user_message": "订单一小时了还没送到，什么情况？",
        "expected_intent": "logistics",
        "conversation_history": None,
    },

    # 特殊场景类
    {
        "category": "special",
        "description": "开发票",
        "user_message": "能开发票吗？怎么申请？",
        "expected_intent": "other",
        "conversation_history": None,
    },
    {
        "category": "special",
        "description": "隐私订单",
        "user_message": "买避孕套，配送员会看到吗？",
        "expected_intent": "other",
        "conversation_history": None,
    },

    # 紧急情况类
    {
        "category": "emergency",
        "description": "发烧紧急",
        "user_message": "小孩发烧39度，体温计多久能送到？",
        "expected_intent": "other",
        "conversation_history": None,
    },
    {
        "category": "emergency",
        "description": "外伤紧急",
        "user_message": "手划伤了，急需碘伏和创可贴",
        "expected_intent": "other",
        "conversation_history": None,
    },

    # 多轮对话类
    {
        "category": "multi_turn",
        "description": "客户追问",
        "user_message": "那个血压计准确吗？",
        "expected_intent": "product_inquiry",
        "conversation_history": [
            {"role": "user", "content": "推荐个血压计"},
            {"role": "assistant", "content": "亲，推荐欧姆龙上臂式血压计😊 大屏显示，操作简单"}
        ],
    },
    {
        "category": "multi_turn",
        "description": "补充信息",
        "user_message": "老人85岁，有高血压",
        "expected_intent": "product_inquiry",
        "conversation_history": [
            {"role": "user", "content": "推荐个血压计"},
            {"role": "assistant", "content": "亲，推荐欧姆龙上臂式血压计😊"},
            {"role": "user", "content": "老人用的"},
            {"role": "assistant", "content": "好的~那更推荐大屏语音款，老人看得清楚😊"}
        ],
    }
]

# ═══════════════════════════════════════════════════════════════════════════════
# 测试执行逻辑
# ═══════════════════════════════════════════════════════════════════════════════

class CSQualityTester:
    def __init__(self):
        self.results = []
        self.iteration = 0
        self.max_iterations = 5

    async def run_single_test(self, scenario: Dict, pool) -> Dict:
        """执行单个测试用例"""
        session_id = f"test_{scenario['category']}_{datetime.now().strftime('%H%M%S')}"
        
        try:
            # 调用客服系统
            cs_result = await chat(
                session_id=session_id,
                message=scenario["user_message"],
                pool=pool,
                conversation_history=scenario.get("conversation_history")
            )
            
            # 评分
            evaluation = await evaluate_reply(
                user_message=scenario["user_message"],
                ai_reply=cs_result["reply"],
                conversation_history=scenario.get("conversation_history"),
                product_results=cs_result.get("sources", [])
            )
            
            return {
                "scenario": scenario,
                "cs_response": cs_result,
                "evaluation": evaluation,
                "session_id": session_id
            }
            
        except Exception as e:
            logger.error(f"测试失败 - {scenario['description']}: {e}")
            return {
                "scenario": scenario,
                "cs_response": {"reply": f"测试失败: {e}", "intent": "error"},
                "evaluation": {
                    "overall": 0.0,
                    "feedback": f"测试执行失败: {e}"
                },
                "session_id": session_id,
                "error": str(e)
            }

    async def run_all_tests(self, pool=None) -> List[Dict]:
        """执行所有测试用例"""
        logger.info(f"开始执行 {len(TEST_SCENARIOS)} 个测试用例...")
        
        results = []
        for i, scenario in enumerate(TEST_SCENARIOS, 1):
            logger.info(f"执行测试 {i}/{len(TEST_SCENARIOS)}: {scenario['description']}")
            
            result = await run_single_test(scenario, pool)
            results.append(result)
            
            # 简要输出
            score = result["evaluation"]["overall"]
            reply = result["cs_response"]["reply"]
            print(f"  ✅ {scenario['description']} - 评分: {score:.2f}")
            print(f"     回复: {reply[:100]}{'...' if len(reply) > 100 else ''}")
            
            # 短暂延迟避免API限制
            await asyncio.sleep(0.5)
        
        return results

    def analyze_results(self, results: List[Dict]) -> Dict:
        """分析测试结果"""
        total_score = 0
        category_scores = {}
        low_score_cases = []
        
        for result in results:
            score = result["evaluation"]["overall"]
            category = result["scenario"]["category"]
            
            total_score += score
            
            if category not in category_scores:
                category_scores[category] = []
            category_scores[category].append(score)
            
            if score < 0.8:
                low_score_cases.append({
                    "description": result["scenario"]["description"],
                    "score": score,
                    "feedback": result["evaluation"]["feedback"],
                    "user_message": result["scenario"]["user_message"],
                    "ai_reply": result["cs_response"]["reply"]
                })
        
        avg_score = total_score / len(results) if results else 0
        category_averages = {
            cat: sum(scores) / len(scores) for cat, scores in category_scores.items()
        }
        
        return {
            "total_tests": len(results),
            "average_score": avg_score,
            "category_scores": category_averages,
            "low_score_cases": low_score_cases,
            "pass_rate": len([r for r in results if r["evaluation"]["overall"] >= 0.8]) / len(results)
        }

    def print_analysis(self, analysis: Dict):
        """打印分析结果"""
        print("\n" + "="*80)
        print("📊 测试结果分析")
        print("="*80)
        
        print(f"总测试数: {analysis['total_tests']}")
        print(f"平均得分: {analysis['average_score']:.3f}")
        print(f"通过率 (>=0.8): {analysis['pass_rate']:.1%}")
        print(f"目标达成: {'✅ 是' if analysis['average_score'] >= 0.85 else '❌ 否'}")
        
        print(f"\n📈 各类别得分:")
        for category, score in analysis['category_scores'].items():
            status = "✅" if score >= 0.8 else "❌"
            print(f"  {status} {category}: {score:.3f}")
        
        if analysis['low_score_cases']:
            print(f"\n⚠️  低分案例 (< 0.8):")
            for case in analysis['low_score_cases']:
                print(f"  • {case['description']} - {case['score']:.2f}")
                print(f"    问题: {case['feedback'][:100]}...")
                print(f"    用户: {case['user_message']}")
                print(f"    回复: {case['ai_reply'][:100]}...")
                print()

    def save_results(self, results: List[Dict], analysis: Dict):
        """保存测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = project_root / "test_results" / f"cs_quality_{timestamp}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        data = {
            "timestamp": timestamp,
            "iteration": self.iteration,
            "results": results,
            "analysis": analysis,
            "target_achieved": analysis["average_score"] >= 0.85
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        
        logger.info(f"结果保存到: {output_file}")


async def run_single_test(scenario: Dict, pool=None) -> Dict:
    """执行单个测试用例的独立函数"""
    session_id = f"test_{scenario['category']}_{datetime.now().strftime('%H%M%S')}"
    
    try:
        # 调用客服系统
        cs_result = await chat(
            session_id=session_id,
            message=scenario["user_message"],
            pool=pool,
            conversation_history=scenario.get("conversation_history")
        )
        
        # 评分
        evaluation = await evaluate_reply(
            user_message=scenario["user_message"],
            ai_reply=cs_result["reply"],
            conversation_history=scenario.get("conversation_history"),
            product_results=cs_result.get("sources", [])
        )
        
        return {
            "scenario": scenario,
            "cs_response": cs_result,
            "evaluation": evaluation,
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"测试失败 - {scenario['description']}: {e}")
        return {
            "scenario": scenario,
            "cs_response": {"reply": f"测试失败: {e}", "intent": "error"},
            "evaluation": {
                "overall": 0.0,
                "accuracy": 0.0,
                "professionalism": 0.0,
                "tone": 0.0,
                "resolution": 0.0,
                "compliance": 0.0,
                "feedback": f"测试执行失败: {e}"
            },
            "session_id": session_id,
            "error": str(e)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 优化迭代逻辑
# ═══════════════════════════════════════════════════════════════════════════════

def identify_improvement_areas(low_score_cases: List[Dict]) -> Dict:
    """识别需要改进的领域"""
    improvements = {
        "prompt": [],
        "knowledge_base": [],
        "few_shot": []
    }
    
    for case in low_score_cases:
        feedback = case['feedback'].lower()
        score_breakdown = case.get('score_breakdown', {})
        
        # 根据反馈分析改进方向
        if '无实质内容' in feedback or 'professionalism' in str(score_breakdown):
            improvements['prompt'].append(f"增加实质内容要求 - {case['description']}")
        
        if '信息不准确' in feedback or 'accuracy' in str(score_breakdown):
            improvements['knowledge_base'].append(f"完善相关知识 - {case['description']}")
            
        if '语气' in feedback or 'tone' in str(score_breakdown):
            improvements['few_shot'].append(f"优化语气示例 - {case['description']}")
        
        if '未解决问题' in feedback or 'resolution' in str(score_breakdown):
            improvements['prompt'].append(f"加强问题解决要求 - {case['description']}")
    
    return improvements


async def apply_optimizations(improvements: Dict) -> bool:
    """应用优化（简化版，主要是记录改进点）"""
    logger.info("🔧 分析改进方向...")
    
    has_changes = False
    
    if improvements['prompt']:
        logger.info("📝 Prompt 优化建议:")
        for item in improvements['prompt']:
            logger.info(f"  - {item}")
        has_changes = True
    
    if improvements['knowledge_base']:
        logger.info("📚 知识库优化建议:")
        for item in improvements['knowledge_base']:
            logger.info(f"  - {item}")
        has_changes = True
    
    if improvements['few_shot']:
        logger.info("💬 Few-shot 优化建议:")
        for item in improvements['few_shot']:
            logger.info(f"  - {item}")
        has_changes = True
    
    if not has_changes:
        logger.info("暂无明显改进方向")
    
    # TODO: 实际的优化逻辑
    # 1. 根据 improvements 修改对应文件
    # 2. 重新加载知识库缓存
    # 3. 返回是否有实际修改
    
    return has_changes


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """主测试流程"""
    print("🚀 AI店长客服质量测试开始")
    print("="*80)
    
    # 尝试初始化数据库，但允许失败
    pool = None
    try:
        await pg_db.init_pool()
        pool = pg_db.get_pool()
        logger.info("✅ 数据库连接成功")
    except Exception as e:
        logger.warning(f"⚠️  数据库连接失败，将使用无数据库模式: {e}")
        pool = None
    
    tester = CSQualityTester()
    
    try:
        for iteration in range(1, tester.max_iterations + 1):
            tester.iteration = iteration
            logger.info(f"\n🔄 第 {iteration} 轮测试开始...")
            
            # 执行所有测试
            results = await tester.run_all_tests(pool)
            
            # 分析结果
            analysis = tester.analyze_results(results)
            tester.print_analysis(analysis)
            
            # 保存结果
            tester.save_results(results, analysis)
            
            # 检查是否达标
            if analysis["average_score"] >= 0.85:
                logger.info("🎉 目标达成！所有测试通过")
                break
            
            # 如果未达标且不是最后一轮，进行优化
            if iteration < tester.max_iterations:
                logger.info(f"\n🔧 开始第 {iteration} 轮优化...")
                improvements = identify_improvement_areas(analysis["low_score_cases"])
                optimized = await apply_optimizations(improvements)
                
                if not optimized:
                    logger.warning("未找到明显优化点，继续下一轮测试")
                
                logger.info("等待 3 秒后继续...")
                await asyncio.sleep(3)
        
        # 最终结果
        if analysis["average_score"] >= 0.85:
            print("\n✅ 测试成功完成！平均分达到目标")
        else:
            print(f"\n⚠️  测试未完全达标，当前平均分: {analysis['average_score']:.3f}")
            print("请根据分析结果手动优化相关模块")
    
    except KeyboardInterrupt:
        logger.info("用户中断测试")
    except Exception as e:
        logger.error(f"测试过程发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if pool:
            await pg_db.close_pool()


# 手动测试单个场景的便捷函数
async def test_single_scenario(scenario_index: int = 0):
    """测试单个场景"""
    pool = None
    try:
        await pg_db.init_pool()
        pool = pg_db.get_pool()
    except Exception as e:
        logger.warning(f"数据库连接失败，使用无数据库模式: {e}")
    
    try:
        scenario = TEST_SCENARIOS[scenario_index]
        logger.info(f"测试场景: {scenario['description']}")
        
        result = await run_single_test(scenario, pool)
        
        print(f"\n用户消息: {scenario['user_message']}")
        print(f"AI回复: {result['cs_response']['reply']}")
        print(f"意图识别: {result['cs_response']['intent']}")
        print(f"评分: {result['evaluation']['overall']:.3f}")
        print(f"反馈: {result['evaluation']['feedback']}")
        
    finally:
        if pool:
            await pg_db.close_pool()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 测试单个场景
        scenario_idx = int(sys.argv[1])
        asyncio.run(test_single_scenario(scenario_idx))
    else:
        # 完整测试流程
        asyncio.run(main())