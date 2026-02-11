# Agent 详细说明

## 概述

系统包含 5 个独立的 AI Agent，每个基于 LangGraph 状态机构建。所有 Agent 通过 `Orchestrator` 统一调度，共享同一套 Skills 层和 LLM 调用封装。

---

## 1. Selection Agent（智能选品）

### 设计理念

模拟资深选品专员的工作流：先广泛收集市场信号，再交叉比对找出机会，最后评估可行性和打分排序。关键创新是**四路并行采集 + Self-Reflection 评分**。

### 输入/输出

| 字段 | 方向 | 说明 |
|------|------|------|
| `store_id` | 输入 | 门店 ID |
| `categories` | 输入 | 目标品类 |
| `trigger_type` | 输入 | scheduled / manual |
| `recommendations` | 输出 | TOP 20 推荐（含六维评分、采购链接、预估毛利）|
| `errors` | 输出 | 错误信息（并行合并） |

### 状态转换

```
fetch_data
    │
    ├──→ market_analysis       ← LLM (pro): 热搜词分析、热度评分
    ├──→ competitor_analysis   ← LLM (pro): 竞品覆盖分析、缺货发现
    ├──→ inventory_analysis    ← LLM (sonnet): 本店 SKU 盘点
    └──→ seasonal_analysis     ← LLM (flash): 季节/天气/节假日
              │
              ▼ (fan-in)
    gap_identification         ← LLM (pro): 交叉比对，输出缺品清单
              │
              ▼
    supplier_evaluation        ← Skills: ActionBook (1688/拼多多搜索)
              │                   LLM (deepseek): 供应商评估
              ▼
    scorer                     ← LLM (pro) + Self-Reflection:
                                  六维度评分 → 自检 → 修正
```

### Prompt 工程

- **market_analysis**: 系统提示定义分析框架（搜索量/增长率/转化率），要求通过 Tool Calling 输出结构化热度评分
- **gap_identification**: 输入包含 4 个分析结果的 JSON 摘要，要求识别 `(市场热品 ∪ 竞品热品) - 本店已有`
- **scorer**: 两轮调用——初始评分后，reflection prompt 要求检查 3 项：计算正确性、数据一致性、风险遗漏

### 模型选择

| 节点 | 模型 | 理由 |
|------|------|------|
| market/competitor/gap/scorer | `pro` (Gemini 2.5 Pro) | 复杂推理、多维度分析 |
| inventory | `sonnet` (Claude Sonnet) | 结构化盘点，中等复杂度 |
| seasonal | `flash` (Gemini Flash) | 简单匹配，成本最低 |
| supplier_evaluation | `deepseek` (DeepSeek V3) | 中文生成，极便宜 |

---

## 2. CustomerService Agent（智能客服）

### 设计理念

三阶段处理：**快速意图路由 → 高质量检索 → 专业回复生成**。核心创新是混合检索（向量+关键词+精排+GraphRAG），确保找到最相关的商品信息并获取完整知识子图。

### 输入/输出

| 字段 | 方向 | 说明 |
|------|------|------|
| `user_message` | 输入 | 用户消息 |
| `conversation_history` | 输入 | 历史对话 |
| `session_id` | 输入 | 会话 ID |
| `intent` | 输出 | 意图识别结果 |
| `route` | 输出 | 路由：faq / search / human |
| `enriched_results` | 输出 | GraphRAG 增强的检索结果 |
| `reply` | 输出 | 回复（含推荐商品、关联推荐） |

### 状态转换

```
intent_recognition     ← LLM (flash): 8 种意图分类
       │
       ▼
    route              ← 规则：投诉→human, 物流→faq, 其余→search
       │
  ┌────┼────┐
  ▼    ▼    ▼
 faq  search human
  │    │      │
  │    ▼      └──→ END (返回转人工标记)
  │ hybrid_search  ← Neo4j: 向量检索(30) + 全文检索(30) + RRF 融合
  │    │
  │    ▼
  │ reranker       ← BGE-Reranker: 精排 Top 5
  │    │
  │    ▼
  │ graphrag       ← Neo4j Cypher: 子图查询（适用人群/禁忌/关联商品）
  │    │
  └────┘
       ▼
 reply_generation  ← LLM (sonnet): 专业回复 + 合规检查 + 关联推荐
       │
       ▼
     END
```

### Prompt 工程

- **intent_recognition**: 枚举 8 种意图（product_inquiry, usage_guide, recommendation, logistics, after_sales, complaint, greeting, other），要求返回 `{intent, confidence, entities}`
- **reply_generation**: 系统提示包含合规规则（禁用词列表、禁忌提醒要求），输入包含 GraphRAG 子图（适用人群、禁忌、使用场景），要求生成亲切专业的回复并推荐 1-2 个关联商品

### 检索架构

```
用户查询: "老人用的测血糖的"
    │
    ├─→ BGE Embedding (1024d) → Neo4j 向量索引 → Top 30
    │
    ├─→ Neo4j 全文索引 → Top 30
    │
    └─→ RRF 融合（k=60） → Top 10
         │
         ▼
    BGE-Reranker 精排 → Top 5
         │
         ▼
    Neo4j Cypher 子图查询:
    MATCH (p:Product)-[r]-(related)
    WHERE p.product_id IN $top5_ids
    RETURN p, r, related
```

---

## 3. Alert Agent（智能预警）

### 设计理念

**先自动检测，再智能归因**。Prophet 时序预测处理销量异常（自动适应季节和节假日），规则引擎处理价格/库存/流量等确定性阈值。检测到异常后，LLM 进行五维归因和行动建议生成。

### 输入/输出

| 字段 | 方向 | 说明 |
|------|------|------|
| `products_data` | 输入 | 商品及销售数据（JSON） |
| `anomalies` | 输出 | 检测到的异常列表 |
| `root_causes` | 输出 | 每条异常的归因分析 |
| `actions` | 输出 | 每条异常的行动建议 |

### 状态转换

```
anomaly_detection     ← Prophet + 规则引擎
       │
  ┌────┴────┐
  ▼         ▼
[END]   root_cause    ← LLM (pro): 五维归因 + 置信度
 (无异常)    │
             ▼
         action        ← LLM (sonnet): 行动建议 + 优先级
             │
             ▼
           [END]
```

- **条件边**: `anomalies_found == 0` 时直接结束，避免无意义的 LLM 调用

### Prophet 配置

```yaml
# config/anomaly.yaml
prophet:
  changepoint_prior_scale: 0.05
  seasonality_prior_scale: 10
  holidays_prior_scale: 10
  yearly_seasonality: true
  weekly_seasonality: true
  chinese_holidays: true
  forecast_periods: 7
  confidence_interval: 0.95
```

---

## 4. Bundle Agent（智能套餐）

### 设计理念

数据驱动的套餐设计：从真实订单中挖掘高频共购组合（FP-Growth），再用 LLM 进行场景包装和智能定价，确保套餐既有数据支撑又有营销吸引力。

### 输入/输出

| 字段 | 方向 | 说明 |
|------|------|------|
| `orders_summary` | 输入 | 订单数据摘要 |
| `product_details` | 输入 | 商品详情 |
| `product_costs` | 输入 | 成本信息 |
| `association_rules` | 输出 | 关联规则（支持度/置信度/提升度） |
| `bundle_proposals` | 输出 | 套餐方案（名称/卖点/场景） |
| `bundle_pricing` | 输出 | 定价结果（原价/套餐价/折扣率/毛利率） |

### 状态转换

```
order_mining    ← FP-Growth: 关联规则挖掘 (support≥1%, confidence≥30%, lift≥1.5)
     │
     ▼
scene_design    ← LLM (deepseek): 场景命名 + 卖点提炼
     │
     ▼
  pricing       ← LLM (sonnet) + 数学模型: 折扣率计算 + 毛利约束(≥25%)
     │
     ▼
   [END]
```

---

## 5. Listing Agent（智能上架）

### 设计理念

从商品源链接到可上架信息的自动化流水线。重点是**合规校验**——医疗器械类目有严格的资质和宣传词限制，系统自动拦截违规内容。

### 输入/输出

| 字段 | 方向 | 说明 |
|------|------|------|
| `source_url` | 输入 | 1688/拼多多商品链接 |
| `source_platform` | 输入 | alibaba / pdd |
| `parsed_product` | 输出 | 解析的商品信息 |
| `matched_standard` | 输出 | 匹配的美团标品 |
| `listing_info` | 输出 | 优化后的上架信息（标题/价格/描述） |
| `compliance_check` | 输出 | 合规检查结果 |

### 状态转换

```
parser       ← Skills (ActionBook): 解析 1688/拼多多页面
    │
    ▼
matcher      ← LLM (flash) + 向量检索: 匹配美团标品库
    │
    ▼
filler       ← LLM (deepseek): 标题优化 + 定价建议
    │            公式: MAX(成本×2.5, 竞品均价×0.95, 标品均价×0.98)
    ▼
compliance   ← LLM (sonnet): 合规校验（资质/禁售词/虚假宣传/夸大宣传）
    │
    ▼
  [END]
```

---

## 多模型分层策略

### 模型矩阵

| 层级 | OpenRouter 模型 | Anthropic 直连 | 用途 | 成本/1M tokens |
|------|----------------|----------------|------|---------------|
| **flash** | Gemini 2.0 Flash | Claude Haiku 3.5 | 意图识别、简单分类 | ~$0.10 |
| **deepseek** | DeepSeek V3 | Claude Haiku 3.5 | 中文生成、文案创作 | ~$0.27 |
| **sonnet** | Claude Sonnet 4 | Claude Sonnet 4 | 高质量回复、合规检查 | ~$3.00 |
| **pro** | Gemini 2.5 Pro | Claude Sonnet 4 | 复杂推理、评分分析 | ~$1.25 |

### 成本优化分析

**假设单店日均调用量**:

| Agent | 日均触发 | 节点数 | 主要模型 | 估算日成本 |
|-------|---------|--------|---------|-----------|
| Selection | 1 次/天 | 8 | pro + deepseek | ~¥2.0 |
| CustomerService | 50 条/天 | 5 | flash + sonnet | ~¥3.0 |
| Alert | 288 次/天 | 1-3 | flash + pro | ~¥2.5 |
| Bundle | 1 次/天 | 3 | deepseek + sonnet | ~¥0.5 |
| Listing | 5 次/天 | 4 | flash + deepseek | ~¥0.5 |
| **日合计** | | | | **~¥8.5** |
| **月合计** | | | | **~¥255** |

对比全部使用 Claude Opus 的方案（月均 ~¥2000+），**多模型分层节省 87%**。

### Self-Reflection 策略

仅在高价值决策节点使用双轮调用（`call_tool_with_reflection`）：

- Selection Scorer：评分结果直接影响采购决策
- 其他节点使用单轮调用，控制成本

Self-Reflection 流程：
1. 初始调用：生成评分结果
2. Reflection 调用：输入初始结果，要求检查计算正确性、数据一致性、风险遗漏
3. 返回修正后的结果

额外成本约 2x，但准确率提升 ~15%，仅用于关键节点。

---

## LLM 调用统一封装

所有 Agent 节点通过 `src/agents/llm.py` 的 `call_tool()` 函数调用 LLM：

```python
result = await call_tool(
    prompt="分析以下市场数据...",
    tool={
        "name": "market_analysis",
        "description": "市场分析结果",
        "input_schema": {
            "type": "object",
            "properties": {
                "hot_keywords": {"type": "array", ...},
                "heat_scores": {"type": "array", ...},
            },
            "required": ["hot_keywords", "heat_scores"],
        },
    },
    model=MODEL_PRO,
    system="你是专业的零售市场分析师...",
    trace_name="selection_market_analysis",
)
```

好处：
- **统一格式**：Tool schema 用 Anthropic 格式，自动转换为 OpenAI function 格式
- **100% 结构化输出**：强制 Tool Calling，不依赖 JSON 解析
- **自动追踪**：Langfuse trace + Prometheus 指标
- **一键切换**：通过 `LLM_PROVIDER` 环境变量切换 OpenRouter/Anthropic
