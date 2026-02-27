"""CustomerService Agent — 高质量单次 LLM 调用模式"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# ── 售后决策树 ─────────────────────────────────────────────────
AFTER_SALES_SCRIPTS = {
    "return_policy": "未拆封商品7天内可无理由退货（保持完整包装）。已拆封医疗器械因卫生原因，仅质量问题可退换。",
    "quality_issue": "质量问题我们全责处理：15天内退换，承担运费，请拍照保留凭证。",
    "exchange": "收到商品48小时内支持换货，超时可协商处理。",
    "refund_timeline": "退款审核通过后1-3工作日原路退回。",
    "expired_product": "过期商品无条件退换，非常抱歉给您带来困扰。",
    "shipping_cost": "质量问题我们承担运费；非质量问题退货客户承担运费。运费险订单可申请赔付。",
}

# ── 结构化知识 ──────────────────────────────────────────────────
_structured_knowledge: dict | None = None


def _load_structured_knowledge() -> dict:
    """加载结构化知识库文件"""
    global _structured_knowledge
    if _structured_knowledge is not None:
        return _structured_knowledge

    knowledge_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "cs_knowledge_structured.json"
    )
    try:
        with open(knowledge_path, encoding="utf-8") as f:
            _structured_knowledge = json.load(f)
            logger.info("Loaded structured CS knowledge")
    except Exception as e:
        logger.warning(f"Failed to load structured knowledge: {e}")
        _structured_knowledge = {}
    return _structured_knowledge


def _format_product_expertise(sk: dict) -> str:
    """格式化商品专业知识"""
    expertise = sk.get("product_expertise", {})
    if not expertise:
        return ""

    lines = []
    for key, info in expertise.items():
        name = key.replace("_", " ").title()
        lines.append(f"\n### {name}")
        for point in info.get("key_knowledge", []):
            lines.append(f"- {point}")
        if info.get("cross_sell"):
            lines.append(f"- 关联推荐：{', '.join(info['cross_sell'])}")
    return "\n".join(lines)


def _format_after_sales_tree(sk: dict) -> str:
    """格式化售后决策树"""
    tree = sk.get("after_sales_decision_tree", {})
    if not tree:
        # fallback to AFTER_SALES_SCRIPTS
        return "\n".join(f"- **{k}**: {v}" for k, v in AFTER_SALES_SCRIPTS.items())

    lines = []
    for category, info in tree.items():
        lines.append(f"\n### {category}")
        conditions = info.get("conditions", {})
        for cond, action in conditions.items():
            lines.append(f"- {cond} → {action.get('response', '')}")
        for extra_key in ["refund_timeline", "shipping_cost"]:
            if extra_key in info:
                lines.append(f"- {extra_key}: {info[extra_key]}")
    return "\n".join(lines)


def _format_conversation_strategies(sk: dict) -> str:
    """格式化对话策略"""
    strategies = sk.get("conversation_strategies", {})
    if not strategies:
        return ""

    lines = []
    for name, info in strategies.items():
        lines.append(f"\n### {name.replace('_', ' ').title()}")
        lines.append(f"策略：{info.get('strategy', '')}")
        steps = info.get("steps") or info.get("rules", [])
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
    return "\n".join(lines)


def _select_few_shot(user_message: str, sk: dict) -> str:
    """根据用户消息动态选择最相关的 few-shot 示例"""
    few_shots = sk.get("dynamic_few_shot", {})
    if not few_shots:
        return _default_few_shot()

    # 关键词 → 类别映射
    category_keywords = {
        "after_sales": ["退", "换", "坏", "不好", "质量", "差", "退款", "赔", "损坏", "不满"],
        "medical_redirect": ["血压", "血糖", "吃药", "治疗", "症状", "病", "疼", "痛"],
        "logistics": ["送", "到", "配送", "多久", "发货", "等"],
        "product_inquiry": ["推荐", "哪个好", "买", "有没有", "多少钱", "怎么选"],
    }

    # 匹配最相关的类别
    matched_categories = []
    for category, keywords in category_keywords.items():
        score = sum(1 for kw in keywords if kw in user_message)
        if score > 0:
            matched_categories.append((category, score))
    matched_categories.sort(key=lambda x: -x[1])

    # 选择匹配的 + 补充通用的
    selected = []
    used_categories = set()
    for category, _ in matched_categories[:2]:
        if category in few_shots:
            for example in few_shots[category][:1]:  # 每类取 1 个
                selected.append(example)
                used_categories.add(category)

    # 补充未匹配的类别各 1 个，总共不超过 4 个
    for category, examples in few_shots.items():
        if len(selected) >= 4:
            break
        if category not in used_categories and examples:
            selected.append(examples[0])

    if not selected:
        return _default_few_shot()

    lines = []
    for ex in selected:
        lines.append(f"用户：{ex['user']}\n客服：{ex['assistant']}\n")
    return "\n".join(lines)


def _default_few_shot() -> str:
    return """用户：给老人买个血压计，哪个好？
客服：亲，推荐上臂式电子血压计~大屏显示+语音播报，特别适合老人😊 上臂式比腕式更准确，操作简单。需要帮您推荐具体型号吗？

用户：口罩质量太差了，要退款
客服：亲，很抱歉给您带来不好的体验😔 请问具体是什么问题呢？未拆封可直接退，质量问题已拆封也可退换，我们承担运费~

用户：我血压150，该怎么办？
客服：亲，血压相关问题建议咨询医生🙏 日常监测很重要，我们有多款血压计方便居家追踪。需要推荐吗？

用户：下单多久能送到？
客服：亲，下单后30-60分钟送达~可以在订单详情实时查看骑手位置😊
"""


def build_system_prompt(knowledge_base: list[dict], after_sales_scripts: dict | None = None) -> str:
    """构建高质量系统提示词 — 结构化知识 + 动态 few-shot"""
    sk = _load_structured_knowledge()
    store = sk.get("store_profile", {})

    # 知识库按类别格式化
    kb_content = ""
    if knowledge_base:
        kb_by_cat: dict[str, list] = {}
        for item in knowledge_base:
            cat = item.get("category", "其他")
            kb_by_cat.setdefault(cat, []).append(item)
        for cat, items in kb_by_cat.items():
            kb_content += f"\n### {cat}\n"
            for item in items:
                q = item.get("question", "")
                a = item.get("answer", "")
                if q:
                    kb_content += f"- Q: {q} → {a}\n"
                else:
                    kb_content += f"- {a}\n"

    # 商品专业知识
    product_expertise = _format_product_expertise(sk)
    # 售后决策树
    after_sales_tree = _format_after_sales_tree(sk)
    # 对话策略
    conv_strategies = _format_conversation_strategies(sk)
    # 合规规则
    compliance = sk.get("compliance_rules", {})
    forbidden = compliance.get("absolute_forbidden", [])
    redirects = compliance.get("safe_redirects", {})

    forbidden_text = "\n".join(f"- ❌ {f}" for f in forbidden) if forbidden else ""
    redirect_text = "\n".join(f"- {k}: {v}" for k, v in redirects.items()) if redirects else ""

    # 店铺类别信息
    categories_text = ""
    for cat in store.get("top_categories", []):
        categories_text += f"  - {cat['name']}({cat['count']}款): {cat['examples']}\n"

    return f"""# 你是谁
你是"小康"，美团即时零售医疗器械专营店的AI客服。你专业、温暖、高效。

# 店铺
- 平台：美团闪购（即时零售，{store.get('delivery_time', '30-60分钟')}送达）
- 范围：{store.get('delivery_range', '3公里内')}
- 商品：{store.get('total_products', 1914)}款，覆盖：
{categories_text}
# 商品专业知识（回答时引用这些知识显得专业）
{product_expertise}

# FAQ 知识库
{kb_content}

# 售后决策树（根据具体情况选择对应方案）
{after_sales_tree}

# 对话策略
{conv_strategies}

# 合规红线
{forbidden_text}

## 安全引导话术
{redirect_text}

# 回复要求
1. **100字以内**，复杂问题不超过150字
2. 以"亲"开头，用1-2个emoji
3. **先理解再回答** — 不确定用户意图时追问，不要猜
4. **用知识说话** — 引用具体参数、政策、使用方法，而不是泛泛而谈
5. **适当追销** — 推荐关联耗材（试纸、袖带、棉片），但最多1-2个，自然融入
6. **转人工 needs_human=true 仅限**：用户提到投诉/315/律师/起诉/举报，或涉及人身安全

# intent 分类
从以下选择：product_inquiry, usage_question, recommendation, comparison, logistics, after_sales, complaint, medical_advice, greeting, other"""


def build_user_message_with_context(
    user_message: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
) -> str:
    """构建包含上下文的用户消息"""
    sk = _load_structured_knowledge()
    parts = []

    # 对话历史
    if conversation_history:
        recent = conversation_history[-20:]
        if recent:
            history_lines = []
            for msg in recent:
                role = "用户" if msg.get("role") == "user" else "客服"
                history_lines.append(f"{role}：{msg.get('content', '')}")
            parts.append("## 对话历史\n" + "\n".join(history_lines))

    # 商品搜索结果
    if product_results:
        product_lines = []
        for i, p in enumerate(product_results[:5], 1):
            desc = p.get("description", p.get("name", ""))
            product_lines.append(f"{i}. {desc}")
        parts.append("## 店内相关商品\n" + "\n".join(product_lines))

    # 动态 few-shot
    few_shot = _select_few_shot(user_message, sk)
    parts.append(f"## 参考对话（模仿这个风格和质量）\n{few_shot}")

    # 用户问题
    parts.append(f"## 用户问题\n{user_message}")

    return "\n\n".join(parts)
