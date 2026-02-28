#!/usr/bin/env python3
"""
美团 IM 客服聊天记录分析脚本
提取 few-shot 示例并补全知识库
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime


class IMConversationAnalyzer:
    def __init__(self, data_file: str, knowledge_file: str):
        self.data_file = data_file
        self.knowledge_file = knowledge_file
        self.conversations = []
        self.knowledge_base = {}
        self.intent_stats = defaultdict(list)
        self.quality_examples = defaultdict(list)
        self.high_freq_questions = Counter()
        self.coverage_gaps = []

    def load_data(self):
        """加载对话数据和知识库"""
        data_path = os.path.expanduser(self.data_file)
        knowledge_path = os.path.expanduser(self.knowledge_file)

        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
            self.conversations = data.get("conversations", [])

        with open(knowledge_path, encoding="utf-8") as f:
            self.knowledge_base = json.load(f)

    def filter_valid_messages(self, messages: list[dict]) -> list[dict]:
        """过滤有效消息，排除系统消息和自动回复"""
        auto_reply_keywords = [
            "尊敬的顾客您好，商家如未及时回复",
            "请拨打商家后台电话",
            "可能正在忙碌",
        ]

        valid_messages = []
        for msg in messages:
            # 排除系统消息
            if msg.get("role") == "system":
                continue

            content = msg.get("content", "")

            # 排除自动回复
            if any(keyword in content for keyword in auto_reply_keywords):
                continue

            # 排除空消息或纯符号消息
            if not content or content.strip() in [
                "？",
                "?",
                "您好",
                "你好",
                "在的",
                "好的",
                "嗯嗯",
            ]:
                continue

            valid_messages.append(msg)

        return valid_messages

    def classify_intent(self, conversation: dict) -> str:
        """根据对话内容分类意图"""
        messages = conversation.get("messages", [])
        valid_messages = self.filter_valid_messages(messages)

        if not valid_messages:
            return "empty_conversation"

        # 提取所有用户和客服的消息内容
        all_content = " ".join([msg.get("content", "") for msg in valid_messages])

        # 产品咨询相关关键词
        product_keywords = [
            "哪个好",
            "推荐",
            "怎么选",
            "区别",
            "效果",
            "型号",
            "价格",
            "包含",
            "是什么意思",
            "人份",
            "测试",
            "使用",
            "适合",
            "有没有",
            "可以用",
        ]

        # 物流配送相关关键词
        logistics_keywords = [
            "多久送到",
            "配送",
            "骑手",
            "送达",
            "催一下",
            "没到",
            "等了",
            "放门口",
            "不用敲门",
            "直接放",
            "尽快",
            "急需",
        ]

        # 售后服务相关关键词
        after_sales_keywords = [
            "退",
            "换",
            "发错",
            "裂开",
            "质量",
            "不一样",
            "误导",
            "投诉",
            "申请",
            "重新",
            "补偿",
            "包装",
            "破损",
        ]

        # 开发票相关关键词
        invoice_keywords = ["开发票", "发票", "开票", "开票信息", "邮箱"]

        # 使用咨询相关关键词
        usage_keywords = [
            "怎么用",
            "使用方法",
            "注意事项",
            "副作用",
            "能治",
            "有效吗",
            "小朋友可以",
            "孕妇",
            "儿童",
            "多久换",
            "保存",
        ]

        # 隐私订单处理
        privacy_keywords = ["隐私订单", "保密配送", "不显示"]

        # 按优先级判断意图
        if any(keyword in all_content for keyword in privacy_keywords):
            return "privacy_order"
        elif any(keyword in all_content for keyword in invoice_keywords):
            return "invoice_request"
        elif any(keyword in all_content for keyword in after_sales_keywords):
            return "after_sales"
        elif any(keyword in all_content for keyword in logistics_keywords):
            return "logistics"
        elif any(keyword in all_content for keyword in usage_keywords):
            return "usage_question"
        elif any(keyword in all_content for keyword in product_keywords):
            return "product_inquiry"
        else:
            return "other"

    def evaluate_response_quality(self, messages: list[dict]) -> float:
        """评估客服回复质量"""
        valid_messages = self.filter_valid_messages(messages)
        agent_messages = [msg for msg in valid_messages if msg.get("role") == "agent"]
        customer_messages = [msg for msg in valid_messages if msg.get("role") == "customer"]

        if not agent_messages or not customer_messages:
            return 0.0

        score = 0.0

        # 回复数量得分 (多轮对话更好)
        if len(agent_messages) >= 3:
            score += 0.3
        elif len(agent_messages) >= 2:
            score += 0.2
        elif len(agent_messages) == 1:
            score += 0.1

        # 回复实质性内容得分
        substantial_keywords = [
            "稍等",
            "帮您",
            "建议",
            "推荐",
            "查一下",
            "看一下",
            "了解",
            "可以",
            "不客气",
            "抱歉",
            "非常",
            "确认",
            "处理",
            "安排",
            "问一下",
        ]

        substantial_count = 0
        for msg in agent_messages:
            content = msg.get("content", "")
            if any(keyword in content for keyword in substantial_keywords):
                substantial_count += 1

        if substantial_count >= 2:
            score += 0.4
        elif substantial_count == 1:
            score += 0.2

        # 专业性得分 (包含专业建议)
        professional_keywords = [
            "上臂式",
            "腕式",
            "测量",
            "血压",
            "体温",
            "试纸",
            "浓度",
            "剂量",
            "配套",
            "型号",
            "建议您",
            "医生",
            "药师",
        ]

        professional_count = sum(
            1
            for msg in agent_messages
            for keyword in professional_keywords
            if keyword in msg.get("content", "")
        )

        if professional_count >= 2:
            score += 0.3
        elif professional_count == 1:
            score += 0.1

        return min(score, 1.0)

    def extract_qa_pairs(self, conversation: dict) -> list[dict]:
        """提取问答对"""
        messages = conversation.get("messages", [])
        valid_messages = self.filter_valid_messages(messages)

        qa_pairs = []
        i = 0

        while i < len(valid_messages):
            msg = valid_messages[i]

            # 找到用户问题
            if msg.get("role") == "customer" and len(msg.get("content", "")) > 5:
                question = msg.get("content", "")

                # 查找后续的客服回复
                for j in range(i + 1, min(i + 3, len(valid_messages))):
                    if valid_messages[j].get("role") == "agent":
                        answer = valid_messages[j].get("content", "")

                        # 过滤掉无意义回复
                        if len(answer) > 10 and answer not in ["稍等", "好的", "嗯嗯", "在的"]:
                            qa_pairs.append(
                                {
                                    "question": question,
                                    "answer": answer,
                                    "quality_score": self.evaluate_response_quality(
                                        valid_messages[i : j + 1]
                                    ),
                                }
                            )
                        break
            i += 1

        return qa_pairs

    def analyze_conversations(self):
        """分析所有对话"""
        print("开始分析对话...")

        for conversation in self.conversations:
            intent = self.classify_intent(conversation)
            quality_score = self.evaluate_response_quality(conversation.get("messages", []))

            # 统计意图分布
            self.intent_stats[intent].append(
                {
                    "session_name": conversation.get("session_name"),
                    "message_count": conversation.get("message_count"),
                    "quality_score": quality_score,
                }
            )

            # 提取QA对
            qa_pairs = self.extract_qa_pairs(conversation)
            for qa in qa_pairs:
                qa["intent"] = intent
                qa["session"] = conversation.get("session_name")

                # 收集高质量示例
                if qa["quality_score"] > 0.6:
                    self.quality_examples[intent].append(qa)

            # 统计高频问题
            messages = self.filter_valid_messages(conversation.get("messages", []))
            for msg in messages:
                if msg.get("role") == "customer":
                    content = msg.get("content", "").strip()
                    if len(content) > 5 and "？" in content or "吗" in content:
                        self.high_freq_questions[content] += 1

    def identify_knowledge_gaps(self):
        """识别知识库覆盖缺口"""
        print("分析知识库覆盖缺口...")

        # 隐私订单处理
        privacy_count = len(self.intent_stats.get("privacy_order", []))
        if privacy_count > 0:
            self.coverage_gaps.append(
                {
                    "type": "隐私订单处理",
                    "frequency": privacy_count,
                    "description": "客户询问隐私订单信息处理，但知识库缺少相关规范",
                    "suggestion": "添加隐私订单处理流程和保密配送说明",
                }
            )

        # 开发票流程
        invoice_count = len(self.intent_stats.get("invoice_request", []))
        if invoice_count > 0:
            self.coverage_gaps.append(
                {
                    "type": "开发票流程",
                    "frequency": invoice_count,
                    "description": "客户询问开发票相关事宜，知识库缺少发票政策",
                    "suggestion": "添加发票开具流程、时限、发送方式等规范",
                }
            )

        # 配送要求传达
        logistics_count = len(self.intent_stats.get("logistics", []))
        if logistics_count > 0:
            self.coverage_gaps.append(
                {
                    "type": "配送要求传达",
                    "frequency": logistics_count,
                    "description": "客户提出特殊配送要求（放门口、不敲门等）",
                    "suggestion": "添加配送要求处理规范和与骑手沟通流程",
                }
            )

    def select_best_few_shot_examples(self) -> dict:
        """选择最佳few-shot示例"""
        best_examples = {}

        for intent, examples in self.quality_examples.items():
            if not examples:
                continue

            # 按质量分数排序
            examples.sort(key=lambda x: x["quality_score"], reverse=True)

            # 每个意图选取前3个最佳示例
            best_examples[intent] = []

            seen_questions = set()
            for example in examples[:10]:  # 从前10个中筛选
                question = example["question"]

                # 避免重复或相似问题
                if any(self.text_similarity(question, seen_q) > 0.7 for seen_q in seen_questions):
                    continue

                best_examples[intent].append({"user": question, "assistant": example["answer"]})
                seen_questions.add(question)

                if len(best_examples[intent]) >= 3:
                    break

        return best_examples

    def text_similarity(self, text1: str, text2: str) -> float:
        """简单的文本相似度计算"""
        chars1 = set(text1)
        chars2 = set(text2)
        intersection = len(chars1 & chars2)
        union = len(chars1 | chars2)
        return intersection / union if union > 0 else 0

    def update_knowledge_base(self):
        """更新知识库"""
        print("更新知识库...")

        # 更新few-shot示例
        best_examples = self.select_best_few_shot_examples()

        # 更新现有的dynamic_few_shot
        if "dynamic_few_shot" not in self.knowledge_base:
            self.knowledge_base["dynamic_few_shot"] = {}

        for intent, examples in best_examples.items():
            if examples:
                self.knowledge_base["dynamic_few_shot"][intent] = examples

        # 添加缺失的知识点
        if "privacy_order_handling" not in self.knowledge_base:
            self.knowledge_base["privacy_order_handling"] = {
                "policy": "所有订单均采用保密配送",
                "process": [
                    "订单包装不显示商品信息",
                    "配送单仅显示'医疗器械'字样",
                    "如客户要求隐私配送请备注'隐私订单'",
                ],
                "response_template": "您好，我们所有订单都是保密配送的，包装不会显示具体商品信息，请放心下单~",
            }

        if "invoice_policy" not in self.knowledge_base:
            self.knowledge_base["invoice_policy"] = {
                "support_types": ["电子发票"],
                "timeline": "48小时内开具",
                "delivery_method": "邮箱发送",
                "required_info": ["发票抬头", "统一社会信用代码/身份证号", "邮箱地址"],
                "process": [
                    "客户提供开票信息",
                    "核验信息完整性",
                    "48小时内开具并发送",
                    "确认客户收到发票",
                ],
                "response_template": "好的，请提供您的发票抬头、统一社会信用代码和邮箱地址，我们会在48小时内将电子发票发送到您邮箱~",
            }

        if "delivery_special_requests" not in self.knowledge_base:
            self.knowledge_base["delivery_special_requests"] = {
                "common_requests": [
                    {"type": "放门口", "response": "好的，我已备注放门口，会转达给骑手"},
                    {"type": "不用敲门", "response": "好的，已备注不敲门直接放门口"},
                    {"type": "尽快送达", "response": "收到，我会和骑手强调尽快配送"},
                    {"type": "医院配送", "response": "好的，医院配送我会提醒骑手找准地址"},
                ],
                "process": [
                    "记录客户配送要求",
                    "在订单中添加备注",
                    "联系骑手传达要求",
                    "跟踪配送进度",
                ],
            }

        # 保存更新后的知识库
        knowledge_path = os.path.expanduser(self.knowledge_file)
        with open(knowledge_path, "w", encoding="utf-8") as f:
            json.dump(self.knowledge_base, f, ensure_ascii=False, indent=2)

    def generate_report(self):
        """生成分析报告"""
        print("生成分析报告...")

        report_content = f"""# 美团IM客服聊天记录分析报告

## 数据概览
- 总对话数: {len(self.conversations)}
- 总消息数: {sum(conv.get("message_count", 0) for conv in self.conversations)}
- 分析时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 高频问题 TOP 10
"""

        for i, (question, count) in enumerate(self.high_freq_questions.most_common(10), 1):
            report_content += f"{i}. **{question}** - 出现 {count} 次\n"

        report_content += """
## 对话意图分布
"""

        intent_mapping = {
            "product_inquiry": "产品咨询",
            "logistics": "物流配送",
            "after_sales": "售后服务",
            "usage_question": "使用咨询",
            "invoice_request": "开发票",
            "privacy_order": "隐私订单",
            "other": "其他",
            "empty_conversation": "空对话",
        }

        for intent, sessions in self.intent_stats.items():
            intent_name = intent_mapping.get(intent, intent)
            count = len(sessions)
            avg_quality = sum(s.get("quality_score", 0) for s in sessions) / max(count, 1)
            percentage = (count / len(self.conversations)) * 100

            report_content += f"- **{intent_name}**: {count}个对话 ({percentage:.1f}%) - 平均回复质量: {avg_quality:.2f}\n"

        report_content += """
## 客服回复质量评估

### 高质量回复示例 (评分 > 0.8)
"""

        high_quality_examples = []
        for intent, examples in self.quality_examples.items():
            for example in examples:
                if example["quality_score"] > 0.8:
                    high_quality_examples.append(
                        {
                            "intent": intent_mapping.get(intent, intent),
                            "question": example["question"],
                            "answer": example["answer"],
                            "score": example["quality_score"],
                        }
                    )

        high_quality_examples.sort(key=lambda x: x["score"], reverse=True)

        for i, example in enumerate(high_quality_examples[:5], 1):
            report_content += f"""
**示例 {i}** - {example["intent"]} (评分: {example["score"]:.2f})
- 客户: {example["question"]}
- 客服: {example["answer"]}
"""

        report_content += """
### 低质量回复问题
"""

        low_quality_issues = [
            "过多使用'稍等'、'好的'等无实质内容回复",
            "对产品咨询回复不够专业和详细",
            "售后问题处理不够主动和完整",
            "缺少主动关怀和后续跟进",
        ]

        for issue in low_quality_issues:
            report_content += f"- {issue}\n"

        report_content += """
## 知识库覆盖率分析

### 已覆盖领域
"""

        covered_areas = [
            "产品基础知识 (血压计、体温计、血糖仪等)",
            "基础售后流程 (退换货、投诉处理)",
            "合规要求 (医疗器械合规用语)",
        ]

        for area in covered_areas:
            report_content += f"✅ {area}\n"

        report_content += """
### 知识库缺口
"""

        for gap in self.coverage_gaps:
            report_content += f"""
**{gap["type"]}** (出现频率: {gap["frequency"]}次)
- 问题: {gap["description"]}
- 建议: {gap["suggestion"]}
"""

        report_content += """
## 改进建议

### 客服培训重点
1. **专业知识强化**: 加强医疗器械产品知识培训，特别是血压计、体温计等高频咨询产品
2. **沟通技巧提升**: 减少'稍等'等无意义回复，增加实质性、有帮助的回复内容
3. **主动服务意识**: 对于售后问题要主动提供解决方案，不要等客户催促
4. **标准化话术**: 建立标准化但灵活的回复模板，提升服务一致性

### 知识库优化
1. **补充隐私订单处理规范**: 建立保密配送的标准说明和操作流程
2. **完善开发票流程**: 明确发票政策、所需信息、开具时限等细节
3. **加强配送服务**: 建立配送要求处理和骑手沟通标准流程
4. **更新few-shot示例**: 基于真实对话更新各意图的最佳回复示例

### 系统改进
1. **自动回复优化**: 减少无意义自动回复，增加更有针对性的智能回复
2. **知识库实时更新**: 建立从真实对话中持续提取优质内容的机制
3. **质量监控机制**: 建立客服回复质量评估和改进闭环

## 数据统计

### few-shot示例更新情况
"""

        best_examples = self.select_best_few_shot_examples()
        for intent, examples in best_examples.items():
            intent_name = intent_mapping.get(intent, intent)
            report_content += f"- {intent_name}: 更新了 {len(examples)} 个示例\n"

        report_content += f"""
### 知识库新增内容
- 隐私订单处理规范
- 开发票政策和流程
- 配送特殊要求处理规范

---
*报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""

        # 保存报告
        data_path = os.path.expanduser(self.data_file)
        report_file = data_path.replace("im_conversations_full.json", "im_analysis_report.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_content)

        print(f"分析报告已保存到: {report_file}")

    def run_analysis(self):
        """运行完整分析"""
        self.load_data()
        self.analyze_conversations()
        self.identify_knowledge_gaps()
        self.update_knowledge_base()
        self.generate_report()

        print("✅ IM聊天记录分析完成!")
        print(f"📊 分析了 {len(self.conversations)} 个对话")
        print(f"🎯 识别了 {len(self.intent_stats)} 种对话意图")
        print(
            f"💎 提取了 {sum(len(examples) for examples in self.quality_examples.values())} 个优质QA对"
        )
        print(f"📋 发现了 {len(self.coverage_gaps)} 个知识库缺口")


def main():
    analyzer = IMConversationAnalyzer(
        data_file="~/Dropbox/workspace/ai-store-manager/data/im_conversations_full.json",
        knowledge_file="~/Dropbox/workspace/ai-store-manager/data/cs_knowledge_structured.json",
    )
    analyzer.run_analysis()


if __name__ == "__main__":
    main()
