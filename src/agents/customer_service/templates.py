"""
客服话术库 (P3-1)

这些话术模板不直接返回给用户，而是作为 LLM 的参考素材注入 system prompt。
LLM 会参考这些标准话术，但仍自由组织语言，保证回复质量和自然度。
"""

from __future__ import annotations

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 话术模板库
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEMPLATES: dict[str, str] = {
    # 欢迎语
    "welcome": (
        "欢迎光临！我是AI客服小康，专注医疗器械为您服务。"
        "如需了解商品、查询订单或处理售后，随时告诉我！"
    ),

    # 营业时间
    "business_hours": (
        "我们提供7×24小时在线客服，全年无休为您服务。"
        "美团即时配送，下单后通常30-60分钟内送达。"
    ),

    # 退换货政策
    "return_policy": (
        "退换政策：\n"
        "• 收到商品7天内可申请无理由退换（商品需完好未拆封）\n"
        "• 质量/损坏问题15天内可退换货，运费由商家承担\n"
        "• 非质量问题退货运费由买家承担\n"
        "• 退款到账1-3个工作日（微信/支付宝立即到账）\n"
        "• 特殊商品（试纸/耗材已拆封）原则上不退，质量问题除外"
    ),

    # 发货时效
    "delivery_time": (
        "配送说明：\n"
        "• 美团即时配送，通常30-60分钟送达\n"
        "• 高峰期（午餐/晚餐时段）或恶劣天气可能延迟至90分钟\n"
        "• 下单后可在美团App实时追踪骑手位置\n"
        "• 如超时未收到，请联系客服处理"
    ),

    # 售后流程
    "after_sales_process": (
        "售后流程：\n"
        "1. 联系客服，说明问题并提供订单号\n"
        "2. 拍摄商品照片（损坏/质量问题需上传）\n"
        "3. 客服核实后24小时内给出处理方案\n"
        "4. 确认方案后：退款1-3工作日到账，换货安排重新配送\n"
        "5. 如对处理结果有异议，可申请平台介入"
    ),

    # 商品咨询通用话术
    "product_inquiry_tips": (
        "商品咨询要点：\n"
        "• 主动询问使用人群（老人/成人/儿童）和使用场景\n"
        "• 说明商品核心参数和优势\n"
        "• 如有多款可选，客观对比推荐1-2款\n"
        "• 提醒注意事项（如精准型血压计需在安静环境使用）"
    ),

    # 医疗建议引导话术
    "medical_guidance": (
        "健康问题引导：\n"
        "• 不提供医疗诊断或用药建议\n"
        "• 症状持续或加重建议及时就医\n"
        "• 可推荐适合的监测器械（如血压计、血糖仪、血氧仪）\n"
        "• 强调器械用于监测，不能替代专业医疗"
    ),

    # 物流查询话术
    "logistics_inquiry": (
        "物流问题处理：\n"
        "• 核实订单号和下单时间\n"
        "• 预计30-60分钟送达，告知当前骑手状态\n"
        "• 超时30分钟主动致歉并提供补偿（优惠券/退配送费）\n"
        "• 骑手无法联系或商品遗失：立即重新配送或全额退款"
    ),

    # 投诉处理话术
    "complaint_handling": (
        "投诉处理原则：\n"
        "• 先真诚道歉，表达理解用户感受\n"
        "• 快速核实问题，给出具体解决方案\n"
        "• 主动提供补偿（优惠券/退款/加急处理）\n"
        "• 升级词（315/律师/消协）→ 立即转人工，不要单独处理\n"
        "• 保持冷静专业，避免与用户争执"
    ),
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 意图 → 相关话术映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INTENT_TEMPLATES: dict[str, list[str]] = {
    "greeting": ["welcome", "business_hours"],
    "product_inquiry": ["product_inquiry_tips"],
    "recommendation": ["product_inquiry_tips"],
    "usage_question": ["product_inquiry_tips"],
    "logistics": ["delivery_time", "logistics_inquiry"],
    "after_sales": ["return_policy", "after_sales_process"],
    "complaint": ["complaint_handling", "return_policy"],
    "medical_advice": ["medical_guidance"],
    "comparison": ["product_inquiry_tips"],
    "other": [],
}


def get_templates_for_intent(intent: str) -> str:
    """
    根据意图返回相关话术模板内容，作为 LLM 的参考素材。

    返回空字符串时表示该意图无需话术注入。
    注意：这些模板是 LLM 的参考，不是直接回复给用户的内容。
    """
    template_keys = INTENT_TEMPLATES.get(intent, [])
    if not template_keys:
        return ""

    sections: list[str] = []
    for key in template_keys:
        content = TEMPLATES.get(key, "")
        if content:
            sections.append(content)

    if not sections:
        return ""

    return "【话术参考素材（LLM请参考但自由组织语言）】\n" + "\n\n".join(sections)


__all__ = ["TEMPLATES", "INTENT_TEMPLATES", "get_templates_for_intent"]
