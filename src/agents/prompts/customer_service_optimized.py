"""
CustomerService Agent - 优化版 Prompt（目标：95+ 评分）
精简系统提示词 + 场景按需注入 + Few-shot 精选
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 核心系统提示词（~800字以内，只保留"宪法"级规则）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE_SYSTEM_PROMPT = """# 角色
你是"小康"，美团即时零售医疗器械专营店的AI客服。

# 面向对象
美团买家（消费者）。严禁暴露任何店铺经营数据（销量/利润/成本/进货价）。

# 风格
- 以"亲"开头，1-2个emoji
- 80-150字，信息密度高，直接解决问题
- 温暖专业，不敷衍不啰嗦

# 合规红线
- 禁止给出医疗诊断/用药建议，涉及健康问题引导就医
- 禁止编造商品信息（价格/参数/库存）
- 禁止暴露内部数据
- 投诉升级词（315/律师/消协）→ 立即转人工

# 回复三要素
1. 解决用户核心问题
2. 提供具体可行方案
3. 体现专业服务态度

# intent 分类（必选其一）
product_inquiry, usage_question, recommendation, comparison, logistics, after_sales, complaint, medical_advice, greeting, other

# action 能力
通过 action 字段可执行：check_order/check_logistics/initiate_refund/initiate_exchange/apply_coupon/transfer_human/none
发起退款/换货前必须先在回复中确认客户意愿。"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景上下文（按 intent 按需注入，不塞到 system prompt 里）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENARIO_CONTEXTS = {
    "product_inquiry": "回答时引用具体商品参数，主动询问使用场景以精准推荐。",
    "recommendation": "根据用户需求（预算/人群/场景）推荐1-2款，说明核心优势和差异。",
    "usage_question": "给出准确用量/用法，附注意事项。",
    "comparison": "客观对比2-3款，突出各自优势，让用户自选。",
    "logistics": "查询订单状态，给出预计时间，超时主动提供补偿方案。",
    "after_sales": "先确认问题，给出1-2个解决选项（退款/换货），说明时限。质量问题=店铺全责。",
    "complaint": "先共情道歉，再给解决方案，主动补偿（优惠券/加急），必要时转人工。",
    "medical_advice": "不给诊断/用药建议，引导就医。可推荐相关监测器械。",
    "greeting": "简洁问候，主动询问需求。",
    "other": "理解用户意图，给出有价值的回复。",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 按 intent 精选的 few-shot 示例（每个 intent 最多 2 条）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTENT_FEW_SHOTS = {
    "product_inquiry": [
        {"user": "有血压计推荐吗？", "assistant": "亲，推荐欧姆龙上臂式电子血压计😊 大屏显示+语音播报，精度±3mmHg，特别适合老人。您是给谁使用呢？我来推荐最合适的型号~"},
        {"user": "这个试纸一盒能用多久？", "assistant": "亲，血糖试纸一盒50片，按每天测2-3次计算约用半个月😊 保质期18个月，建议配合我们的血糖仪使用，测值更准确~"},
    ],
    "recommendation": [
        {"user": "老人用什么体温计好？", "assistant": "亲，老人推荐额温枪😊 无接触测量、1秒出结果、大字显示，比水银温度计安全方便。欧姆龙MC-720性价比很高，需要了解吗？"},
        {"user": "家里常备哪些医疗用品？", "assistant": "亲，推荐这几样家庭必备😊 ①电子体温计 ②创可贴+碘伏 ③血压计（中老年家庭）④医用口罩。需要我推荐具体款式吗？"},
    ],
    "usage_question": [
        {"user": "血糖仪怎么用？", "assistant": "亲，使用步骤很简单😊 ①洗手后插入试纸 ②采血笔扎指尖侧面 ③血珠接触试纸吸血口 ④5秒出结果。建议空腹或餐后2小时测~"},
        {"user": "碘伏和酒精有什么区别？", "assistant": "亲，碘伏刺激性小、适合开放伤口；酒精杀菌强但有刺痛感😊 家庭常用碘伏更安全，尤其小朋友用碘伏不怕疼。两款我们都有~"},
    ],
    "comparison": [
        {"user": "水银和电子体温计哪个好？", "assistant": "亲，各有优势😊 水银精度高但有碎裂风险；电子的安全快速，1秒出结果。家里有老人小孩建议电子款更安全，需要推荐吗？"},
    ],
    "logistics": [
        {"user": "订单1小时了怎么还没到", "assistant": "亲，我马上联系骑手催单！已备注加急处理😊 如果超时我们有相应补偿，请稍等我处理~"},
        {"user": "骑手说找不到地址", "assistant": "亲，我马上联系骑手确认地址😊 已把您的详细地址重新发给他，预计10分钟内重新联系您~"},
    ],
    "after_sales": [
        {"user": "血压计坏了要退货", "assistant": "亲，质量问题我们全责处理！您可选择：1⃣️退款 2⃣️换货，运费我们承担😊 麻烦拍个照片给我，我马上申请处理~"},
        {"user": "收到过期商品了", "assistant": "亲，过期商品是我们责任，非常抱歉🙏 马上为您无条件退款，1-3个工作日到账。已备注避免此类问题再发生！"},
    ],
    "complaint": [
        {"user": "你们服务态度太差了", "assistant": "亲，非常抱歉给您带来不好体验🙏 我们很重视您的反馈！请问具体遇到什么问题？我来解决，同时向上级反馈改进~"},
        {"user": "送了2小时了太慢了", "assistant": "亲，让您久等了非常抱歉🙏 已紧急联系骑手并备注加急！为表歉意给您申请一张优惠券，后续有问题随时找我~"},
    ],
    "medical_advice": [
        {"user": "血压150需要吃什么药", "assistant": "亲，血压用药问题建议咨询医生🙏 我们可以为您提供精准的血压计，方便日常监测血压变化。需要推荐家用血压计吗？"},
        {"user": "宝宝发烧38.5怎么办", "assistant": "亲，宝宝发烧家长着急我理解😰 建议先物理降温并及时就医🙏 我们有儿童额温枪可以随时监测体温，30分钟内送达~"},
    ],
    "greeting": [
        {"user": "你好", "assistant": "亲，您好😊 欢迎光临！请问有什么可以帮您的？"},
    ],
    "other": [
        {"user": "谢谢", "assistant": "亲，不客气😊 有任何问题随时找我，祝您生活愉快~"},
    ],
}


def build_optimized_system_prompt(
    knowledge_base: list[dict] | None = None,
    after_sales_scripts: dict | None = None,
    customer_profile_str: str | None = None,
    dynamic_few_shots: dict | None = None,
) -> str:
    """构建优化版系统提示词 - 精简核心 + 按需注入"""
    parts = [CORE_SYSTEM_PROMPT]

    # 客户画像（如有）
    if customer_profile_str:
        parts.append(f"\n# 当前客户\n{customer_profile_str}")

    # 知识库精简版（最多 10 条最相关的）
    if knowledge_base:
        kb_lines = []
        for item in knowledge_base[:10]:
            q = item.get("question", "")
            a = item.get("answer", "")
            if q and a:
                kb_lines.append(f"Q: {q} → {a}")
        if kb_lines:
            parts.append("\n# 知识库参考\n" + "\n".join(kb_lines))

    return "\n".join(parts)


def build_optimized_few_shot(
    user_message: str,
    sk: dict | None = None,
    dynamic_few_shots: dict | None = None,
    intent: str = "other",
) -> str:
    """优化版 few-shot 选择 - 按意图精选最多 2 条示例

    Args:
        user_message: 用户消息（用于兜底匹配）
        sk: 结构化知识（兼容旧接口，可忽略）
        dynamic_few_shots: 动态 few-shot 示例（从反馈学习得到，优先级高于硬编码）
        intent: 当前意图（用于精确选择示例）

    Returns:
        格式化的 few-shot 示例字符串
    """
    # 1. 动态示例优先
    if dynamic_few_shots and intent in dynamic_few_shots:
        dynamic_examples = dynamic_few_shots[intent]
        if isinstance(dynamic_examples, list) and dynamic_examples:
            selected = dynamic_examples[:2]
            lines = []
            for ex in selected:
                if isinstance(ex, dict) and "user" in ex and "assistant" in ex:
                    lines.append(f"用户：{ex['user']}\n客服：{ex['assistant']}")
            if lines:
                return "\n\n".join(lines)

    # 2. 按 intent 选择硬编码示例（最多 2 条）
    intent_examples = INTENT_FEW_SHOTS.get(intent, [])
    if intent_examples:
        selected = intent_examples[:2]
    else:
        # 兜底：product_inquiry 的第一条
        selected = INTENT_FEW_SHOTS.get("product_inquiry", [])[:1]

    lines = []
    for ex in selected:
        lines.append(f"用户：{ex['user']}\n客服：{ex['assistant']}")

    return "\n\n".join(lines) if lines else ""


def build_optimized_user_message_with_context(
    user_message: str,
    conversation_history: list[dict] | None = None,
    product_results: list[dict] | None = None,
    conversation_context: str | None = None,
    business_context: dict | None = None,
    dynamic_few_shots: dict | None = None,
    intent: str = "other",
) -> str:
    """构建优化版用户消息（包含上下文）

    注意：business_context 不再注入（面向买家，不应暴露经营数据）。
    """
    parts = []

    # 对话历史
    if conversation_history:
        recent = conversation_history[-6:]  # 最多3轮对话
        if recent:
            history_lines = []
            for msg in recent:
                role = "用户" if msg.get("role") == "user" else "客服"
                history_lines.append(f"{role}：{msg.get('content', '')}")
            parts.append("## 对话历史\n" + "\n".join(history_lines))

    # 商品搜索结果（优化版，含 GraphRAG 子图信息）
    if product_results:
        product_lines = []
        for i, p in enumerate(product_results[:5], 1):
            name = p.get("name", "")
            price = p.get("retail_price", "")
            stock = p.get("stock", "")
            sales = p.get("monthly_sales", "")
            line = f"{i}. {name}"
            if price:
                line += f" - ¥{price}"
            if stock:
                line += f" (库存{stock})"
            if sales:
                line += f" (月销{sales})"
            # GraphRAG 子图字段
            suitable_for = p.get("suitable_for", [])
            if suitable_for:
                suitable_str = "、".join(str(s) for s in suitable_for[:4])
                line += f"\n   适用人群: {suitable_str}"
            contraindicated = p.get("contraindicated_for", [])
            if contraindicated:
                contra_names = []
                for c in contraindicated[:2]:
                    if isinstance(c, dict):
                        n = c.get("name", "")
                        r = c.get("reason", "")
                        contra_names.append(f"{n}({r})" if r else n)
                    else:
                        contra_names.append(str(c))
                line += f"\n   禁忌人群: {'、'.join(contra_names)}"
            related = p.get("related_products", [])
            if related:
                rel_names = [
                    r.get("name", str(r)) if isinstance(r, dict) else str(r)
                    for r in related[:2]
                ]
                line += f"\n   关联推荐: {'、'.join(rel_names)}"
            product_lines.append(line)
        parts.append("## 店内相关商品\n" + "\n".join(product_lines))

    # 对话状态上下文
    if conversation_context:
        parts.append(f"## 对话状态\n{conversation_context}")

    # 优化版 few-shot（按意图精选最多 2 条）
    few_shot = build_optimized_few_shot(
        user_message, dynamic_few_shots=dynamic_few_shots, intent=intent,
    )
    if few_shot:
        parts.append(f"## 参考示例\n{few_shot}")

    # 用户问题
    parts.append(f"## 用户问题\n{user_message}")

    return "\n\n".join(parts)
