#!/usr/bin/env python3
"""
深度分析客服对话数据脚本
分析39个对话，566条消息，提取优化点
"""

import json
from collections import Counter, defaultdict


def analyze_conversations(data_file):
    """深度分析客服对话"""
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    conversations = data["conversations"]

    # ═══ 1. 基础统计 ═══
    print("=" * 60)
    print("📊 对话数据深度分析")
    print("=" * 60)
    print(f"总对话数: {len(conversations)}")
    print(f"总消息数: {sum(len(conv['messages']) for conv in conversations)}")

    # ═══ 2. 问题类型深度分析 ═══
    intent_analysis = analyze_intents(conversations)

    # ═══ 3. 客服回复质量分析 ═══
    reply_quality_analysis = {}  # 将在其他分析中包含

    # ═══ 4. 高频问题与标准答案 ═══
    frequent_patterns = analyze_frequent_patterns(conversations)

    # ═══ 5. 优秀与差的回复示例 ═══
    reply_examples = analyze_reply_examples(conversations)

    # ═══ 6. 知识库缺口分析 ═══
    knowledge_gaps = analyze_knowledge_gaps(conversations)

    # ═══ 7. 客户情绪分析 ═══
    emotion_analysis = analyze_customer_emotion(conversations)

    return {
        "intent_analysis": intent_analysis,
        "reply_quality": reply_quality_analysis,
        "frequent_patterns": frequent_patterns,
        "reply_examples": reply_examples,
        "knowledge_gaps": knowledge_gaps,
        "emotion_analysis": emotion_analysis,
    }


def analyze_intents(conversations):
    """分析对话意图分布"""
    intent_data = []

    for conv in conversations:
        # 分析第一个客户消息判断意图
        customer_msgs = [msg for msg in conv["messages"] if msg["role"] == "customer"]
        if not customer_msgs:
            continue

        first_msg = customer_msgs[0]["content"]
        intent = classify_intent(first_msg)

        # 分析解决率
        resolved = is_conversation_resolved(conv["messages"])

        # 计算客服回复质量
        agent_replies = [msg for msg in conv["messages"] if msg["role"] == "agent"]
        avg_reply_quality = calculate_reply_quality_score(agent_replies, customer_msgs)

        intent_data.append(
            {
                "intent": intent,
                "resolved": resolved,
                "reply_quality": avg_reply_quality,
                "message_count": len(conv["messages"]),
                "session": conv.get("session_name", ""),
            }
        )

    # 统计分析
    intent_stats = defaultdict(list)
    for item in intent_data:
        intent_stats[item["intent"]].append(item)

    result = {}
    for intent, items in intent_stats.items():
        result[intent] = {
            "count": len(items),
            "percentage": len(items) / len(intent_data) * 100,
            "avg_quality": sum(item["reply_quality"] for item in items) / len(items),
            "resolution_rate": sum(1 for item in items if item["resolved"]) / len(items) * 100,
            "avg_msg_count": sum(item["message_count"] for item in items) / len(items),
        }

    return result


def classify_intent(message):
    """基于消息内容分类意图"""
    message = message.lower()

    # 产品咨询关键词
    if any(kw in message for kw in ["买", "推荐", "哪个好", "有没有", "多少钱", "选择", "怎么买"]):
        return "product_inquiry"

    # 使用咨询
    if any(kw in message for kw in ["怎么用", "怎么测", "用法", "操作", "说明书", "使用方法"]):
        return "usage_question"

    # 售后服务
    if any(
        kw in message for kw in ["退", "换", "坏", "质量", "差", "问题", "不好", "损坏", "修理"]
    ):
        return "after_sales"

    # 物流配送
    if any(
        kw in message for kw in ["送", "到", "配送", "多久", "发货", "快递", "收货", "等", "时间"]
    ):
        return "logistics"

    # 开发票
    if any(kw in message for kw in ["发票", "开票", "票据", "报销"]):
        return "invoice"

    # 隐私订单
    if any(kw in message for kw in ["隐私", "保密", "悄悄", "秘密配送", "不要让人看到"]):
        return "privacy"

    # 投诉
    if any(kw in message for kw in ["投诉", "举报", "315", "消协", "差评", "欺骗", "骗子"]):
        return "complaint"

    # 医疗咨询
    if any(kw in message for kw in ["血压", "血糖", "病", "症状", "治疗", "医生", "药", "健康"]):
        return "medical_consultation"

    # 问候
    if any(kw in message for kw in ["你好", "在吗", "您好", "hello", "hi"]):
        return "greeting"

    return "other"


def is_conversation_resolved(messages):
    """判断对话是否得到解决"""
    customer_msgs = [msg for msg in messages if msg["role"] == "customer"]
    agent_msgs = [msg for msg in messages if msg["role"] == "agent"]

    if not customer_msgs or not agent_msgs:
        return False

    last_customer_msg = customer_msgs[-1]["content"].lower()

    # 客户表示满意的标志
    satisfied_keywords = ["谢谢", "好的", "收到", "明白", "清楚", "可以", "行", "👌", "😊"]
    if any(kw in last_customer_msg for kw in satisfied_keywords):
        return True

    # 客服给出了明确解决方案
    if len(agent_msgs) > 0:
        last_agent_msg = agent_msgs[-1]["content"].lower()
        solution_keywords = ["帮您处理", "已为您", "已经", "马上", "立即", "现在就", "退款", "换货"]
        if any(kw in last_agent_msg for kw in solution_keywords):
            return True

    return False


def calculate_reply_quality_score(agent_replies, customer_msgs):
    """计算客服回复质量评分"""
    if not agent_replies:
        return 0.0

    total_score = 0
    for reply in agent_replies:
        content = reply["content"]
        score = 0.5  # 基础分

        # 负分项
        if any(word in content for word in ["稍等", "好的", "嗯", "哦"]):
            score -= 0.2
        if len(content) < 10:  # 太短
            score -= 0.3
        if "自动回复" in content or "后台电话" in content:
            score -= 0.4

        # 加分项
        if len(content) > 30:  # 有内容
            score += 0.2
        if any(word in content for word in ["为您", "帮您", "建议", "推荐"]):
            score += 0.2
        if any(word in content for word in ["专业", "正品", "品质", "效果"]):
            score += 0.1
        if "😊" in content or "🙏" in content or "👌" in content:
            score += 0.1

        total_score += max(0, min(1, score))  # 限制在0-1之间

    return total_score / len(agent_replies)


def analyze_frequent_patterns(conversations):
    """分析高频问题模式"""
    customer_questions = []

    for conv in conversations:
        for msg in conv["messages"]:
            if msg["role"] == "customer":
                content = msg["content"]
                # 清理消息，提取问题
                if "?" in content or "吗" in content or "多少" in content:
                    customer_questions.append(content)

    # 统计高频问题
    question_counter = Counter(customer_questions)

    # 按相似性归类
    question_patterns = group_similar_questions(customer_questions)

    return {
        "top_questions": question_counter.most_common(20),
        "question_patterns": question_patterns,
    }


def group_similar_questions(questions):
    """将相似问题归类"""
    patterns = defaultdict(list)

    for q in questions:
        # 提取关键特征
        if "一盒" in q and ("人" in q or "用" in q):
            patterns["产品用量询问"].append(q)
        elif "多久" in q and ("到" in q or "送" in q):
            patterns["配送时间"].append(q)
        elif "正品" in q:
            patterns["正品保证"].append(q)
        elif "保密" in q or "隐私" in q:
            patterns["隐私配送"].append(q)
        elif "开" in q and "票" in q:
            patterns["开发票"].append(q)
        elif "岁" in q and ("可以" in q or "能" in q):
            patterns["年龄适用性"].append(q)
        elif "医疗级" in q:
            patterns["医疗级别"].append(q)
        else:
            patterns["其他"].append(q)

    return dict(patterns)


def analyze_reply_examples(conversations):
    """分析优秀和差的回复示例"""
    good_replies = []
    poor_replies = []

    for conv in conversations:
        agent_msgs = [msg for msg in conv["messages"] if msg["role"] == "agent"]

        for agent_msg in agent_msgs:
            # 找到对应的客户消息
            customer_msg = ""
            for j, msg in enumerate(conv["messages"]):
                if msg == agent_msg and j > 0:
                    prev_msg = conv["messages"][j - 1]
                    if prev_msg["role"] == "customer":
                        customer_msg = prev_msg["content"]
                    break

            content = agent_msg["content"]

            # 优秀回复标准
            if (
                len(content) > 20
                and any(word in content for word in ["为您", "帮您", "建议", "推荐"])
                and not any(word in content for word in ["稍等", "好的", "嗯"])
                and ("😊" in content or "🙏" in content)
            ):
                good_replies.append(
                    {"customer": customer_msg, "agent": content, "reason": "有实质内容且语气亲切"}
                )

            # 差的回复标准
            if (
                len(content) < 15
                or content in ["稍等", "好的", "嗯", "哦"]
                or "后台电话" in content
            ):
                poor_replies.append(
                    {"customer": customer_msg, "agent": content, "reason": "内容过短或无实质帮助"}
                )

    return {
        "good_examples": good_replies[:10],  # 取前10个最好的
        "poor_examples": poor_replies[:10],  # 取前10个最差的
    }


def analyze_knowledge_gaps(conversations):
    """分析知识库缺口"""
    gaps = {"missing_faqs": [], "product_info_gaps": [], "process_gaps": [], "script_gaps": []}

    for conv in conversations:
        customer_msgs = [msg for msg in conv["messages"] if msg["role"] == "customer"]
        agent_msgs = [msg for msg in conv["messages"] if msg["role"] == "agent"]

        for customer_msg in customer_msgs:
            content = customer_msg["content"]

            # 检查是否有对应的满意回复
            has_good_reply = False
            for agent_msg in agent_msgs:
                if len(agent_msg["content"]) > 30:
                    has_good_reply = True
                    break

            if not has_good_reply:
                # 分类缺失的知识
                if "一盒" in content and "人" in content:
                    gaps["missing_faqs"].append(content + " -> 需要产品用量说明")
                elif "保密" in content or "隐私" in content:
                    gaps["process_gaps"].append(content + " -> 需要隐私配送流程")
                elif "开" in content and "票" in content:
                    gaps["process_gaps"].append(content + " -> 需要开票流程说明")
                elif "催" in content and ("外卖" in content or "送" in content):
                    gaps["script_gaps"].append(content + " -> 需要配送催单话术")
                elif "医疗级" in content:
                    gaps["product_info_gaps"].append(content + " -> 需要医疗级别说明")

    return gaps


def analyze_customer_emotion(conversations):
    """分析客户情绪"""
    emotions = {"positive": 0, "neutral": 0, "negative": 0}

    emotion_examples = {"positive": [], "negative": []}

    for conv in conversations:
        for msg in conv["messages"]:
            if msg["role"] == "customer":
                content = msg["content"]

                # 积极情绪
                if any(word in content for word in ["谢谢", "好", "满意", "👌", "😊", "不错"]):
                    emotions["positive"] += 1
                    if len(emotion_examples["positive"]) < 5:
                        emotion_examples["positive"].append(content)

                # 消极情绪
                elif any(
                    word in content for word in ["差", "坏", "不好", "怎么", "气", "烦", "投诉"]
                ):
                    emotions["negative"] += 1
                    if len(emotion_examples["negative"]) < 5:
                        emotion_examples["negative"].append(content)
                else:
                    emotions["neutral"] += 1

    return {"distribution": emotions, "examples": emotion_examples}


def main():
    data_file = "../data/im_conversations_full.json"
    results = analyze_conversations(data_file)

    # 输出详细分析报告
    print("\n" + "=" * 60)
    print("📋 深度分析结果")
    print("=" * 60)

    print("\n🎯 意图分析:")
    for intent, stats in results["intent_analysis"].items():
        print(
            f"  {intent}: {stats['count']}次 ({stats['percentage']:.1f}%) "
            f"质量:{stats['avg_quality']:.2f} 解决率:{stats['resolution_rate']:.1f}%"
        )

    print("\n📝 高频问题模式:")
    for pattern, questions in results["frequent_patterns"]["question_patterns"].items():
        if len(questions) > 0:
            print(f"  {pattern}: {len(questions)}次")
            if questions:
                print(f"    示例: {questions[0]}")

    print("\n✅ 优秀回复示例:")
    for example in results["reply_examples"]["good_examples"][:3]:
        print(f"  客户: {example['customer'][:50]}...")
        print(f"  客服: {example['agent'][:50]}...")
        print()

    print("\n❌ 差劲回复示例:")
    for example in results["reply_examples"]["poor_examples"][:3]:
        print(f"  客户: {example['customer'][:50]}...")
        print(f"  客服: {example['agent']}")
        print()

    print("\n🔍 知识库缺口:")
    for gap_type, gaps in results["knowledge_gaps"].items():
        if gaps:
            print(f"  {gap_type}: {len(gaps)}项")
            for gap in gaps[:3]:
                print(f"    - {gap}")

    print("\n😊 客户情绪分布:")
    emotions = results["emotion_analysis"]["distribution"]
    total = sum(emotions.values())
    for emotion, count in emotions.items():
        print(f"  {emotion}: {count} ({count / total * 100:.1f}%)")

    # 保存结果到文件
    with open("../data/deep_analysis_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n💾 详细分析结果已保存到: ../data/deep_analysis_results.json")


if __name__ == "__main__":
    main()
