"""
AI客服自我进化系统
实现持续自动学习闭环，系统随着对话积累自动进化
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CustomerServiceAutoEvolution:
    """客服自我进化管理器"""

    def __init__(self, pool=None):
        self.pool = pool
        self.data_dir = os.path.join(os.getcwd(), "data")
        self.dynamic_few_shots_path = os.path.join(self.data_dir, "dynamic_few_shots.json")
        self.knowledge_patches_path = os.path.join(self.data_dir, "cs_knowledge_patches.json")
        
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)

    async def after_reply_hook(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        context: Optional[dict] = None
    ) -> None:
        """
        每次回复后的异步处理钩子
        
        Args:
            session_id: 会话ID
            user_msg: 用户消息
            reply: AI回复
            context: 上下文信息（包含conversation_history, product_results等）
        """
        try:
            # 异步执行评分和进化逻辑（不阻塞主响应）
            asyncio.create_task(self._process_reply_evolution(
                session_id, user_msg, reply, context or {}
            ))
            logger.debug(f"Evolution task created for session {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to create evolution task: {e}")

    async def _process_reply_evolution(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        context: dict
    ) -> None:
        """处理回复的自动进化逻辑"""
        try:
            if not self.pool:
                logger.warning("No database pool available for evolution")
                return
                
            # 1. 自动评分
            score_result = await self._auto_score_reply(
                session_id, user_msg, reply, context
            )
            
            if not score_result:
                return
                
            overall_score = score_result.get('overall', 0.0)
            
            # 2. 根据评分触发不同动作
            if overall_score >= 0.85:
                # 高分：加入few-shot候选池
                await self._handle_high_score_reply(
                    session_id, user_msg, reply, score_result, context
                )
            elif overall_score < 0.6:
                # 低分：分析原因并触发知识库补充
                await self._handle_low_score_reply(
                    session_id, user_msg, reply, score_result, context
                )
            else:
                # 中间分：仅记录
                logger.info(f"Medium score reply logged: {overall_score:.2f}")
                
        except Exception as e:
            logger.error(f"Failed to process reply evolution: {e}")

    async def _auto_score_reply(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        context: dict
    ) -> Optional[dict]:
        """自动对回复进行评分"""
        try:
            from .evaluator import evaluate_reply
            
            # 使用现有的评分器进行评分
            scores = await evaluate_reply(
                user_message=user_msg,
                ai_reply=reply,
                conversation_history=context.get('conversation_history'),
                product_results=context.get('product_results')
            )
            
            # 存储评分到数据库
            await self._store_evaluation_result(session_id, user_msg, reply, scores)
            
            return scores
            
        except Exception as e:
            logger.error(f"Failed to auto score reply: {e}")
            return None

    async def _store_evaluation_result(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        scores: dict
    ) -> None:
        """存储评分结果到数据库"""
        try:
            # 确保评分表存在
            await self._ensure_evolution_tables()
            
            # 存储评分
            await self.pool.execute("""
                INSERT INTO cs_reply_scores (
                    session_id, user_message, ai_reply,
                    accuracy, professionalism, tone, resolution, compliance, overall,
                    feedback, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            """, 
                session_id,
                user_msg[:1000],
                reply[:2000], 
                scores.get('accuracy', 0),
                scores.get('professionalism', 0),
                scores.get('tone', 0),
                scores.get('resolution', 0),
                scores.get('compliance', 0),
                scores.get('overall', 0),
                scores.get('feedback', '')[:500]
            )
            
        except Exception as e:
            logger.error(f"Failed to store evaluation result: {e}")

    async def _handle_high_score_reply(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        scores: dict,
        context: dict
    ) -> None:
        """处理高分回复：加入few-shot候选池并更新dynamic_few_shots.json"""
        try:
            # 1. 分析回复场景类别
            category = await self._categorize_interaction(user_msg, reply, context)
            
            # 2. 存储到few-shot候选池
            await self.pool.execute("""
                INSERT INTO cs_few_shot_candidates (
                    category, user_msg, reply, score, session_id, created_at
                ) VALUES ($1, $2, $3, $4, $5, NOW())
            """, category, user_msg, reply, scores.get('overall', 0), session_id)
            
            # 3. 更新dynamic_few_shots.json
            await self._update_dynamic_few_shots(category, user_msg, reply, scores.get('overall', 0))
            
            logger.info(f"High score reply added to few-shot pool: {scores.get('overall', 0):.2f}")
            
        except Exception as e:
            logger.error(f"Failed to handle high score reply: {e}")

    async def _handle_low_score_reply(
        self,
        session_id: str,
        user_msg: str,
        reply: str,
        scores: dict,
        context: dict
    ) -> None:
        """处理低分回复：分析原因并补充知识库"""
        try:
            # 1. 分析低分原因
            analysis = await self._analyze_low_score_reason(
                user_msg, reply, scores, context
            )
            
            # 2. 记录到改进日志表
            await self.pool.execute("""
                INSERT INTO cs_improvement_log (
                    session_id, user_msg, reply, score, analysis, created_at
                ) VALUES ($1, $2, $3, $4, $5, NOW())
            """, session_id, user_msg, reply, scores.get('overall', 0), analysis)
            
            # 3. 如果分析出缺少特定知识，自动补充知识库
            await self._auto_patch_knowledge(analysis, user_msg, reply)
            
            logger.warning(f"Low score reply analyzed: {scores.get('overall', 0):.2f}")
            
        except Exception as e:
            logger.error(f"Failed to handle low score reply: {e}")

    async def _categorize_interaction(
        self,
        user_msg: str,
        reply: str,
        context: dict
    ) -> str:
        """分析交互的场景类别"""
        try:
            from ..llm import call_tool, MODEL_FLASH
            
            tool_schema = {
                "name": "categorize_cs_interaction",
                "description": "分析客服交互的场景类别",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": [
                                "product_inquiry", "usage_guidance", "recommendation",
                                "comparison", "pricing", "logistics", "after_sales", 
                                "complaint_handling", "medical_safety", "greeting"
                            ],
                            "description": "交互的主要场景类别"
                        }
                    },
                    "required": ["category"]
                }
            }
            
            prompt = f"""分析以下客服交互的场景类别：
            
用户消息: {user_msg}
AI回复: {reply}

请选择最符合的场景类别。"""

            result = await call_tool(
                prompt=prompt,
                tool=tool_schema,
                model=MODEL_FLASH,
                system="你是客服质量分析专家，专门分析客服交互的场景类别。",
                trace_name="cs_interaction_categorization"
            )
            
            return result.get('category', 'other')
            
        except Exception as e:
            logger.error(f"Failed to categorize interaction: {e}")
            return 'other'

    async def _update_dynamic_few_shots(
        self,
        category: str,
        user_msg: str,
        reply: str,
        score: float
    ) -> None:
        """更新dynamic_few_shots.json文件"""
        try:
            # 读取现有few-shots
            few_shots = {}
            if os.path.exists(self.dynamic_few_shots_path):
                with open(self.dynamic_few_shots_path, 'r', encoding='utf-8') as f:
                    few_shots = json.load(f)
            
            # 初始化类别
            if category not in few_shots:
                few_shots[category] = []
            
            # 创建新示例
            new_example = {
                "user_message": user_msg,
                "ai_response": reply,
                "score": score,
                "timestamp": datetime.now().isoformat(),
                "source": "auto_evolution"
            }
            
            # 添加新示例
            few_shots[category].append(new_example)
            
            # 排序并保持top-3
            few_shots[category].sort(key=lambda x: x.get('score', 0), reverse=True)
            few_shots[category] = few_shots[category][:3]
            
            # 写入文件
            with open(self.dynamic_few_shots_path, 'w', encoding='utf-8') as f:
                json.dump(few_shots, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Updated dynamic few-shots for category: {category}")
            
        except Exception as e:
            logger.error(f"Failed to update dynamic few-shots: {e}")

    async def _analyze_low_score_reason(
        self,
        user_msg: str,
        reply: str,
        scores: dict,
        context: dict
    ) -> str:
        """分析低分回复的原因"""
        try:
            from ..llm import call_tool, MODEL_DEEPSEEK
            
            tool_schema = {
                "name": "analyze_low_score_reason",
                "description": "分析低分客服回复的原因",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "primary_issue": {
                            "type": "string",
                            "enum": [
                                "missing_product_knowledge",
                                "incorrect_medical_info",
                                "inappropriate_tone",
                                "incomplete_answer",
                                "compliance_violation",
                                "poor_after_sales_handling"
                            ],
                            "description": "主要问题类型"
                        },
                        "missing_knowledge": {
                            "type": "string",
                            "description": "缺少的具体知识内容"
                        },
                        "improvement_suggestion": {
                            "type": "string",
                            "description": "改进建议"
                        }
                    },
                    "required": ["primary_issue", "improvement_suggestion"]
                }
            }
            
            feedback = scores.get('feedback', '')
            prompt = f"""分析低分客服回复的问题：

用户问题: {user_msg}
AI回复: {reply}
各维度评分: {json.dumps(scores, ensure_ascii=False)}
评分反馈: {feedback}

请分析主要问题并提供改进建议。如果是知识缺失，请具体说明缺少什么知识。"""

            result = await call_tool(
                prompt=prompt,
                tool=tool_schema,
                model=MODEL_DEEPSEEK,
                system="你是客服质量改进专家，专门分析客服回复的问题并提供改进建议。",
                trace_name="cs_low_score_analysis"
            )
            
            return json.dumps(result, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Failed to analyze low score reason: {e}")
            return f"分析失败: {str(e)}"

    async def _auto_patch_knowledge(
        self,
        analysis: str,
        user_msg: str,
        reply: str
    ) -> None:
        """自动补充知识库"""
        try:
            analysis_data = json.loads(analysis)
            
            # 只有在确实缺少知识的情况下才补充
            if analysis_data.get('primary_issue') == 'missing_product_knowledge':
                missing_knowledge = analysis_data.get('missing_knowledge')
                
                if missing_knowledge:
                    # 生成知识补丁
                    patch = await self._generate_knowledge_patch(
                        user_msg, missing_knowledge
                    )
                    
                    if patch:
                        await self._add_knowledge_patch(patch)
                        
        except Exception as e:
            logger.error(f"Failed to auto patch knowledge: {e}")

    async def _generate_knowledge_patch(
        self,
        user_msg: str,
        missing_knowledge: str
    ) -> Optional[dict]:
        """生成知识库补丁"""
        try:
            from ..llm import call_tool, MODEL_DEEPSEEK
            
            tool_schema = {
                "name": "generate_knowledge_patch",
                "description": "生成客服知识库补丁",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "知识类别"
                        },
                        "question_pattern": {
                            "type": "string",
                            "description": "用户问题模式"
                        },
                        "knowledge_content": {
                            "type": "string",
                            "description": "补充的知识内容"
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "相关关键词"
                        }
                    },
                    "required": ["category", "question_pattern", "knowledge_content"]
                }
            }
            
            prompt = f"""根据用户问题和缺失的知识，生成知识库补丁：

用户问题: {user_msg}
缺失知识: {missing_knowledge}

请生成一个知识库补丁，包含：
1. 适当的知识类别
2. 用户问题模式（通用化）
3. 具体的知识内容
4. 相关关键词"""

            result = await call_tool(
                prompt=prompt,
                tool=tool_schema,
                model=MODEL_DEEPSEEK,
                system="你是知识库管理专家，专门生成准确的医疗器械客服知识补丁。",
                trace_name="cs_knowledge_patch_generation"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate knowledge patch: {e}")
            return None

    async def _add_knowledge_patch(self, patch: dict) -> None:
        """添加知识库补丁到patches文件"""
        try:
            patches = []
            
            # 读取现有patches
            if os.path.exists(self.knowledge_patches_path):
                with open(self.knowledge_patches_path, 'r', encoding='utf-8') as f:
                    patches = json.load(f)
            
            # 检查重复
            patch_content = patch.get('knowledge_content', '')
            for existing_patch in patches:
                if existing_patch.get('knowledge_content') == patch_content:
                    logger.info("Knowledge patch already exists, skipping")
                    return
            
            # 添加新补丁
            patch['created_at'] = datetime.now().isoformat()
            patch['id'] = len(patches) + 1
            patches.append(patch)
            
            # 写入文件
            with open(self.knowledge_patches_path, 'w', encoding='utf-8') as f:
                json.dump(patches, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Added knowledge patch: {patch.get('category')}")
            
        except Exception as e:
            logger.error(f"Failed to add knowledge patch: {e}")

    async def _ensure_evolution_tables(self) -> None:
        """确保自动进化需要的数据库表存在"""
        try:
            # cs_improvement_log 表
            await self.pool.execute("""
                CREATE TABLE IF NOT EXISTS cs_improvement_log (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT,
                    user_msg TEXT,
                    reply TEXT,
                    score REAL,
                    analysis TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            
            # cs_few_shot_candidates 表
            await self.pool.execute("""
                CREATE TABLE IF NOT EXISTS cs_few_shot_candidates (
                    id SERIAL PRIMARY KEY,
                    category TEXT,
                    user_msg TEXT,
                    reply TEXT,
                    score REAL,
                    session_id TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            
            # 创建索引
            await self.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_cs_improvement_log_score
                ON cs_improvement_log(score)
            """)
            
            await self.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_cs_few_shot_candidates_score
                ON cs_few_shot_candidates(score DESC)
            """)
            
            await self.pool.execute("""
                CREATE INDEX IF NOT EXISTS idx_cs_few_shot_candidates_category
                ON cs_few_shot_candidates(category)
            """)
            
        except Exception as e:
            logger.error(f"Failed to ensure evolution tables: {e}")

    async def get_evolution_stats(self) -> dict:
        """获取自我进化统计数据"""
        try:
            if not self.pool:
                return {}
                
            # 评分统计
            score_stats = await self.pool.fetchrow("""
                SELECT 
                    COUNT(*) as total_evaluations,
                    AVG(overall) as avg_score,
                    COUNT(CASE WHEN overall >= 0.85 THEN 1 END) as high_scores,
                    COUNT(CASE WHEN overall < 0.6 THEN 1 END) as low_scores
                FROM cs_reply_scores 
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """)
            
            # Few-shot候选数量
            few_shot_stats = await self.pool.fetchrow("""
                SELECT 
                    COUNT(*) as total_candidates,
                    COUNT(DISTINCT category) as categories
                FROM cs_few_shot_candidates
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """)
            
            # 改进日志数量
            improvement_stats = await self.pool.fetchrow("""
                SELECT COUNT(*) as total_improvements
                FROM cs_improvement_log
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """)
            
            return {
                "evaluation_stats": dict(score_stats) if score_stats else {},
                "few_shot_stats": dict(few_shot_stats) if few_shot_stats else {},
                "improvement_stats": dict(improvement_stats) if improvement_stats else {},
                "generated_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to get evolution stats: {e}")
            return {}


# 全局进化管理器实例
_evolution_manager: Optional[CustomerServiceAutoEvolution] = None


def get_evolution_manager(pool=None) -> CustomerServiceAutoEvolution:
    """获取全局进化管理器实例"""
    global _evolution_manager
    if _evolution_manager is None:
        _evolution_manager = CustomerServiceAutoEvolution(pool)
    elif pool and _evolution_manager.pool != pool:
        _evolution_manager.pool = pool
    return _evolution_manager


async def after_reply_hook(
    session_id: str,
    user_msg: str, 
    reply: str,
    context: Optional[dict] = None,
    pool=None
) -> None:
    """
    全局after_reply_hook函数，供nodes.py调用
    
    Args:
        session_id: 会话ID
        user_msg: 用户消息
        reply: AI回复
        context: 上下文信息
        pool: 数据库连接池
    """
    try:
        manager = get_evolution_manager(pool)
        await manager.after_reply_hook(session_id, user_msg, reply, context)
    except Exception as e:
        logger.error(f"Global after_reply_hook failed: {e}")