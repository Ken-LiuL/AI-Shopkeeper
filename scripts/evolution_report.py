#!/usr/bin/env python3
"""
AI客服自动进化周报生成脚本

生成客服系统自我进化的周报，包括：
- 评分趋势分析
- 新增few-shot示例统计
- 知识库补丁汇总
- 低分回复分析和改进建议

可以通过cron定时执行
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.agents.customer_service.auto_evolve import get_evolution_manager
from src.database import get_db_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_evolution_report() -> str:
    """生成自动进化周报"""
    try:
        # 获取数据库连接
        pool = await get_db_pool()
        evolution_manager = get_evolution_manager(pool)

        # 获取统计数据
        stats = await evolution_manager.get_evolution_stats()

        # 生成报告
        report = _build_evolution_report(stats)

        # 保存报告
        await _save_report(report)

        await pool.close()
        return report

    except Exception as e:
        logger.error(f"Failed to generate evolution report: {e}")
        return f"报告生成失败: {e}"


def _build_evolution_report(stats: dict) -> str:
    """构建进化报告内容"""
    now = datetime.now()
    week_start = now - timedelta(days=7)

    eval_stats = stats.get("evaluation_stats", {})
    few_shot_stats = stats.get("few_shot_stats", {})
    improvement_stats = stats.get("improvement_stats", {})

    report = f"""# AI客服自我进化周报

**报告周期**: {week_start.strftime("%Y-%m-%d")} 至 {now.strftime("%Y-%m-%d")}
**生成时间**: {now.strftime("%Y-%m-%d %H:%M:%S")}

---

## 📊 评分趋势分析

### 总体表现
- **总评价数**: {eval_stats.get("total_evaluations", 0)} 次
- **平均评分**: {eval_stats.get("avg_score", 0):.3f} / 1.000
- **高分回复** (≥0.85): {eval_stats.get("high_scores", 0)} 次 ({_calc_percentage(eval_stats.get("high_scores", 0), eval_stats.get("total_evaluations", 1)):.1f}%)
- **低分回复** (<0.6): {eval_stats.get("low_scores", 0)} 次 ({_calc_percentage(eval_stats.get("low_scores", 0), eval_stats.get("total_evaluations", 1)):.1f}%)

### 质量评估
{_get_quality_assessment(eval_stats.get("avg_score", 0), eval_stats.get("high_scores", 0), eval_stats.get("low_scores", 0))}

---

## 🎯 Few-Shot自动进化

### 学习成果
- **新增候选示例**: {few_shot_stats.get("total_candidates", 0)} 个
- **覆盖场景类别**: {few_shot_stats.get("categories", 0)} 种
- **自动学习状态**: {"🟢 活跃" if few_shot_stats.get("total_candidates", 0) > 0 else "🟡 待激活"}

### 动态示例库状态
{_get_few_shot_status()}

---

## 🔄 知识库自动补充

### 补丁统计
- **生成改进记录**: {improvement_stats.get("total_improvements", 0)} 条
- **知识补丁状态**: {_get_knowledge_patches_status()}

### 自动学习效果
{_get_learning_effectiveness(improvement_stats.get("total_improvements", 0))}

---

## 🔍 系统进化分析

### 进化健康度
{_get_evolution_health_score(eval_stats, few_shot_stats, improvement_stats)}

### 改进建议
{_get_improvement_recommendations(eval_stats, few_shot_stats)}

---

## 📈 下周优化重点

{_get_next_week_focus(eval_stats)}

---

*本报告由AI客服自动进化系统生成，数据来源于真实对话评分和学习记录。*
"""

    return report


def _calc_percentage(numerator: int, denominator: int) -> float:
    """计算百分比"""
    return (numerator / denominator * 100) if denominator > 0 else 0


def _get_quality_assessment(avg_score: float, high_scores: int, low_scores: int) -> str:
    """获取质量评估"""
    if avg_score >= 0.8:
        return "✅ **优秀** - 系统表现稳定，持续高质量输出"
    elif avg_score >= 0.7:
        return "🟡 **良好** - 整体表现不错，仍有提升空间"
    elif avg_score >= 0.6:
        return "🟠 **一般** - 需要重点关注和优化"
    else:
        return "🔴 **需改进** - 系统表现不理想，建议人工介入"


def _get_few_shot_status() -> str:
    """获取few-shot状态"""
    try:
        few_shots_path = os.path.join(os.getcwd(), "data", "dynamic_few_shots.json")
        if os.path.exists(few_shots_path):
            with open(few_shots_path, encoding="utf-8") as f:
                few_shots = json.load(f)

            total_examples = sum(len(examples) for examples in few_shots.values())
            categories = list(few_shots.keys())

            status = f"- **总示例数**: {total_examples} 个\n"
            status += f"- **活跃类别**: {', '.join(categories[:5])}"
            if len(categories) > 5:
                status += f" 等{len(categories)}种"

            return status
        else:
            return "- 暂无动态示例库文件"
    except Exception as e:
        return f"- 获取状态失败: {e}"


def _get_knowledge_patches_status() -> str:
    """获取知识补丁状态"""
    try:
        patches_path = os.path.join(os.getcwd(), "data", "cs_knowledge_patches.json")
        if os.path.exists(patches_path):
            with open(patches_path, encoding="utf-8") as f:
                patches = json.load(f)

            return f"已累积 {len(patches)} 个知识补丁"
        else:
            return "暂无知识补丁"
    except Exception as e:
        return f"获取失败: {e}"


def _get_learning_effectiveness(improvements: int) -> str:
    """获取学习效果评估"""
    if improvements >= 10:
        return "🚀 **高效学习** - 系统积极识别和改进问题"
    elif improvements >= 5:
        return "📈 **稳步学习** - 系统正常识别改进机会"
    elif improvements >= 1:
        return "🌱 **初步学习** - 系统开始积累改进经验"
    else:
        return "😴 **学习待激活** - 建议增加对话量以触发学习"


def _get_evolution_health_score(
    eval_stats: dict, few_shot_stats: dict, improvement_stats: dict
) -> str:
    """计算进化健康度评分"""
    score = 0
    total_evaluations = eval_stats.get("total_evaluations", 0)
    avg_score = eval_stats.get("avg_score", 0)
    high_scores = eval_stats.get("high_scores", 0)

    # 评分质量权重 (40%)
    if avg_score >= 0.8:
        score += 40
    elif avg_score >= 0.7:
        score += 30
    elif avg_score >= 0.6:
        score += 20
    else:
        score += 10

    # 学习活跃度权重 (35%)
    candidates = few_shot_stats.get("total_candidates", 0)
    if candidates >= 10:
        score += 35
    elif candidates >= 5:
        score += 25
    elif candidates >= 1:
        score += 15

    # 改进响应度权重 (25%)
    improvements = improvement_stats.get("total_improvements", 0)
    if improvements >= 5:
        score += 25
    elif improvements >= 2:
        score += 15
    elif improvements >= 1:
        score += 10

    if score >= 80:
        return f"🌟 **健康度评分: {score}/100** - 系统运行良好，自我进化活跃"
    elif score >= 60:
        return f"💚 **健康度评分: {score}/100** - 系统状态良好，进化稳定"
    elif score >= 40:
        return f"🟡 **健康度评分: {score}/100** - 系统基本正常，需要更多数据"
    else:
        return f"🔴 **健康度评分: {score}/100** - 系统需要人工检查和调优"


def _get_improvement_recommendations(eval_stats: dict, few_shot_stats: dict) -> str:
    """获取改进建议"""
    recommendations = []

    avg_score = eval_stats.get("avg_score", 0)
    low_scores = eval_stats.get("low_scores", 0)
    total_evaluations = eval_stats.get("total_evaluations", 0)
    candidates = few_shot_stats.get("total_candidates", 0)

    if avg_score < 0.7:
        recommendations.append("📚 **加强知识库**: 当前平均评分偏低，建议人工审核知识库完整性")

    if low_scores > total_evaluations * 0.2:
        recommendations.append("🔍 **关注低分回复**: 低分回复比例较高，建议分析具体原因")

    if candidates < 5:
        recommendations.append("🎯 **激活自动学习**: few-shot学习不够活跃，建议增加对话量")

    if total_evaluations < 50:
        recommendations.append("📈 **扩大数据采样**: 评分样本较少，建议扩大评分覆盖范围")

    if not recommendations:
        recommendations.append("✅ **保持现状**: 系统运行良好，继续监控即可")

    return "\n".join(f"{i + 1}. {rec}" for i, rec in enumerate(recommendations))


def _get_next_week_focus(eval_stats: dict) -> str:
    """获取下周优化重点"""
    avg_score = eval_stats.get("avg_score", 0)
    low_scores = eval_stats.get("low_scores", 0)

    if avg_score < 0.6:
        return """1. **紧急**: 人工审核系统prompt和知识库
2. **重点**: 分析低分回复原因，手动补充关键知识
3. **监控**: 加强评分频次，每日检查系统表现"""
    elif avg_score < 0.75:
        return """1. **优化**: 让自动学习系统积累更多高质量示例
2. **完善**: 补充知识库缺失的专业领域内容
3. **测试**: 验证新增few-shot示例的效果"""
    else:
        return """1. **维护**: 保持系统稳定运行
2. **优化**: 持续收集用户反馈，微调细节
3. **拓展**: 考虑扩展到更多场景类别"""


async def _save_report(report: str) -> None:
    """保存报告到文件"""
    try:
        # 创建报告目录
        reports_dir = os.path.join(os.getcwd(), "data", "evolution_reports")
        os.makedirs(reports_dir, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evolution_report_{timestamp}.md"
        filepath = os.path.join(reports_dir, filename)

        # 写入文件
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info(f"Evolution report saved to: {filepath}")

        # 同时保存最新版本（用于API访问）
        latest_path = os.path.join(reports_dir, "latest.md")
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(report)

    except Exception as e:
        logger.error(f"Failed to save report: {e}")


async def main():
    """主函数"""
    print("🚀 生成AI客服自动进化周报...")

    report = await generate_evolution_report()

    print("\n" + "=" * 50)
    print(report)
    print("=" * 50)

    print("\n✅ 报告生成完成！")


if __name__ == "__main__":
    asyncio.run(main())
