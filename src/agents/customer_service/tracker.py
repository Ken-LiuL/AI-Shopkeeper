"""
多轮意图追踪系统
实现对话状态机，追踪用户意图变化和售后流程
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    """对话状态枚举"""

    GREETING = "greeting"  # 初始问候
    INQUIRY = "inquiry"  # 咨询中（商品/用法/比较）
    AFTER_SALES = "after_sales"  # 售后流程（退货/换货/退款）
    COMPLAINT = "complaint"  # 投诉升级
    RESOLVED = "resolved"  # 已解决


class AfterSalesStep(Enum):
    """售后流程步骤"""

    PROBLEM_DESCRIPTION = "problem_description"  # 问题描述
    SOLUTION_PROPOSED = "solution_proposed"  # 方案提出
    USER_CONFIRMATION = "user_confirmation"  # 用户确认
    EXECUTION = "execution"  # 执行处理


class ConversationTracker:
    """对话追踪器"""

    def __init__(self):
        self.state_transitions = self._build_state_machine()
        self.after_sales_keywords = [
            "退货",
            "退款",
            "换货",
            "质量问题",
            "损坏",
            "不好用",
            "退掉",
            "申请退",
            "要退",
            "坏了",
            "有问题",
            "不满意",
            "投诉",
        ]
        self.greeting_keywords = ["你好", "您好", "hi", "hello", "在吗", "咨询", "问一下"]
        self.inquiry_keywords = [
            "价格",
            "多少钱",
            "怎么用",
            "效果",
            "推荐",
            "哪个好",
            "有什么",
            "功能",
            "区别",
            "对比",
            "适合",
        ]
        self.complaint_keywords = [
            "投诉",
            "态度不好",
            "服务差",
            "要举报",
            "找你们领导",
            "太差了",
            "非常不满意",
            "要曝光",
        ]

    def _build_state_machine(self) -> dict[ConversationState, list[ConversationState]]:
        """构建状态转换规则"""
        return {
            ConversationState.GREETING: [
                ConversationState.INQUIRY,
                ConversationState.AFTER_SALES,
                ConversationState.COMPLAINT,
            ],
            ConversationState.INQUIRY: [
                ConversationState.AFTER_SALES,
                ConversationState.COMPLAINT,
                ConversationState.RESOLVED,
                ConversationState.INQUIRY,  # 继续咨询
            ],
            ConversationState.AFTER_SALES: [
                ConversationState.COMPLAINT,
                ConversationState.RESOLVED,
                ConversationState.AFTER_SALES,  # 售后流程内部转换
            ],
            ConversationState.COMPLAINT: [
                ConversationState.RESOLVED,
                ConversationState.COMPLAINT,  # 继续投诉
            ],
            ConversationState.RESOLVED: [
                ConversationState.INQUIRY,  # 新的咨询
                ConversationState.GREETING,  # 重新开始
            ],
        }

    def infer_state_from_history(self, conversation_history: list[dict]) -> ConversationState:
        """从对话历史推断当前状态"""
        if not conversation_history:
            return ConversationState.GREETING

        # 获取最近3轮对话
        recent_messages = conversation_history[-6:]  # 3轮用户+AI消息
        user_messages = [
            msg.get("content", "") for msg in recent_messages if msg.get("role") == "user"
        ]
        ai_messages = [
            msg.get("content", "") for msg in recent_messages if msg.get("role") == "assistant"
        ]

        if not user_messages:
            return ConversationState.GREETING

        # 分析最近的用户消息
        recent_user_text = " ".join(user_messages[-2:]).lower()
        recent_ai_text = " ".join(ai_messages[-2:]).lower()

        # 优先级：投诉 > 售后 > 咨询 > 问候

        # 检查投诉关键词
        if any(keyword in recent_user_text for keyword in self.complaint_keywords):
            return ConversationState.COMPLAINT

        # 检查售后关键词
        if any(keyword in recent_user_text for keyword in self.after_sales_keywords):
            return ConversationState.AFTER_SALES

        # 检查是否已解决（AI回复包含解决性语言且用户表示满意）
        resolved_patterns = ["已为您处理", "问题解决了", "满意", "谢谢", "好的", "明白了"]
        if any(pattern in recent_ai_text for pattern in ["已为您", "为您处理", "已解决"]) and any(
            pattern in recent_user_text for pattern in resolved_patterns[-4:]
        ):
            return ConversationState.RESOLVED

        # 检查咨询关键词
        if any(keyword in recent_user_text for keyword in self.inquiry_keywords):
            return ConversationState.INQUIRY

        # 检查问候关键词
        if any(keyword in recent_user_text for keyword in self.greeting_keywords):
            return ConversationState.GREETING

        # 默认情况：如果对话较短，认为是问候；否则是咨询
        if len(conversation_history) <= 2:
            return ConversationState.GREETING
        else:
            return ConversationState.INQUIRY

    def update_state(
        self, current_state: ConversationState, intent: str, message: str
    ) -> ConversationState:
        """根据用户意图和消息更新状态"""
        message_lower = message.lower()

        # 强制状态转换检查
        if any(keyword in message_lower for keyword in self.complaint_keywords):
            return ConversationState.COMPLAINT

        if any(keyword in message_lower for keyword in self.after_sales_keywords):
            return ConversationState.AFTER_SALES

        # 基于意图的状态转换
        intent_state_mapping = {
            "after_sales": ConversationState.AFTER_SALES,
            "complaint": ConversationState.COMPLAINT,
            "product_inquiry": ConversationState.INQUIRY,
            "usage_question": ConversationState.INQUIRY,
            "recommendation": ConversationState.INQUIRY,
            "comparison": ConversationState.INQUIRY,
            "greeting": ConversationState.GREETING,
        }

        if intent in intent_state_mapping:
            new_state = intent_state_mapping[intent]
            # 检查状态转换是否合法
            if new_state in self.state_transitions.get(current_state, []):
                return new_state

        # 保持当前状态
        return current_state

    def track_after_sales_flow(
        self, conversation_history: list[dict]
    ) -> tuple[AfterSalesStep, dict]:
        """追踪售后流程的具体步骤"""
        if not conversation_history:
            return AfterSalesStep.PROBLEM_DESCRIPTION, {}

        # 分析对话内容
        user_messages = [
            msg.get("content", "") for msg in conversation_history if msg.get("role") == "user"
        ]
        ai_messages = [
            msg.get("content", "") for msg in conversation_history if msg.get("role") == "assistant"
        ]

        flow_data = {
            "problem_described": False,
            "solution_offered": False,
            "user_accepted": False,
            "execution_started": False,
        }

        # 检查问题描述
        problem_keywords = ["坏了", "损坏", "不好用", "质量问题", "有问题"]
        if any(
            any(keyword in msg.lower() for keyword in problem_keywords) for msg in user_messages
        ):
            flow_data["problem_described"] = True

        # 检查方案提出
        solution_keywords = ["为您", "可以", "建议", "退货", "换货", "退款", "处理"]
        if any(any(keyword in msg for keyword in solution_keywords) for msg in ai_messages):
            flow_data["solution_offered"] = True

        # 检查用户确认
        acceptance_keywords = ["好的", "可以", "同意", "行", "要", "申请"]
        rejection_keywords = ["不", "不要", "不行", "不可以"]
        recent_user_msgs = user_messages[-2:]

        if any(any(keyword in msg for keyword in acceptance_keywords) for msg in recent_user_msgs):
            if not any(
                any(keyword in msg for keyword in rejection_keywords) for msg in recent_user_msgs
            ):
                flow_data["user_accepted"] = True

        # 检查执行开始
        execution_keywords = ["已为您", "正在处理", "申请成功", "订单号"]
        if any(any(keyword in msg for keyword in execution_keywords) for msg in ai_messages):
            flow_data["execution_started"] = True

        # 确定当前步骤
        if flow_data["execution_started"]:
            return AfterSalesStep.EXECUTION, flow_data
        elif flow_data["user_accepted"]:
            return AfterSalesStep.USER_CONFIRMATION, flow_data
        elif flow_data["solution_offered"]:
            return AfterSalesStep.SOLUTION_PROPOSED, flow_data
        else:
            return AfterSalesStep.PROBLEM_DESCRIPTION, flow_data

    def get_context_summary(
        self, state: ConversationState, conversation_history: list[dict]
    ) -> str:
        """生成给LLM的上下文摘要"""
        if not conversation_history:
            return self._get_state_context(state)

        # 基础状态上下文
        context = self._get_state_context(state)

        # 添加特定状态的上下文信息
        if state == ConversationState.AFTER_SALES:
            step, flow_data = self.track_after_sales_flow(conversation_history)
            context += self._get_after_sales_context(step, flow_data)

        elif state == ConversationState.INQUIRY:
            context += self._get_inquiry_context(conversation_history)

        elif state == ConversationState.COMPLAINT:
            context += self._get_complaint_context(conversation_history)

        return context

    def _get_state_context(self, state: ConversationState) -> str:
        """获取状态基础上下文"""
        context_map = {
            ConversationState.GREETING: "用户刚开始对话，需要友好问候并了解需求。",
            ConversationState.INQUIRY: "用户正在咨询商品相关问题，需要提供专业准确的信息。",
            ConversationState.AFTER_SALES: "用户遇到售后问题，需要耐心了解情况并提供解决方案。",
            ConversationState.COMPLAINT: "用户在投诉，需要认真对待，安抚情绪，快速解决。",
            ConversationState.RESOLVED: "问题已解决，用户满意，可以询问是否还有其他需求。",
        }

        return context_map.get(state, "")

    def _get_after_sales_context(self, step: AfterSalesStep, flow_data: dict) -> str:
        """获取售后流程上下文"""
        context = "\n售后流程追踪："

        if step == AfterSalesStep.PROBLEM_DESCRIPTION:
            if not flow_data.get("problem_described"):
                context += " 需要了解具体问题：商品哪里有问题？什么时候发现的？"
            else:
                context += " 用户已描述问题，需要判断问题严重程度并提出解决方案。"

        elif step == AfterSalesStep.SOLUTION_PROPOSED:
            context += " 已提出解决方案，需要等待用户确认是否接受。"

        elif step == AfterSalesStep.USER_CONFIRMATION:
            if flow_data.get("user_accepted"):
                context += " 用户已接受方案，需要开始执行处理流程。"
            else:
                context += " 用户可能不接受当前方案，需要提供其他选择。"

        elif step == AfterSalesStep.EXECUTION:
            context += " 正在执行处理流程，需要告知用户进展或完成情况。"

        return context

    def _get_inquiry_context(self, conversation_history: list[dict]) -> str:
        """获取咨询上下文"""
        # 分析用户咨询的主要方向
        user_messages = [
            msg.get("content", "") for msg in conversation_history if msg.get("role") == "user"
        ]
        all_user_text = " ".join(user_messages).lower()

        context = "\n咨询追踪："

        if any(keyword in all_user_text for keyword in ["价格", "多少钱", "费用"]):
            context += " 用户关注价格信息。"

        if any(keyword in all_user_text for keyword in ["怎么用", "用法", "使用方法"]):
            context += " 用户需要使用指导。"

        if any(keyword in all_user_text for keyword in ["推荐", "哪个好", "选择"]):
            context += " 用户需要商品推荐建议。"

        if any(keyword in all_user_text for keyword in ["区别", "对比", "比较"]):
            context += " 用户在比较不同商品。"

        return context

    def _get_complaint_context(self, conversation_history: list[dict]) -> str:
        """获取投诉上下文"""
        return "\n投诉处理：用户情绪可能激动，需要首先安抚，认真倾听，快速给出解决方案，必要时升级到人工客服。"


# 全局追踪器实例
_tracker_instance: ConversationTracker | None = None


def get_conversation_tracker() -> ConversationTracker:
    """获取对话追踪器实例"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = ConversationTracker()
    return _tracker_instance


def track_conversation(
    conversation_history: list[dict], user_intent: str = "", user_message: str = ""
) -> dict:
    """
    追踪对话状态并返回上下文信息

    Args:
        conversation_history: 对话历史
        user_intent: 用户意图
        user_message: 用户消息

    Returns:
        包含状态和上下文摘要的字典
    """
    tracker = get_conversation_tracker()

    # 从历史推断当前状态
    current_state = tracker.infer_state_from_history(conversation_history)

    # 如果有新的意图和消息，更新状态
    if user_intent and user_message:
        current_state = tracker.update_state(current_state, user_intent, user_message)

    # 生成上下文摘要
    context_summary = tracker.get_context_summary(current_state, conversation_history)

    # 特殊处理售后流程
    after_sales_info = {}
    if current_state == ConversationState.AFTER_SALES:
        step, flow_data = tracker.track_after_sales_flow(conversation_history)
        after_sales_info = {"step": step.value, "flow_data": flow_data}

    return {
        "state": current_state.value,
        "context_summary": context_summary,
        "after_sales_info": after_sales_info,
    }
