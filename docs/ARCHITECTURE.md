# 架构设计文档

## 系统分层

```
┌──────────────────────────────────────────────────────────────┐
│  表现层 (Presentation)                                        │
│  React 管理后台 · 企业微信通知 · Swagger UI                    │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  API 层 (src/api/)                                            │
│  FastAPI + Pydantic schemas + 统一错误处理                     │
│  路由: selection / cs / alerts / bundles / listing             │
│        products / dashboard                                   │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  调度层 (src/agents/orchestrator.py)                          │
│  Orchestrator: 接收请求 → 路由到子 Agent → 聚合结果            │
│  惰性编译 LangGraph：按需创建，全局缓存                        │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Agent 层 (src/agents/*/)                                     │
│  5 个独立 LangGraph 状态机                                     │
│  每个 Agent = graph.py (状态机) + nodes.py (节点) + state.py  │
│                                                               │
│  统一 LLM 调用: src/agents/llm.py                             │
│    ├─ OpenRouter (Gemini Flash / DeepSeek V3 / Claude)        │
│    ├─ Anthropic 直连                                          │
│    ├─ Tool Calling (结构化输出)                                │
│    └─ Self-Reflection (两轮调用)                               │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Skills 层 (src/skills/)                                      │
│  ActionBook · Neo4jSkill · DatabaseSkill · EmbeddingSkill     │
│  RerankerSkill · ProphetSkill · CalculatorSkill · Notifier    │
│  Factory: 按需注入                                             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  数据层 (src/db/)                                             │
│  PostgreSQL 16 (asyncpg) · Neo4j 5 (async driver) · Redis 7  │
│  连接池管理 + lifespan 生命周期                                │
└──────────────────────────────────────────────────────────────┘
```

## 数据流

### 选品数据流

```
定时触发 (06:00)
    │
    ▼
Orchestrator.run_selection()
    │
    ▼
fetch_data ─────── 加载原始数据到 State
    │
    ├──→ market_analysis ──────┐
    ├──→ competitor_analysis ──┤  并行执行（LangGraph fan-out）
    ├──→ inventory_analysis ──┤
    └──→ seasonal_analysis ───┘
                               │  fan-in（等待全部完成）
                               ▼
                    gap_identification ── 交叉比对，识别缺品机会
                               │
                               ▼
                    supplier_evaluation ── 1688 + 拼多多双渠道查询
                               │
                               ▼
                    scorer ── 六维度评分 + Self-Reflection
                               │
                               ▼
                    State.recommendations ── 写入 PostgreSQL
```

### 客服数据流

```
用户消息 → POST /api/cs/chat
    │
    ▼
intent_recognition ── LLM 意图分类 (flash 模型)
    │
    ▼
route ── 路由决策
    ├─ faq ──────→ faq_reply → reply_generation → END
    ├─ search ──→ hybrid_search ── Neo4j 向量检索 + 全文检索
    │                │
    │                ▼
    │            reranker ── BGE Reranker 精排
    │                │
    │                ▼
    │            graphrag ── Neo4j 子图查询（适用人群/禁忌/关联）
    │                │
    │                ▼
    │            reply_generation ── LLM 生成专业回复 → END
    │
    └─ human ──→ human_transfer → END (转人工)
```

### 预警数据流

```
定时触发 (每 5 分钟)
    │
    ▼
anomaly_detection
    ├─ Prophet 时序预测 → 销量异常
    ├─ 规则引擎 → 价格/库存/流量/竞品异常
    └─ 聚合分析 → 多因素叠加
    │
    ├─ 无异常 → END
    │
    └─ 有异常
         │
         ▼
    root_cause ── LLM 五维归因（竞品/库存/定价/外部/运营）
         │
         ▼
    action ── LLM 生成行动建议 → 写入 alerts 表 → 企业微信推送
```

## Agent 状态机

### Selection Agent

```
                    ┌─────────┐
                    │fetch_data│
                    └────┬────┘
           ┌─────────┬──┴──┬─────────┐
           ▼         ▼     ▼         ▼
      ┌────────┐┌────────┐┌────────┐┌────────┐
      │market  ││competi-││inven-  ││season- │
      │analysis││tor     ││tory    ││al      │
      └───┬────┘└───┬────┘└───┬────┘└───┬────┘
           └─────────┴──┬──┴─────────┘
                        ▼
               ┌────────────────┐
               │gap_identification│
               └───────┬────────┘
                       ▼
              ┌─────────────────┐
              │supplier_evaluation│
              └───────┬─────────┘
                      ▼
                 ┌─────────┐
                 │ scorer  │
                 └────┬────┘
                      ▼
                    [END]
```

- **并行**: fetch_data 同时触发 4 个分析节点
- **聚合**: 4 个节点全部完成后才进入 gap_identification
- **State 合并**: `errors` 字段使用 `Annotated[list, _merge_lists]` 支持并行写入

### CustomerService Agent

```
┌──────────────────┐
│intent_recognition│
└────────┬─────────┘
         ▼
     ┌───────┐
     │ route │
     └───┬───┘
    ┌────┼────┐
    ▼    ▼    ▼
┌─────┐┌──────┐┌───────┐
│ faq ││search││ human │
└──┬──┘└──┬───┘└───┬───┘
   │      ▼        │
   │  ┌────────┐   │
   │  │reranker│   │
   │  └───┬────┘   │
   │      ▼        │
   │  ┌────────┐   │
   │  │graphrag│   │
   │  └───┬────┘   │
   │      │        │
   └──┬───┘        │
      ▼            ▼
┌───────────┐  ┌──────┐
│reply_gen  │  │[END] │
└─────┬─────┘  └──────┘
      ▼
   [END]
```

### Alert Agent

```
┌───────────────────┐
│anomaly_detection  │
└────────┬──────────┘
         │
    ┌────┴────┐
    ▼         ▼
 [END]   ┌──────────┐   (条件: anomalies_found > 0)
         │root_cause│
         └────┬─────┘
              ▼
         ┌────────┐
         │ action │
         └────┬───┘
              ▼
           [END]
```

### Bundle Agent

```
┌─────────────┐     ┌──────────────┐     ┌─────────┐
│order_mining │ ──→ │scene_design  │ ──→ │ pricing │ ──→ [END]
└─────────────┘     └──────────────┘     └─────────┘
```

### Listing Agent

```
┌────────┐     ┌─────────┐     ┌────────┐     ┌────────────┐
│ parser │ ──→ │ matcher │ ──→ │ filler │ ──→ │ compliance │ ──→ [END]
└────────┘     └─────────┘     └────────┘     └────────────┘
```

## 数据库 ER 图

```
┌──────────────┐       ┌──────────────┐
│   products   │       │    orders    │
├──────────────┤       ├──────────────┤
│ product_id PK│◄──┐   │ order_id  PK │
│ name         │   │   │ platform     │
│ barcode      │   │   │ total_amount │
│ category     │   │   │ status       │
│ brand        │   │   │ order_time   │
│ cost_price   │   │   └──────┬───────┘
│ retail_price │   │          │
│ stock        │   │          │ 1:N
│ monthly_sales│   │          ▼
│ status       │   │   ┌──────────────┐
└──────┬───────┘   │   │ order_items  │
       │           │   ├──────────────┤
       │           ├───│ product_id FK│
       │           │   │ order_id  FK │
       │           │   │ quantity     │
       │           │   │ unit_price   │
       │           │   └──────────────┘
       │           │
       │ 1:N       │   ┌──────────────────┐
       ▼           │   │ competitor_stores │
┌──────────────┐   │   ├──────────────────┤
│sales_history │   │   │ competitor_id PK │
├──────────────┤   │   │ name             │
│ product_id FK│───┘   │ distance_km      │
│ sale_date    │       │ threat_level     │
│ quantity     │       └────────┬─────────┘
│ revenue      │                │ 1:N
└──────────────┘                ▼
                        ┌──────────────────────┐
┌──────────────┐        │ competitor_products   │
│   alerts     │        ├──────────────────────┤
├──────────────┤        │ competitor_id FK      │
│ alert_id  PK │        │ product_name          │
│ product_id FK│        │ price                 │
│ alert_type   │        │ monthly_sales         │
│ severity     │        │ is_stockout           │
│ root_cause   │        └──────────────────────┘
│ status       │
└──────────────┘        ┌──────────────────────┐
                        │   bundles            │
┌──────────────┐        ├──────────────────────┤
│selection_runs│        │ bundle_id PK         │
├──────────────┤        │ name                 │
│ run_id    PK │        │ products (JSONB)     │
│ status       │        │ original_price       │
│ keywords     │        │ bundle_price         │
│ result(JSONB)│        │ discount_percent     │
│ result_count │        │ status               │
└──────────────┘        └──────────────────────┘

┌──────────────────────┐   ┌──────────────────────┐
│ prophet_models       │   │ parameter_versions   │
├──────────────────────┤   ├──────────────────────┤
│ product_id PK FK     │   │ version_id PK        │
│ model_data (BYTEA)   │   │ parameter_type       │
│ training_samples     │   │ parameter_values     │
│ last_trained_at      │   │ status               │
│ metrics (JSONB)      │   │ validation_score     │
└──────────────────────┘   └──────────────────────┘

┌──────────────────────────┐
│ recommendation_outcomes  │
├──────────────────────────┤
│ recommendation_id        │
│ product_keyword          │
│ predicted_score          │
│ was_purchased            │
│ actual_monthly_sales     │
│ outcome_score            │
└──────────────────────────┘
```

### Neo4j 图模型

```
(:Product) ─[:SUITABLE_FOR {confidence}]─→ (:Population)
(:Product) ─[:CONTRAINDICATED_FOR {reason}]─→ (:Population)
(:Product) ─[:USED_IN]─→ (:Scenario)
(:Product) ─[:OFTEN_BOUGHT_WITH {support,confidence,lift}]─→ (:Product)
(:Product) ─[:UPGRADE_TO {reason}]─→ (:Product)
(:Product) ─[:ALTERNATIVE_TO {similarity}]─→ (:Product)
(:Product) ─[:HELPS_WITH]─→ (:Symptom)
(:FAQ) ─[:ANSWERS]─→ (:Product)

向量索引: Product.embedding (1024d, cosine)
向量索引: FAQ.question_embedding (1024d, cosine)
全文索引: Product(name, description, category)
全文索引: FAQ(question, answer)
```

## 技术决策记录

### 为什么选 LangGraph？

| 考虑方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| LangChain LCEL | 简单链式调用 | 不支持条件分支、并行、状态管理 | ❌ 不满足复杂流程需求 |
| CrewAI | 多 Agent 协作 | 抽象层厚，自定义能力弱 | ❌ 过重 |
| **LangGraph** | 状态机+并行+条件分支+TypedDict | 学习曲线稍高 | ✅ 完美匹配 |
| 自研 | 完全控制 | 开发维护成本高 | ❌ 不必要 |

LangGraph 核心价值：
- **并行 fan-out/fan-in**：选品 Agent 4 个分析节点并行执行
- **条件路由**：客服 Agent 根据意图路由到不同处理链
- **TypedDict 状态管理**：类型安全，IDE 友好
- **Annotated 合并策略**：支持并行节点写入同一字段

### 为什么选 Neo4j？

- **知识图谱原生支持**：商品-人群-场景-症状的多维关联关系
- **GraphRAG**：客服检索到商品后，一次 Cypher 查询获取完整子图（适用人群、禁忌、关联商品）
- **向量索引**：Neo4j 5 原生支持向量索引，无需额外的向量数据库
- **全文索引**：内置 Lucene 全文检索，实现混合搜索（向量+关键词）
- **APOC 插件**：图算法支持（社区发现、路径分析）

对比 Milvus/Pinecone 等纯向量库：我们需要的不只是向量相似度，更需要结构化的关系推理。

### 为什么选 OpenRouter？

| 方案 | 优点 | 缺点 |
|------|------|------|
| Anthropic 直连 | 质量最高 | 成本高，单一供应商 |
| **OpenRouter** | 多模型统一 API | 多一层延迟 |
| 自部署开源模型 | 无 API 费用 | GPU 成本高，质量不稳定 |

OpenRouter 的核心价值是**多模型分层**：
- `google/gemini-2.0-flash` → 意图识别、简单分类（极便宜）
- `deepseek/deepseek-chat-v3` → 中文文本生成（便宜且中文强）
- `anthropic/claude-sonnet-4` → 高质量回复和分析
- `google/gemini-2.5-pro-preview` → 复杂推理（选品评分）

通过分层，单店月均 AI 费用从 ~¥2000 降至 ~¥300。

### 为什么用 Tool Calling 做结构化输出？

所有 LLM 调用统一使用 Tool Calling 模式（`call_tool`），而非自由文本：

1. **100% 结构化**：返回 JSON 而非自由文本，消除解析失败
2. **Schema 约束**：通过 `input_schema` 定义字段类型和枚举值
3. **跨模型兼容**：`llm.py` 自动将 Anthropic tool 格式转为 OpenAI function 格式
4. **Langfuse 追踪**：统一记录每次调用的 input/output/tokens/duration

### 为什么 PostgreSQL + Neo4j + Redis 三库架构？

| 数据库 | 职责 | 选择理由 |
|--------|------|----------|
| **PostgreSQL** | 业务数据（商品/订单/预警/运行记录） | 事务、复杂查询、成熟稳定 |
| **Neo4j** | 知识图谱 + 向量索引 | 关系推理、GraphRAG、混合检索 |
| **Redis** | 缓存 + 会话 + 限流 | 高速读写、TTL、发布订阅 |

三者协同：
- API 查询走 PostgreSQL（结构化查询）
- 客服检索走 Neo4j（语义+关系推理）
- 热数据缓存到 Redis（减少数据库压力）
