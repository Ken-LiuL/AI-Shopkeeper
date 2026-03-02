#!/usr/bin/env python3
"""
更新 Agent 提示词，为竞品数据添加演示数据标识
"""

import re
from pathlib import Path


def update_prompt_files():
    """更新 agents/prompts/ 目录下的所有提示词文件"""

    prompts_dir = Path("src/agents/prompts")

    files_to_update = ["selection.py", "listing.py", "alert.py"]

    for filename in files_to_update:
        filepath = prompts_dir / filename

        if not filepath.exists():
            print(f"⚠️  文件不存在: {filepath}")
            continue

        print(f"📝 更新文件: {filepath}")

        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        # 备份原文件
        backup_path = filepath.with_suffix(".py.backup")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"   💾 备份到: {backup_path}")

        # 更新内容
        updated_content = update_prompt_content(content, filename)

        # 写入更新后的内容
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated_content)

        print("   ✅ 已更新")


def update_prompt_content(content: str, filename: str) -> str:
    """更新提示词内容"""

    if filename == "selection.py":
        # 更新竞品分析相关提示词
        content = re.sub(
            r"## 竞品([^#]+)数据",
            r'## 竞品\1数据\n⚠️ 注意：如显示"演示数据"或"🎭"标识的竞品信息仅供参考，请结合实际市场调研。',
            content,
            flags=re.MULTILINE,
        )

        # 为竞品分析输出添加数据质量说明
        content = re.sub(
            r"使用 output_competitor_analysis 工具输出结果",
            r'使用 output_competitor_analysis 工具输出结果。\n\n⚠️ 数据质量提示：分析结果中如包含"演示数据"标识的竞品信息，建议：\n1. 仅作为参考，不作为决策依据\n2. 结合实际市场调研验证\n3. 配置真实竞品数据源以提高准确性',
            content,
        )

    elif filename == "listing.py":
        # 为定价分析添加数据来源说明
        content = re.sub(
            r"# 竞品价格\n{competitor_prices}",
            r'# 竞品价格\n{competitor_prices}\n\n⚠️ 数据说明：如竞品数据标注"演示数据"，仅供定价参考，建议结合实际市场调研。',
            content,
        )

    elif filename == "alert.py":
        # 为预警分析添加数据质量提示
        content = re.sub(
            r"## 竞品数据（最近7天变化）",
            r'## 竞品数据（最近7天变化）\n⚠️ 数据质量：标注"演示数据"或"🎭"的信息为模拟数据，建议谨慎参考。',
            content,
        )

    return content


if __name__ == "__main__":
    print("🔄 开始更新 Agent 提示词文件...")
    update_prompt_files()
    print("\n✅ 所有提示词文件已更新完成")
