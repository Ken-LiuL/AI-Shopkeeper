"""
ConversationManager — 统一的对话上下文管理器

核心思路：
1. 每个 session 维护一个 "topic stack"（话题栈）
2. 用户的新消息先经过 topic resolution（确定是延续话题还是切换话题）
3. LLM 调用时，把当前 topic 的完整上下文传入（而不是按 intent 过滤）
4. 消灭 intent 驱动 → 改为 topic 驱动

话题栈示例：
  [
    {"topic": "血压计推荐", "products": ["欧姆龙HEM-7121"], "started_at": 3},
    {"topic": "自我介绍", "ephemeral": true}  ← 临时话题，不覆盖主话题
  ]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Topic:
    """对话话题"""
    name: str                          # 话题名称（如 "血压计推荐"）
    category: str = "general"          # 分类：product / after_sales / logistics / general
    products: list[str] = field(default_factory=list)   # 涉及的商品名
    keywords: list[str] = field(default_factory=list)   # 关键词
    started_at_turn: int = 0           # 开始的对话轮次
    ephemeral: bool = False            # 是否临时话题（如问候、自报身份）
    resolved: bool = False             # 话题是否已解决

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "products": self.products,
            "keywords": self.keywords,
            "started_at_turn": self.started_at_turn,
            "ephemeral": self.ephemeral,
            "resolved": self.resolved,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Topic:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 话题识别规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 商品关键词 → 话题名
PRODUCT_TOPIC_MAP = {
    "血压": "血压计",
    "体温": "体温计",
    "血糖": "血糖仪",
    "口罩": "口罩",
    "创可贴": "创可贴",
    "纱布": "纱布/绷带",
    "绷带": "纱布/绷带",
    "轮椅": "轮椅",
    "拐杖": "助行器",
    "雾化": "雾化器",
    "制氧": "制氧机",
    "呼吸机": "呼吸机",
    "退热贴": "退热贴",
    "面膜": "医用面膜",
    "敷料": "医用敷料",
    "欧姆龙": "欧姆龙产品",
    "鱼跃": "鱼跃产品",
    "体重秤": "体重秤",
}

# 临时话题识别模式
EPHEMERAL_PATTERNS = [
    (r"^我是.{1,10}$", "自我介绍"),
    (r"^(你好|hi|hello|在吗|您好)\s*$", "问候"),
    (r"^(谢谢|感谢|thx|thanks)\s*$", "致谢"),
    (r"^(好的|嗯|行|ok|明白)\s*$", "确认"),
]

# 上下文延续信号词（表示用户在追问前一个话题）
CONTINUATION_SIGNALS = [
    "有哪些", "都有什么", "还有吗", "有啥", "哪个", "哪款",
    "多少钱", "价格", "贵吗", "便宜", "打折",
    "推荐", "有没有", "哪个好", "什么牌子",
    "怎么用", "用法", "一盒", "能用多久",
    "其他的", "别的", "还有别的",
    "具体", "详细", "展开说说",
]


class ConversationManager:
    """统一的对话上下文管理器

    职责：
    1. 维护话题栈（topic stack）
    2. 解析每条消息属于哪个话题（新话题 / 延续 / 临时）
    3. 提供给 LLM 的上下文构建（基于当前活跃话题）
    4. 序列化/反序列化（存入 Redis）
    """

    def __init__(self):
        self.topic_stack: list[Topic] = []
        self.turn_count: int = 0

    # ── Topic Resolution ──────────────────────────────────────

    def resolve_topic(
        self, message: str, conversation_history: list[dict] | None = None
    ) -> Topic:
        """确定当前消息属于哪个话题

        决策逻辑：
        1. 检查是否是临时话题（问候、自报身份等）
        2. 检查是否包含新商品关键词 → 创建新话题
        3. 检查是否是延续信号 → 延续当前活跃话题
        4. 兜底：延续当前活跃话题
        """
        m = message.strip().lower() if message else ""
        self.turn_count += 1

        # Step 1: 临时话题
        for pattern, name in EPHEMERAL_PATTERNS:
            if re.match(pattern, m, re.IGNORECASE):
                topic = Topic(
                    name=name,
                    category="general",
                    ephemeral=True,
                    started_at_turn=self.turn_count,
                )
                # 不压栈（或压栈但不替换活跃话题）
                logger.info(f"[CM] Ephemeral topic: {name} (active topic unchanged)")
                return topic

        # Step 2: 新商品话题
        for keyword, topic_name in PRODUCT_TOPIC_MAP.items():
            if keyword in m:
                # 检查是否跟当前活跃话题相同
                active = self.get_active_topic()
                if active and topic_name in active.name:
                    # 同一个话题的延续
                    active.keywords.append(keyword)
                    logger.info(f"[CM] Continuing topic: {active.name}")
                    return active

                # 新话题
                topic = Topic(
                    name=topic_name,
                    category="product",
                    keywords=[keyword],
                    started_at_turn=self.turn_count,
                )
                self.topic_stack.append(topic)
                logger.info(f"[CM] New product topic: {topic_name}")
                return topic

        # Step 3: 延续信号
        is_continuation = len(m) <= 25 and any(sig in m for sig in CONTINUATION_SIGNALS)
        if is_continuation:
            active = self.get_active_topic()
            if active:
                logger.info(f"[CM] Continuation of topic: {active.name}")
                return active
            # 无活跃话题但用户在追问 → 从历史推断
            if conversation_history:
                inferred = self._infer_topic_from_history(conversation_history)
                if inferred:
                    self.topic_stack.append(inferred)
                    logger.info(f"[CM] Inferred topic from history: {inferred.name}")
                    return inferred

        # Step 4: 售后/投诉/物流 — 新话题
        after_sales_kw = ["退", "换", "坏了", "破损", "过期", "质量"]
        complaint_kw = ["投诉", "举报", "315", "律师", "消协", "骗"]
        logistics_kw = ["发货", "物流", "送到", "配送", "还没到", "骑手"]

        if any(kw in m for kw in complaint_kw):
            topic = Topic(name="投诉", category="complaint", started_at_turn=self.turn_count)
            self.topic_stack.append(topic)
            return topic
        if any(kw in m for kw in after_sales_kw):
            topic = Topic(name="售后", category="after_sales", started_at_turn=self.turn_count)
            self.topic_stack.append(topic)
            return topic
        if any(kw in m for kw in logistics_kw):
            topic = Topic(name="物流", category="logistics", started_at_turn=self.turn_count)
            self.topic_stack.append(topic)
            return topic

        # Step 5: 兜底 — 延续活跃话题或创建通用话题
        active = self.get_active_topic()
        if active:
            logger.info(f"[CM] Default: continuing active topic: {active.name}")
            return active

        topic = Topic(name="通用咨询", category="general", started_at_turn=self.turn_count)
        self.topic_stack.append(topic)
        return topic

    def get_active_topic(self) -> Topic | None:
        """获取当前活跃话题（最近的非临时、非已解决话题）"""
        for topic in reversed(self.topic_stack):
            if not topic.ephemeral and not topic.resolved:
                return topic
        return None

    def add_product_to_topic(self, product_name: str) -> None:
        """将商品关联到当前活跃话题"""
        active = self.get_active_topic()
        if active and product_name not in active.products:
            active.products.append(product_name)

    def resolve_topic_as_done(self) -> None:
        """标记当前活跃话题为已解决"""
        active = self.get_active_topic()
        if active:
            active.resolved = True

    # ── History Inference ─────────────────────────────────────

    def _infer_topic_from_history(self, conversation_history: list[dict]) -> Topic | None:
        """从对话历史推断话题"""
        for msg in reversed(conversation_history[-8:]):
            content = (msg.get("content") or "").lower()
            for keyword, topic_name in PRODUCT_TOPIC_MAP.items():
                if keyword in content:
                    return Topic(
                        name=topic_name,
                        category="product",
                        keywords=[keyword],
                        started_at_turn=max(0, self.turn_count - 1),
                    )
        return None

    # ── Context Building ──────────────────────────────────────

    def build_topic_context(self, current_topic: Topic) -> str:
        """构建当前话题的上下文摘要，注入到 system prompt"""
        if current_topic.ephemeral:
            # 临时话题：告诉 LLM 这是临时的，主话题是什么
            active = self.get_active_topic()
            if active:
                return (
                    f"用户当前是{current_topic.name}（临时），"
                    f"但主要话题仍是「{active.name}」，"
                    f"回应后请自然回到主话题。"
                )
            return ""

        context_parts = [f"当前话题：{current_topic.name}"]
        if current_topic.products:
            context_parts.append(f"涉及商品：{'、'.join(current_topic.products)}")
        if current_topic.category == "product":
            context_parts.append("用户在咨询商品，延续这个话题回答。")
        elif current_topic.category == "after_sales":
            context_parts.append("用户遇到售后问题，耐心处理。")
        elif current_topic.category == "complaint":
            context_parts.append("用户在投诉，先安抚情绪再解决。")

        # 话题栈信息（如果有多个话题）
        non_ephemeral = [t for t in self.topic_stack if not t.ephemeral and not t.resolved]
        if len(non_ephemeral) > 1:
            earlier = [t.name for t in non_ephemeral[:-1]]
            context_parts.append(f"之前还聊过：{'、'.join(earlier)}")

        return "\n".join(context_parts)

    # ── Serialization ─────────────────────────────────────────

    def to_json(self) -> str:
        """序列化为 JSON（存入 Redis）"""
        return json.dumps({
            "topic_stack": [t.to_dict() for t in self.topic_stack],
            "turn_count": self.turn_count,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> ConversationManager:
        """从 JSON 反序列化"""
        cm = cls()
        try:
            parsed = json.loads(data)
            cm.topic_stack = [Topic.from_dict(t) for t in parsed.get("topic_stack", [])]
            cm.turn_count = parsed.get("turn_count", 0)
        except Exception as e:
            logger.warning(f"[CM] Failed to deserialize: {e}")
        return cm


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Redis 集成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CM_KEY_PREFIX = "cs:session:cm:"


async def load_conversation_manager(redis, session_id: str) -> ConversationManager:
    """从 Redis 加载对话管理器"""
    if redis is None:
        return ConversationManager()
    try:
        data = await redis.get(f"{_CM_KEY_PREFIX}{session_id}")
        if data:
            return ConversationManager.from_json(data)
    except Exception as e:
        logger.warning(f"[CM] Failed to load from Redis: {e}")
    return ConversationManager()


async def save_conversation_manager(
    redis, session_id: str, cm: ConversationManager, ttl: int = 86400
) -> None:
    """保存对话管理器到 Redis"""
    if redis is None:
        return
    try:
        await redis.set(
            f"{_CM_KEY_PREFIX}{session_id}",
            cm.to_json(),
            ex=ttl,
        )
    except Exception as e:
        logger.warning(f"[CM] Failed to save to Redis: {e}")
