"""CustomerService Agent - 高质量单次 LLM 调用模式"""

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


def _load_dynamic_few_shots() -> dict:
    """加载动态few-shot示例（自动进化生成）"""
    few_shots_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "dynamic_few_shots.json"
    )
    try:
        with open(few_shots_path, encoding="utf-8") as f:
            few_shots = json.load(f)
            logger.info(f"Loaded {len(few_shots)} categories of dynamic few-shots")
            return few_shots
    except Exception as e:
        logger.debug(f"No dynamic few-shots found: {e}")
        return {}


def _load_knowledge_patches() -> list:
    """加载知识库补丁（自动进化生成）"""
    patches_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "data", "cs_knowledge_patches.json"
    )
    try:
        with open(patches_path, encoding="utf-8") as f:
            patches = json.load(f)
            logger.info(f"Loaded {len(patches)} knowledge patches")
            return patches
    except Exception as e:
        logger.debug(f"No knowledge patches found: {e}")
        return []


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
    """根据用户消息动态选择最相关的 few-shot 示例（优先使用自动进化的动态示例）"""

    # 1. 优先加载动态few-shot示例（自动进化系统生成）
    dynamic_few_shots = _load_dynamic_few_shots()

    # 2. 如果没有动态示例，使用结构化知识库中的示例
    if not dynamic_few_shots:
        few_shots = sk.get("dynamic_few_shot", {})
        if not few_shots:
            return _default_few_shot()
    else:
        few_shots = dynamic_few_shots

    # 3. 关键词 → 类别映射（统一的分类策略）
    category_keywords = {
        "after_sales": ["退", "换", "坏", "不好", "质量", "差", "退款", "赔", "损坏", "不满"],
        "medical_safety": ["血压", "血糖", "吃药", "治疗", "症状", "病", "疼", "痛"],
        "logistics": ["送", "到", "配送", "多久", "发货", "等"],
        "product_inquiry": ["推荐", "哪个好", "买", "有没有", "多少钱", "怎么选"],
        "usage_guidance": ["怎么用", "使用方法", "用法", "操作"],
        "recommendation": ["推荐", "哪款", "选择", "比较"],
        "complaint_handling": ["投诉", "不满意", "态度", "服务"],
        "greeting": ["你好", "在吗", "hello", "hi"],
    }

    # 4. 匹配最相关的类别
    matched_categories = []
    for category, keywords in category_keywords.items():
        score = sum(1 for kw in keywords if kw in user_message)
        if score > 0:
            matched_categories.append((category, score))
    matched_categories.sort(key=lambda x: -x[1])

    # 5. 选择匹配的示例
    selected = []
    used_categories = set()

    # 优先选择匹配度高的类别
    for category, _ in matched_categories[:2]:
        if category in few_shots:
            examples = few_shots[category][:1]  # 每类取最高分的1个
            for example in examples:
                # 动态few-shots的格式适配
                if "user_message" in example and "ai_response" in example:
                    selected.append(
                        {"user": example["user_message"], "assistant": example["ai_response"]}
                    )
                elif "user" in example and "assistant" in example:
                    selected.append(example)
                used_categories.add(category)

    # 6. 补充其他类别的优秀示例，总共不超过4个
    for category, examples in few_shots.items():
        if len(selected) >= 4:
            break
        if category not in used_categories and examples:
            example = examples[0]  # 取该类别最高分示例
            if "user_message" in example and "ai_response" in example:
                selected.append(
                    {"user": example["user_message"], "assistant": example["ai_response"]}
                )
            elif "user" in example and "assistant" in example:
                selected.append(example)

    if not selected:
        return _default_few_shot()

    # 7. 格式化输出
    lines = []
    for ex in selected:
        user_msg = ex.get("user", "")[:100]  # 限制长度
        assistant_reply = ex.get("assistant", "")[:200]
        lines.append(f"用户：{user_msg}\n客服：{assistant_reply}\n")

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
    """构建高质量系统提示词 - 结构化知识 + 动态 few-shot + 自动补丁"""
    sk = _load_structured_knowledge()
    store = sk.get("store_profile", {})

    # 知识库按类别格式化（基础知识库）
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

    # 加载并合并知识库补丁（自动进化系统生成）
    knowledge_patches = _load_knowledge_patches()
    if knowledge_patches:
        kb_content += "\n### 🔄 自动补充知识（基于对话学习）\n"
        for patch in knowledge_patches[-10:]:  # 只显示最近10个补丁
            category = patch.get("category", "其他")
            content = patch.get("knowledge_content", "")
            question_pattern = patch.get("question_pattern", "")
            if content:
                kb_content += f"- **{category}**: {question_pattern} → {content}\n"

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
- 平台：美团闪购（即时零售，{store.get("delivery_time", "30-60分钟")}送达）
- 范围：{store.get("delivery_range", "3公里内")}
- 商品：{store.get("total_products", 1914)}款，覆盖：
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

# 回复要求（基于真实对话优化）
1. **绝对禁止无意义回复**：不能只说"稍等"、"好的"、"嗯"，每次回复必须有实质帮助
2. **100字以内**，复杂问题不超过150字，但要信息量充足
3. 以"亲"开头，用1-2个emoji，语气温暖但专业
4. **先理解再回答** - 不确定时追问，基于上下文给出针对性回复
5. **实用信息优先** - 直接回答客户关切：用量、年龄适用性、安全性、时效等
6. **主动提供选择** - 遇到问题主动给2-3个解决方案，让客户选择
7. **紧急情况特殊处理** - 发现"发烧"、"急需"等关键词立即加急处理
8. **适当追销** - 推荐关联耗材（试纸、袖带、棉片），最多1-2个，自然融入
9. **转人工 needs_human=true 仅限**：用户提到投诉/315/律师/起诉/举报，或涉及人身安全

# 高频问题必备回复模板
- 产品用量："亲，这个产品是[用量说明]，[推荐购买建议]😊"
- 年龄适用："亲，[年龄]岁[适用性说明]，[安全建议]😊"
- 配送催单："亲，我马上联系骑手！[处理措施]，如有延误[补偿说明]😊"
- 质量问题："亲，质量问题我们全责！您可以选择：1⃣️退款 2⃣️换货，运费我们承担😊"
- 医疗级询问："亲，这是[级别]医疗器械，有国家认证，安全可靠😊"
- 隐私配送："亲，我们都是保密配送，包装不显示商品信息，请放心😊"

# intent 分类
从以下选择：product_inquiry, usage_question, recommendation, comparison, logistics, after_sales, complaint, medical_advice, greeting, other"""


def build_user_message_with_context(
    user_message: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
    conversation_context: str | None = None,
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

    # 对话状态上下文
    if conversation_context:
        parts.append(f"## 对话状态提示\n{conversation_context}")

    # 动态 few-shot
    few_shot = _select_few_shot(user_message, sk)
    parts.append(f"## 参考对话（模仿这个风格和质量）\n{few_shot}")

    # 用户问题
    parts.append(f"## 用户问题\n{user_message}")

    return "\n\n".join(parts)
