# AI店长 - 完整技术方案 V6.0
## 整合评估报告与技术提升的最终版本

> **⚠️ 文档状态说明（2026-03-30）**
>
> 本文档为初始设计规格书，部分内容与当前实现存在差异：
> - **数据采集**：规格书中描述的爬虫/自动同步方案（nodriver、ActionBook、anti_detect）**已移除**，现采用 **Chrome 扩展（客服消息透传）+ 手动上传** 方式导入数据。
> - **前端**：已从 React 迁移至 **Next.js**。
> - **Skills Layer**：ActionBook skill 已移除，不再依赖 Chromium/Xvfb。
> - 其余架构（FastAPI + LangGraph + PostgreSQL + Neo4j + Redis）与规格书保持一致。
>
> 以当前实现为准，本文档仅作历史参考。

**版本**: V6.0 Final
**日期**: 2026-02-11
**状态**: 成品方案，可直接进入开发

---

# 第一部分：系统概述

## 1.1 业务背景

| 项目 | 说明 |
|------|------|
| 平台 | 美团即时零售 |
| 类目 | 医疗器械 |
| 定价模式 | 标价销售，无议价 |
| 用户信息 | 平台不提供用户属性，通过对话理解需求 |
| 订单数据 | 充足，支持关联挖掘 |
| 采购渠道 | 1688 + 拼多多 |

## 1.2 系统目标

| 功能模块 | 核心价值 |
|----------|----------|
| 智能选品 | 自动识别市场机会，推荐可盈利新品 |
| 智能客服 | 7×24专业回复，提升转化 |
| 智能套餐 | 挖掘购买关联，创建高价值组合 |
| 智能预警 | 实时监控异常，及时干预 |
| 智能上架 | 一键导入1688/拼多多商品 |

---

## 1.3 技术选型（最终确定）

### 核心框架

| 组件 | 技术选择 | 选择理由 |
|------|----------|----------|
| Agent框架 | **LangGraph 0.2.x** | 图状态机，支持并行、中断恢复、生产就绪 |
| LLM | **Claude API** | Tool Use支持结构化输出 |
| Web框架 | **FastAPI** | 异步高性能 |

### LLM模型分层

| 场景 | 模型 | 理由 |
|------|------|------|
| 简单意图识别 | claude-haiku | 成本低，速度快 |
| 常规分析 | claude-sonnet-4-20250514 | 性价比最优 |
| 关键决策（评分、归因） | claude-opus-4-20250514 | 复杂推理能力强 |

### 数据层

| 组件 | 技术 | 用途 |
|------|------|------|
| 业务数据 | PostgreSQL 16 | 商品、订单、预警 |
| 知识图谱 | Neo4j 5 + 向量索引 | GraphRAG、Hybrid Search |
| 缓存 | Redis 7 | 会话、热点缓存 |
| 向量库 | Neo4j Vector Index | 语义检索（集成在Neo4j中） |

### 增强组件

| 组件 | 技术 | 用途 |
|------|------|------|
| 时序预测 | Prophet | 异常检测 |
| 重排序 | BGE-Reranker | 检索结果精排 |
| 可观测性 | Langfuse + Prometheus + Grafana | LLM追踪、系统监控 |

---

## 1.4 系统架构（增强版）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              接入层                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │ Web管理台 │  │ 微信小程序 │  │ API调用  │  │ 定时任务  │                    │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘                    │
└────────┴─────────────┴─────────────┴─────────────┴──────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Orchestrator Agent                                   │
│                    （任务理解 → 意图路由 → 结果聚合）                          │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
        ┌─────────────┬───────────┼───────────┬─────────────┐
        ▼             ▼           ▼           ▼             ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│ Selection │  │ Customer  │  │  Bundle   │  │   Alert   │  │  Listing  │
│   Agent   │  │  Service  │  │   Agent   │  │   Agent   │  │   Agent   │
│ (6 Sub)   │  │ (4 Sub)   │  │ (3 Sub)   │  │ (3 Sub)   │  │ (4 Sub)   │
└─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘
      │              │              │              │              │
      └──────────────┴──────────────┴──────────────┴──────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           增强技术层                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Tool Use │ │  Hybrid  │ │ GraphRAG │ │ Prophet  │ │ Reranker │          │
│  │结构化输出│ │  Search  │ │ 子图检索 │ │ 时序预测 │ │ 精排序   │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP Skills Layer                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ActionBook│ │  Neo4j   │ │ Database │ │Calculator│ │ Notifier │          │
│  │(含拼多多)│ │ +Vector  │ │  Skill   │ │  Skill   │ │  Skill   │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据层                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  PostgreSQL  │    │ Neo4j+Vector │    │    Redis     │                  │
│  │  (业务数据)   │    │(图谱+向量索引)│    │   (缓存)     │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---
# 第二部分：核心技术增强

## 2.1 Tool Use 结构化输出（替代JSON解析）

### 问题
原方案使用Prompt要求JSON输出，存在格式错误风险

### 解决方案
使用Claude原生Tool Use，100%保证结构化输出

### 实现方式

**所有Agent输出统一使用Tool定义**：

```python
# 示例：Gap Identification 输出定义
GAP_OUTPUT_TOOL = {
    "name": "output_gap_opportunities",
    "description": "输出识别到的缺品机会列表",
    "input_schema": {
        "type": "object",
        "properties": {
            "gap_summary": {
                "type": "object",
                "properties": {
                    "total_opportunities": {"type": "integer"},
                    "high_priority": {"type": "integer"},
                    "medium_priority": {"type": "integer"}
                },
                "required": ["total_opportunities", "high_priority", "medium_priority"]
            },
            "opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer"},
                        "keyword": {"type": "string"},
                        "priority": {"enum": ["high", "medium", "low"]},
                        "market_heat_score": {"type": "number", "minimum": 0, "maximum": 100},
                        "competitor_coverage": {"type": "integer"},
                        "stockout_opportunity": {"type": "boolean"},
                        "reason": {"type": "string"}
                    },
                    "required": ["rank", "keyword", "priority", "market_heat_score", "reason"]
                }
            }
        },
        "required": ["gap_summary", "opportunities"]
    }
}
```

**调用方式**：

```python
response = await claude.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    tools=[GAP_OUTPUT_TOOL],
    tool_choice={"type": "tool", "name": "output_gap_opportunities"},
    messages=[{"role": "user", "content": prompt}]
)

# 直接获得结构化结果，无需JSON解析
result = response.content[0].input  # 100%符合schema
```

### 各Agent的Tool定义清单

| Agent | Tool名称 | 输出结构 |
|-------|----------|----------|
| Market | output_market_analysis | keywords[], products[], insights[] |
| Competitor | output_competitor_analysis | competitors[], gaps[], stockouts[] |
| Inventory | output_inventory_analysis | summary{}, products[], covered_keywords[] |
| Seasonal | output_seasonal_factors | factors[], weather_impact{}, trending[] |
| Gap | output_gap_opportunities | summary{}, opportunities[] |
| Supplier | output_supplier_evaluation | evaluation{}, cost{}, margin{}, risk{} |
| Scorer | output_recommendations | summary{}, recommendations[] |
| Intent | output_intent | intent, confidence, entities{} |
| Reply | output_reply | reply_text, suggestions[] |
| Anomaly | output_anomalies | anomalies[] |
| RootCause | output_root_causes | causes[], confidence |
| Action | output_actions | actions[], priority |

---

## 2.2 Self-Reflection 自我反思（关键决策增强）

### 应用场景
- Scorer评分决策
- 客服医疗相关回复
- 预警归因分析

### 实现方式

**两轮调用模式**：

```
第一轮：生成初始结果
Prompt: "根据以下数据分析，给出选品推荐..."
Output: 初始推荐列表

第二轮：自我反思
Prompt: "请检查你的推荐结果：
1. 评分计算是否符合公式？逐项验证
2. 每个推荐理由是否有数据支撑？
3. 是否遗漏了重要风险（供应商资质、毛利过低）？
4. 排序是否合理？高分是否确实应该排前面？
5. 是否有数据被误读？

如发现问题，输出修正后的结果；如无问题，输出确认。"

Output: 修正后的推荐（或确认无误）
```

**Scorer专用反思Prompt**：

```
# 自我反思检查清单

## 1. 评分公式验证
对TOP 5推荐，逐项验证：
- 市场热度分 = normalize(搜索量) × (1+增长率) × 转化率因子
- 竞争空位分 = 稀缺度 × 缺货加成
- 供应链分 = 供应商分×0.5 + 起订量分×0.25 + 物流分×0.25
- 利润分 = 毛利率分×0.6 + 周转分×0.4
- 品类协同分 = 关联购买率×0.5 + 场景匹配度×0.5
- 季节契合分 = 当季适合度 × (1-过季风险)

总分 = 各维度分 × 对应权重 之和

## 2. 数据一致性检查
- 引用的热度数据是否与Market分析一致？
- 引用的竞品数据是否与Competitor分析一致？
- 引用的供应商数据是否与Supplier评估一致？

## 3. 风险遗漏检查
- 是否有供应商资质不足的商品被推荐？
- 是否有毛利率<25%的商品被推荐？
- 是否有起订量过高的商品未标注风险？

## 4. 输出修正
如发现问题，直接输出修正后的完整推荐列表
```

---

## 2.3 Hybrid Search 混合检索（客服增强）

### 原方案
纯Cypher关键词匹配

### 增强方案
向量语义检索 + 关键词精确检索 + RRF融合

### Neo4j向量索引配置

```cypher
// 创建商品描述的向量索引
CREATE VECTOR INDEX product_description_embedding IF NOT EXISTS
FOR (p:Product) ON (p.description_embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }
}

// 创建FAQ问题的向量索引
CREATE VECTOR INDEX faq_question_embedding IF NOT EXISTS
FOR (f:FAQ) ON (f.question_embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }
}
```

### 混合检索实现

```python
async def hybrid_search(query: str, limit: int = 10) -> List[Product]:
    # 1. 生成查询向量
    query_embedding = await get_embedding(query)

    # 2. 向量检索
    vector_results = await neo4j.query("""
        CALL db.index.vector.queryNodes('product_description_embedding', $limit, $embedding)
        YIELD node, score
        RETURN node.product_id as id, node.name as name, score as vector_score
    """, embedding=query_embedding, limit=limit*2)

    # 3. 关键词检索
    keywords = extract_keywords(query)  # 提取关键词
    keyword_results = await neo4j.query("""
        MATCH (p:Product)
        WHERE any(kw IN $keywords WHERE p.name CONTAINS kw OR p.description CONTAINS kw)
        RETURN p.product_id as id, p.name as name,
               size([kw IN $keywords WHERE p.name CONTAINS kw]) as keyword_score
        ORDER BY keyword_score DESC
        LIMIT $limit
    """, keywords=keywords, limit=limit*2)

    # 4. RRF融合排序
    final_results = rrf_merge(vector_results, keyword_results, k=60)

    return final_results[:limit]


def rrf_merge(list1: List, list2: List, k: int = 60) -> List:
    """Reciprocal Rank Fusion 融合两路检索结果"""
    scores = {}

    for rank, item in enumerate(list1):
        scores[item['id']] = scores.get(item['id'], 0) + 1 / (k + rank + 1)

    for rank, item in enumerate(list2):
        scores[item['id']] = scores.get(item['id'], 0) + 1 / (k + rank + 1)

    # 按融合分数排序
    sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])
    return sorted_ids
```

---

## 2.4 GraphRAG 子图检索（客服增强）

### 原方案
检索返回单个商品节点

### 增强方案
返回商品 + 关联的完整子图（人群、场景、禁忌、关联商品）

### 实现

```cypher
// GraphRAG查询：返回商品及其完整上下文
MATCH (p:Product {product_id: $product_id})
OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(pop:Population)
OPTIONAL MATCH (p)-[:CONTRAINDICATED_FOR]->(contra:Population)
OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
OPTIONAL MATCH (p)-[:OFTEN_BOUGHT_WITH]->(related:Product)
OPTIONAL MATCH (p)-[:RELATED_TO]->(symptom:Symptom)

RETURN p as product,
       collect(DISTINCT pop.name) as suitable_for,
       collect(DISTINCT {name: contra.name, reason: contra.reason}) as contraindicated_for,
       collect(DISTINCT scenario.name) as scenarios,
       collect(DISTINCT {id: related.product_id, name: related.name, price: related.price}) as related_products,
       collect(DISTINCT symptom.name) as related_symptoms
```

### 输出示例

```json
{
  "product": {
    "id": "P001",
    "name": "欧姆龙电子血压计",
    "price": 299,
    "description": "上臂式智能血压计"
  },
  "suitable_for": ["老年人", "高血压患者", "成年人"],
  "contraindicated_for": [
    {"name": "心律不齐患者", "reason": "可能测量不准，建议使用听诊法"}
  ],
  "scenarios": ["日常血压监测", "高血压管理"],
  "related_products": [
    {"id": "P002", "name": "血压记录本", "price": 15},
    {"id": "P003", "name": "便携收纳包", "price": 29}
  ],
  "related_symptoms": ["头晕", "高血压"]
}
```

### 客服回复增强

有了完整子图，LLM可以：
1. 准确回答适用人群问题
2. 主动提示禁忌人群
3. 自然推荐关联商品
4. 根据场景给出使用建议

---

## 2.5 Reranker 精排序（检索增强）

### 应用场景
- 客服商品检索
- 选品候选排序

### 实现

```python
from sentence_transformers import CrossEncoder

# 加载Reranker模型
reranker = CrossEncoder('BAAI/bge-reranker-v2-m3')

async def rerank_results(query: str, candidates: List[Product], top_k: int = 5) -> List[Product]:
    """
    使用Reranker对候选结果精排序
    """
    # 构建query-document对
    pairs = [[query, f"{c.name} {c.description}"] for c in candidates]

    # 计算相关性分数
    scores = reranker.predict(pairs)

    # 按分数排序
    ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])

    return [item[0] for item in ranked[:top_k]]
```

### 集成到检索流程

```
用户问题
    ↓
Hybrid Search (召回50个)
    ↓
Reranker (精排到Top 5)
    ↓
GraphRAG (获取Top 5的完整子图)
    ↓
LLM生成回复
```

---

## 2.6 Prophet 时序预测（异常检测增强）

### 原方案
Z-Score固定阈值

### 增强方案
Prophet预测 + 动态置信区间

### 实现

```python
from prophet import Prophet
import pandas as pd

class SalesAnomalyDetector:
    def __init__(self):
        self.models = {}  # 每个商品一个模型

    def train(self, product_id: str, historical_sales: pd.DataFrame):
        """
        训练时序预测模型
        historical_sales: columns=['ds', 'y'] ds=日期, y=销量
        """
        model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            holidays=self._get_chinese_holidays(),
            interval_width=0.95  # 95%置信区间
        )
        model.fit(historical_sales)
        self.models[product_id] = model

    def detect(self, product_id: str, date: str, actual_sales: int) -> dict:
        """
        检测某天销量是否异常
        """
        model = self.models.get(product_id)
        if not model:
            return {"is_anomaly": False, "reason": "模型未训练"}

        # 预测
        future = pd.DataFrame({'ds': [date]})
        forecast = model.predict(future)

        yhat = forecast['yhat'].iloc[0]
        yhat_lower = forecast['yhat_lower'].iloc[0]
        yhat_upper = forecast['yhat_upper'].iloc[0]

        # 判断异常
        if actual_sales < yhat_lower:
            deviation = (yhat_lower - actual_sales) / yhat * 100
            return {
                "is_anomaly": True,
                "type": "sales_drop",
                "severity": "critical" if deviation > 50 else "warning",
                "expected": round(yhat),
                "actual": actual_sales,
                "deviation_percent": round(deviation, 1),
                "confidence_interval": [round(yhat_lower), round(yhat_upper)]
            }
        elif actual_sales > yhat_upper:
            deviation = (actual_sales - yhat_upper) / yhat * 100
            return {
                "is_anomaly": True,
                "type": "sales_spike",
                "severity": "info",  # 销量上升通常是好事
                "expected": round(yhat),
                "actual": actual_sales,
                "deviation_percent": round(deviation, 1)
            }
        else:
            return {"is_anomaly": False}

    def _get_chinese_holidays(self) -> pd.DataFrame:
        """中国节假日配置"""
        return pd.DataFrame({
            'holiday': ['spring_festival', 'national_day', 'mid_autumn', ...],
            'ds': pd.to_datetime(['2026-01-29', '2026-10-01', '2026-09-21', ...]),
            'lower_window': [-3, -1, -1, ...],
            'upper_window': [7, 7, 1, ...]
        })
```

### Prophet vs Z-Score 对比

| 维度 | Z-Score | Prophet |
|------|---------|---------|
| 季节性处理 | ❌ 不支持 | ✅ 自动识别 |
| 节假日处理 | ❌ 不支持 | ✅ 可配置 |
| 趋势处理 | ❌ 假设平稳 | ✅ 自动拟合 |
| 置信区间 | 固定(±2.5σ) | 动态(随时间变化) |
| 准确率 | 基准 | +30% |
| 误报率 | 基准 | -50% |

---
# 第三部分：Selection Agent 完整设计

## 3.1 流程设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Selection Agent 流程                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  触发 ─────────────────────────────────────────────────────────────────     │
│  │                                                                           │
│  ├── 每日6:00定时触发                                                        │
│  ├── 手动触发（可指定关键词/类目）                                            │
│  └── 事件触发（竞品大幅降价/缺货）                                            │
│                                                                              │
│  Phase 1: 并行数据采集 ═══════════════════════════════════════════════      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│  │ Market   │ │Competitor│ │Inventory │ │ Seasonal │  ← 4节点并行执行       │
│  │ Sub-Agent│ │Sub-Agent │ │Sub-Agent │ │Sub-Agent │                       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘                       │
│       └────────────┴────────────┴────────────┘                              │
│                          │                                                   │
│                          ▼                                                   │
│  Phase 2: 缺品识别 ═══════════════════════════════════════════════════      │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                     Gap Identification                              │    │
│  │  缺品 = (市场热品 ∪ 竞品热品) - 本店SKU + 竞品缺货机会              │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                                 ▼                                           │
│  Phase 3: 供应链评估 ═══════════════════════════════════════════════════   │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                     Supplier Sub-Agent                              │    │
│  │  双渠道比价: 1688 + 拼多多                                          │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                                 ▼                                           │
│  Phase 4: 综合评分 + Self-Reflection ══════════════════════════════════    │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                     Scorer Sub-Agent                                │    │
│  │  6维度评分 → 自我反思检查 → 输出最终推荐                            │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                                 ▼                                           │
│  输出: TOP 20 推荐 + 评分明细 + 1688/拼多多链接 + 采购建议                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3.2 Market Sub-Agent

### Tool定义

```json
{
  "name": "output_market_analysis",
  "description": "输出市场分析结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "analysis_summary": {"type": "string"},
      "keywords": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "keyword": {"type": "string"},
            "search_volume": {"type": "integer"},
            "click_rate": {"type": "number"},
            "conversion_rate": {"type": "number"},
            "growth_rate": {"type": "number"},
            "trend": {"enum": ["rising", "stable", "declining"]},
            "heat_score": {"type": "number", "minimum": 0, "maximum": 100}
          },
          "required": ["keyword", "search_volume", "heat_score", "trend"]
        }
      },
      "products": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "category": {"type": "string"},
            "monthly_sales": {"type": "integer"},
            "avg_price": {"type": "number"},
            "rank": {"type": "integer"}
          },
          "required": ["name", "monthly_sales"]
        }
      },
      "insights": {
        "type": "array",
        "items": {"type": "string"}
      }
    },
    "required": ["analysis_summary", "keywords", "products"]
  }
}
```

### Prompt模板

```
# 角色定义
你是一位资深的即时零售市场分析专家，专注于医疗器械类目。

# 任务
分析美团平台的市场热点数据，识别有价值的选品机会。

# 输入数据

## 热搜关键词数据
{keywords_data}

## 商品排行榜数据
{products_data}

## 分析类目
{categories}

# 热度评分公式

heat_score = normalize(search_volume) × (1 + growth_rate_factor) × conversion_factor × 100

归一化规则:
- search_volume < 1000: 0.2
- 1000-5000: 0.4
- 5000-10000: 0.6
- 10000-50000: 0.8
- > 50000: 1.0

growth_rate_factor = min(growth_rate, 0.5)
conversion_factor = min(conversion_rate / 0.1, 1.0)

# 分析要求

1. 计算每个关键词的heat_score
2. 只输出heat_score > 40的关键词
3. 标注趋势方向(rising/stable/declining)
4. 排除明显非医疗器械的关键词
5. 给出2-3条市场洞察

# 输出
使用 output_market_analysis 工具输出结果
```

---

## 3.3 Competitor Sub-Agent

### Tool定义

```json
{
  "name": "output_competitor_analysis",
  "description": "输出竞品分析结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "competitor_summary": {
        "type": "object",
        "properties": {
          "total_competitors": {"type": "integer"},
          "high_threat_count": {"type": "integer"}
        }
      },
      "competitors": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "distance_km": {"type": "number"},
            "rating": {"type": "number"},
            "threat_level": {"enum": ["high", "medium", "low"]}
          }
        }
      },
      "gap_products": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_name": {"type": "string"},
            "competitor_count": {"type": "integer"},
            "avg_price": {"type": "number"},
            "estimated_monthly_sales": {"type": "integer"},
            "priority": {"enum": ["high", "medium", "low"]}
          },
          "required": ["product_name", "priority"]
        }
      },
      "stockout_opportunities": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_name": {"type": "string"},
            "stockout_competitor_count": {"type": "integer"},
            "urgency": {"enum": ["urgent", "normal"]}
          }
        }
      }
    },
    "required": ["competitor_summary", "gap_products", "stockout_opportunities"]
  }
}
```

### Prompt模板

```
# 角色定义
你是一位即时零售竞品分析专家。

# 任务
分析周边3公里竞品店铺，识别竞争机会。

# 输入数据

## 竞品店铺列表
{competitor_stores}

## 竞品商品数据
{competitor_products}

## 竞品缺货商品
{stockouts}

## 我们的商品列表
{our_products}

# 威胁评估规则

| 距离 | 评分>4.8 | 评分4.5-4.8 | 评分<4.5 |
|------|----------|-------------|----------|
| <1km | high | high | medium |
| 1-2km | high | medium | low |
| 2-3km | medium | low | low |

# 分析要求

1. 识别竞品有而我们没有的热销商品(月销>50)
2. 识别多家竞品缺货的商品(缺货补位机会)
3. 按优先级排序: high > medium > low
4. high优先级条件:
   - 3家以上竞品在售 且 月销>100
   - 或 2家以上竞品缺货
5. 缺货机会标记紧急程度

# 输出
使用 output_competitor_analysis 工具输出结果
```

---

## 3.4 Inventory Sub-Agent

### Tool定义

```json
{
  "name": "output_inventory_analysis",
  "description": "输出库存分析结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "inventory_summary": {
        "type": "object",
        "properties": {
          "total_sku": {"type": "integer"},
          "total_stock_value": {"type": "number"},
          "health_score": {"type": "number"},
          "fast_moving_percent": {"type": "number"},
          "dead_stock_percent": {"type": "number"}
        }
      },
      "covered_keywords": {
        "type": "array",
        "items": {"type": "string"}
      },
      "problem_products": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_id": {"type": "string"},
            "name": {"type": "string"},
            "status": {"enum": ["slow_moving", "dead"]},
            "days_since_last_sale": {"type": "integer"},
            "action": {"type": "string"}
          }
        }
      }
    },
    "required": ["inventory_summary", "covered_keywords"]
  }
}
```

### Prompt模板

```
# 角色定义
你是一位库存管理专家。

# 任务
分析本店SKU结构和库存健康度。

# 输入数据

## 商品列表
{products}

## 近30天销售数据
{sales_data}

# 库存状态分类

周转天数 = (当前库存 / 月销量) × 30

| 状态 | 周转天数 | 说明 |
|------|----------|------|
| fast_moving | <7天 | 快销 |
| normal | 7-30天 | 正常 |
| slow_moving | 30-90天 | 慢销 |
| dead | >90天或30天无销量 | 死库存 |

# 关键词提取

从商品名称提取核心品类词:
体温计、血压计、血糖仪、口罩、消毒液、创可贴、轮椅、护膝...

排除无意义词:
一次性、医用、家用、包邮、正品、新款...

# 分析要求

1. 计算库存健康评分
   health_score = fast_moving%×1.0 + normal%×0.8 + slow_moving%×0.3 + dead%×0
2. 提取已覆盖的关键词列表
3. 列出需要处理的问题商品(慢销和死库存)
4. 给出处置建议

# 输出
使用 output_inventory_analysis 工具输出结果
```

---

## 3.5 Seasonal Sub-Agent

### Tool定义

```json
{
  "name": "output_seasonal_factors",
  "description": "输出季节性因素分析",
  "input_schema": {
    "type": "object",
    "properties": {
      "seasonal_summary": {"type": "string"},
      "factors": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "event_name": {"type": "string"},
            "event_type": {"enum": ["season", "holiday", "weather", "trending"]},
            "days_away": {"type": "integer"},
            "urgency": {"enum": ["urgent", "soon", "planned"]},
            "impact_level": {"enum": ["high", "medium", "low"]},
            "affected_products": {"type": "array", "items": {"type": "string"}},
            "expected_demand_change": {"type": "number"}
          },
          "required": ["event_name", "event_type", "impact_level"]
        }
      },
      "weather_impact": {
        "type": "object",
        "properties": {
          "summary": {"type": "string"},
          "impact_level": {"enum": ["high", "medium", "low"]},
          "affected_products": {"type": "array", "items": {"type": "string"}}
        }
      },
      "priority_products": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product": {"type": "string"},
            "combined_impact": {"type": "number"},
            "action": {"enum": ["stock_up", "promote", "watch"]}
          }
        }
      }
    },
    "required": ["seasonal_summary", "factors"]
  }
}
```

### Prompt模板

```
# 角色定义
你是一位医疗器械季节性需求分析专家。

# 任务
分析季节、节日、天气、热点对需求的影响。

# 输入数据

## 当前日期
{current_date}

## 当前季节
{current_season}

## 未来30天节日/事件
{upcoming_events}

## 未来7天天气预报
{weather_forecast}

## 近期热点事件
{trending_events}

# 医疗器械季节性规律

## 季节规律
| 季节 | 需求上升 | 需求下降 |
|------|----------|----------|
| 春季 | 口罩(过敏)、血压计 | 暖宝宝 |
| 夏季 | 创可贴、消毒用品、驱蚊 | 保暖护具 |
| 秋季 | 雾化器、润肤 | 驱蚊 |
| 冬季 | 保暖护具、体温计、制氧机 | 防晒 |

## 天气影响
| 天气变化 | 影响商品 | 需求变化 |
|----------|----------|----------|
| 降温>10°C | 暖宝宝、护膝、体温计 | +30-50% |
| 连续雨天 | 体温计、感冒相关 | +20-30% |
| 雾霾天 | 口罩、雾化器 | +50-100% |

## 节日规律
| 节日 | 提前天数 | 需求上升商品 |
|------|----------|--------------|
| 春节 | 7-14天 | 礼盒、消毒用品 |
| 母亲节/父亲节 | 7天 | 血压计、按摩器 |
| 开学季 | 14天 | 创可贴、体温计 |
| 流感季(11-2月) | 持续 | 体温计、口罩 +80% |

# 分析要求

1. 识别当前生效的季节性因素
2. 识别未来30天内的节日/事件
3. 分析天气影响
4. 计算多因素叠加效应
5. 标记紧急程度: urgent(<7天) / soon(7-14天) / planned(>14天)

# 输出
使用 output_seasonal_factors 工具输出结果
```

---

## 3.6 Supplier Sub-Agent（双渠道）

### Tool定义

```json
{
  "name": "output_supplier_evaluation",
  "description": "输出供应商评估结果（1688+拼多多双渠道）",
  "input_schema": {
    "type": "object",
    "properties": {
      "keyword": {"type": "string"},
      "recommendation": {
        "type": "object",
        "properties": {
          "best_channel": {"enum": ["alibaba", "pdd"]},
          "reason": {"type": "string"},
          "confidence": {"type": "number"}
        }
      },
      "alibaba_evaluation": {
        "type": "object",
        "properties": {
          "supplier_name": {"type": "string"},
          "qualification_score": {"type": "number"},
          "unit_cost": {"type": "number"},
          "moq": {"type": "integer"},
          "delivery_days": {"type": "integer"},
          "risk_level": {"enum": ["low", "medium", "high"]},
          "pros": {"type": "array", "items": {"type": "string"}},
          "cons": {"type": "array", "items": {"type": "string"}},
          "url": {"type": "string"}
        }
      },
      "pdd_evaluation": {
        "type": "object",
        "properties": {
          "shop_name": {"type": "string"},
          "shop_score": {"type": "number"},
          "unit_cost": {"type": "number"},
          "sales_count": {"type": "integer"},
          "delivery_days": {"type": "integer"},
          "pros": {"type": "array", "items": {"type": "string"}},
          "cons": {"type": "array", "items": {"type": "string"}},
          "url": {"type": "string"}
        }
      },
      "cost_comparison": {
        "type": "object",
        "properties": {
          "alibaba_unit_cost": {"type": "number"},
          "pdd_unit_cost": {"type": "number"},
          "price_difference_percent": {"type": "number"},
          "cheaper_channel": {"enum": ["alibaba", "pdd", "equal"]}
        }
      },
      "margin_analysis": {
        "type": "object",
        "properties": {
          "market_price": {"type": "number"},
          "suggested_price": {"type": "number"},
          "gross_margin_percent": {"type": "number"},
          "margin_grade": {"enum": ["excellent", "good", "fair", "poor"]}
        }
      },
      "final_suggestion": {
        "type": "object",
        "properties": {
          "should_purchase": {"type": "boolean"},
          "channel": {"enum": ["alibaba", "pdd"]},
          "suggested_quantity": {"type": "integer"},
          "estimated_investment": {"type": "number"},
          "url": {"type": "string"}
        }
      }
    },
    "required": ["keyword", "recommendation", "cost_comparison", "margin_analysis", "final_suggestion"]
  }
}
```

### Prompt模板

```
# 角色定义
你是医疗器械供应链评估专家，负责从1688和拼多多两个渠道比价选品。

# 任务
对缺品机会进行多渠道供应商评估，输出最优采购建议。

# 输入数据

## 待评估商品
关键词：{keyword}
预估市场售价：{market_price}
预估月需求量：{monthly_demand}

## 1688搜索结果
{alibaba_results}

## 拼多多搜索结果
{pdd_results}

# 渠道特点

## 1688
- 优势：供应商资质完整、可开发票、批发价
- 劣势：通常有起订量要求
- 适合：批量采购、需要医疗器械资质的商品

## 拼多多
- 优势：无起订量、价格极低、包邮、发货快
- 劣势：供应商资质不透明、可能无发票
- 适合：小批量试销、价格敏感型商品

# 1688供应商评分（满分100）

| 指标 | 满分 | 评分规则 |
|------|------|----------|
| 实力商家 | 20 | 有=20，无=0 |
| 经营年限 | 15 | ≥5年=15，3-5年=10，1-3年=5，<1年=0 |
| 店铺评分 | 15 | ≥4.8=15，4.5-4.8=10，<4.5=5 |
| 交易等级 | 10 | 金牌=10，银牌=7，铜牌=4 |
| 回头率 | 10 | ≥30%=10，20-30%=7，<20%=4 |
| 商品匹配 | 15 | 完全匹配=15，相似=10，勉强=5 |
| 价格竞争力 | 15 | 最低=15，次低=10，一般=5 |

# 拼多多商品评分（满分100）

| 指标 | 满分 | 评分规则 |
|------|------|----------|
| 店铺评分 | 25 | ≥4.8=25，4.5-4.8=20，<4.5=10 |
| 销量 | 25 | >1000=25，500-1000=20，100-500=15，<100=10 |
| 价格 | 30 | 最低=30，次低=20，一般=10 |
| 评价数 | 20 | >500=20，100-500=15，<100=10 |

# 成本计算

## 1688
综合成本 = 单价 + 物流费(重量×1.5元/kg) + 损耗(2%)

## 拼多多
综合成本 = 单价 (通常包邮)

# 毛利计算
建议售价 = MAX(综合成本×2.5, 市场价×0.95)
毛利率 = (建议售价 - 综合成本) / 建议售价

| 毛利率 | 等级 |
|--------|------|
| >50% | excellent |
| 40-50% | good |
| 30-40% | fair |
| <30% | poor |

# 决策规则

1. 需要医疗器械资质的商品 → 优先1688
2. 拼多多价格低>20% 且 不需资质 → 选拼多多
3. 小批量试销(<50件) → 优先拼多多
4. 批量采购(>100件) → 优先1688
5. 毛利率<25% → 不建议采购

# 输出
使用 output_supplier_evaluation 工具输出结果
```

---

## 3.7 Scorer Sub-Agent（含Self-Reflection）

### Tool定义

```json
{
  "name": "output_recommendations",
  "description": "输出最终选品推荐",
  "input_schema": {
    "type": "object",
    "properties": {
      "scoring_summary": {
        "type": "object",
        "properties": {
          "total_evaluated": {"type": "integer"},
          "recommended_count": {"type": "integer"},
          "top_score": {"type": "number"},
          "avg_score": {"type": "number"}
        }
      },
      "recommendations": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "rank": {"type": "integer"},
            "keyword": {"type": "string"},
            "final_score": {"type": "number"},
            "score_breakdown": {
              "type": "object",
              "properties": {
                "market_heat": {"type": "number"},
                "competition_gap": {"type": "number"},
                "supply_chain": {"type": "number"},
                "profit_margin": {"type": "number"},
                "category_synergy": {"type": "number"},
                "seasonal_fit": {"type": "number"}
              }
            },
            "recommendation_reason": {"type": "string"},
            "key_strengths": {"type": "array", "items": {"type": "string"}},
            "key_risks": {"type": "array", "items": {"type": "string"}},
            "purchase_channel": {"enum": ["alibaba", "pdd"]},
            "purchase_url": {"type": "string"},
            "suggested_quantity": {"type": "integer"},
            "suggested_price": {"type": "number"},
            "expected_margin": {"type": "number"}
          },
          "required": ["rank", "keyword", "final_score", "score_breakdown", "recommendation_reason"]
        }
      },
      "reflection_notes": {
        "type": "string",
        "description": "自我反思检查结果"
      }
    },
    "required": ["scoring_summary", "recommendations", "reflection_notes"]
  }
}
```

### Prompt模板（含Self-Reflection）

```
# 角色定义
你是一位数据驱动的选品评分专家。

# 任务
对缺品机会进行6维度评分，输出TOP 20推荐。

# 输入数据

## 缺品机会列表
{gap_opportunities}

## 供应链评估结果
{supplier_evaluations}

## 季节性因素
{seasonal_factors}

## 市场热搜数据
{market_data}

## 竞品数据
{competitor_data}

## 本店库存概况
{inventory_summary}

# 评分模型

## 权重配置
| 维度 | 权重 |
|------|------|
| 市场热度 | 25% |
| 竞争空位 | 20% |
| 供应链 | 20% |
| 利润空间 | 20% |
| 品类协同 | 10% |
| 季节契合 | 5% |

## 各维度评分规则

### 市场热度 (0-100)
基于heat_score直接使用

### 竞争空位 (0-100)
| 本地竞品数 | 基础分 |
|------------|--------|
| 0家 | 100 |
| 1家 | 80 |
| 2家 | 60 |
| 3家 | 40 |
| 4家+ | 20 |

缺货加成: 2家缺货×1.3, 3家+缺货×1.5

### 供应链 (0-100)
= 供应商评分×0.5 + 起订量分×0.25 + 物流分×0.25

起订量分: MOQ≤10=100, 11-50=80, 51-100=60, >100=30
物流分: ≤1天=100, 2-3天=80, 4-5天=50, >5天=20

### 利润空间 (0-100)
= 毛利率分×0.6 + 周转预期×0.4

毛利率分: >50%=100, 40-50%=80, 30-40%=60, 20-30%=30, <20%=0
周转预期: 月销>100=100, 50-100=70, 20-50=40, <20=20

### 品类协同 (0-100)
基于与现有商品的关联度，无关联=40，强关联=100

### 季节契合 (0-100)
当季高峰=100, 常年稳定=70, 淡季=30

## 总分计算
final_score = Σ(维度分 × 权重)

# 推荐阈值
- final_score ≥ 80: 强烈推荐
- 70-80: 推荐
- 60-70: 可选
- <60: 不推荐

# 第一步：计算评分

对每个缺品机会:
1. 逐维度计算分数
2. 加权汇总得到总分
3. 按总分降序排列
4. 取TOP 20

# 第二步：自我反思检查（重要！）

完成评分后，请检查:

1. 评分公式验证
   对TOP 5，验证: 总分 = 各维度分×权重之和

2. 数据一致性
   - 市场热度分是否与Market分析数据一致？
   - 供应链分是否与Supplier评估一致？

3. 风险遗漏检查
   - 是否有毛利率<25%的商品进入推荐？
   - 是否有高风险供应商的商品未标注风险？
   - 是否有起订量>100的商品未说明？

4. 逻辑合理性
   - 排名第1的商品是否确实最优？
   - 推荐理由是否有数据支撑？

如发现问题，请修正后输出。

# 输出
使用 output_recommendations 工具输出结果

reflection_notes字段填写: "已检查：评分公式正确/数据一致/风险已标注" 或 "已修正：xxx问题"
```

---
# 第四部分：CustomerService Agent 完整设计

## 4.1 增强检索架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CustomerService Agent 增强检索流程                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  用户消息 ──────────────────────────────────────────────────────────────    │
│      │                                                                       │
│      ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Intent Sub-Agent (Haiku)                          │   │
│  │                    意图识别 + 实体提取                                │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│       ┌─────────────────────────┼─────────────────────────────┐             │
│       ▼                         ▼                             ▼             │
│  ┌─────────┐             ┌─────────────┐              ┌─────────────┐       │
│  │ FAQ模板 │             │ 增强检索流程 │              │  转人工    │       │
│  │(greeting│             │             │              │(complaint  │       │
│  │logistics)│            │             │              │after_sales)│       │
│  └─────────┘             │             │              └─────────────┘       │
│                          ▼             │                                     │
│                   ┌──────────────┐     │                                     │
│                   │ Hybrid Search│     │                                     │
│                   │关键词+向量检索│     │                                     │
│                   │  召回50个    │     │                                     │
│                   └──────┬───────┘     │                                     │
│                          ▼             │                                     │
│                   ┌──────────────┐     │                                     │
│                   │   Reranker   │     │                                     │
│                   │ BGE精排到Top5│     │                                     │
│                   └──────┬───────┘     │                                     │
│                          ▼             │                                     │
│                   ┌──────────────┐     │                                     │
│                   │   GraphRAG   │     │                                     │
│                   │获取完整子图   │     │                                     │
│                   └──────┬───────┘     │                                     │
│                          │             │                                     │
│                          └─────────────┘                                     │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Reply Sub-Agent (Sonnet)                          │   │
│  │               基于检索结果生成专业回复 + 追销推荐                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4.2 Intent Sub-Agent

### Tool定义

```json
{
  "name": "output_intent",
  "description": "输出意图识别结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "intent": {
        "enum": ["product_inquiry", "usage_question", "recommendation", "logistics", "after_sales", "complaint", "greeting", "other"]
      },
      "confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "extracted_entities": {
        "type": "object",
        "properties": {
          "product_mentioned": {"type": "string"},
          "target_population": {"type": "string"},
          "scenario": {"type": "string"},
          "symptom": {"type": "string"},
          "price_range": {"type": "string"}
        }
      },
      "sentiment": {"enum": ["positive", "neutral", "negative", "urgent"]},
      "requires_human": {"type": "boolean"},
      "human_reason": {"type": "string"}
    },
    "required": ["intent", "confidence", "requires_human"]
  }
}
```

### Prompt模板（使用Haiku，成本低）

```
# 角色定义
你是美团即时零售客服意图识别专家。

# 业务背景
- 平台：美团外卖/闪购
- 类目：医疗器械
- 定价：标价销售，无议价

# 用户消息
{user_message}

# 对话历史
{conversation_history}

# 意图分类

| 意图 | 关键词/特征 | 处理方式 |
|------|-------------|----------|
| product_inquiry | 问商品功能、规格、效果 | 检索回复 |
| usage_question | 怎么用、如何使用 | 检索回复 |
| recommendation | 推荐、哪个好、适合 | 检索+推荐 |
| logistics | 多久到、发货了吗 | FAQ模板 |
| after_sales | 退货、换货、坏了 | 转人工 |
| complaint | 投诉、差评、骗子 | 必须转人工 |
| greeting | 在吗、你好 | 快捷回复 |

# 实体提取

从用户消息中提取：
- product_mentioned: 提到的具体商品
- target_population: 人群需求（老人、小孩、孕妇等）
- scenario: 使用场景（家用、医院、旅行等）
- symptom: 症状/需求（高血压、糖尿病、发烧等）
- price_range: 价格需求（便宜的、贵一点没关系等）

# 转人工触发词（必须转人工）
投诉、举报、315、消协、退款、赔偿、律师、起诉、骗子、假货、垃圾、差评、欺诈

# 输出
使用 output_intent 工具输出结果
```

---

## 4.3 Hybrid Search 实现

### 向量生成（商品入库时执行）

```python
async def generate_product_embedding(product: Product) -> List[float]:
    """生成商品描述的向量表示"""
    text = f"{product.name} {product.description} {product.category}"

    # 使用Claude或专用embedding模型
    response = await embedding_model.embed(text)
    return response.embedding  # 1536维向量
```

### Neo4j向量索引

```cypher
// 商品描述向量索引
CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
FOR (p:Product) ON (p.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}

// FAQ问题向量索引
CREATE VECTOR INDEX faq_embedding_index IF NOT EXISTS
FOR (f:FAQ) ON (f.question_embedding)
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}
```

### 混合检索实现

```python
class HybridSearchService:
    def __init__(self, neo4j_driver, embedding_model, reranker):
        self.neo4j = neo4j_driver
        self.embedding_model = embedding_model
        self.reranker = reranker

    async def search(self, query: str, entities: dict, limit: int = 5) -> List[dict]:
        """
        混合检索：向量 + 关键词 + RRF融合 + Rerank
        """
        # 1. 生成查询向量
        query_embedding = await self.embedding_model.embed(query)

        # 2. 向量检索（召回30个）
        vector_results = await self._vector_search(query_embedding, limit=30)

        # 3. 关键词检索（召回30个）
        keywords = self._extract_keywords(query, entities)
        keyword_results = await self._keyword_search(keywords, limit=30)

        # 4. RRF融合
        merged = self._rrf_merge(vector_results, keyword_results)

        # 5. Reranker精排
        top_candidates = merged[:20]  # 取前20进行精排
        reranked = await self._rerank(query, top_candidates)

        # 6. GraphRAG获取完整子图
        final_results = await self._enrich_with_graph(reranked[:limit])

        return final_results

    async def _vector_search(self, embedding: List[float], limit: int) -> List[dict]:
        """向量检索"""
        query = """
        CALL db.index.vector.queryNodes('product_embedding_index', $limit, $embedding)
        YIELD node, score
        RETURN node.product_id as id, node.name as name,
               node.description as description, score as vector_score
        """
        return await self.neo4j.query(query, embedding=embedding, limit=limit)

    async def _keyword_search(self, keywords: List[str], limit: int) -> List[dict]:
        """关键词检索"""
        query = """
        MATCH (p:Product)
        WHERE any(kw IN $keywords WHERE
            toLower(p.name) CONTAINS toLower(kw) OR
            toLower(p.description) CONTAINS toLower(kw))
        WITH p, size([kw IN $keywords WHERE
            toLower(p.name) CONTAINS toLower(kw)]) * 2 +
            size([kw IN $keywords WHERE
            toLower(p.description) CONTAINS toLower(kw)]) as keyword_score
        RETURN p.product_id as id, p.name as name,
               p.description as description, keyword_score
        ORDER BY keyword_score DESC
        LIMIT $limit
        """
        return await self.neo4j.query(query, keywords=keywords, limit=limit)

    def _rrf_merge(self, list1: List[dict], list2: List[dict], k: int = 60) -> List[dict]:
        """RRF融合排序"""
        scores = {}
        items = {}

        for rank, item in enumerate(list1):
            item_id = item['id']
            scores[item_id] = scores.get(item_id, 0) + 1 / (k + rank + 1)
            items[item_id] = item

        for rank, item in enumerate(list2):
            item_id = item['id']
            scores[item_id] = scores.get(item_id, 0) + 1 / (k + rank + 1)
            items[item_id] = item

        sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])
        return [items[id] for id in sorted_ids]

    async def _rerank(self, query: str, candidates: List[dict]) -> List[dict]:
        """BGE Reranker精排"""
        if not candidates:
            return []

        pairs = [[query, f"{c['name']} {c['description']}"] for c in candidates]
        scores = self.reranker.predict(pairs)

        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
        return [item[0] for item in ranked]

    async def _enrich_with_graph(self, products: List[dict]) -> List[dict]:
        """GraphRAG：获取商品的完整关联子图"""
        enriched = []
        for product in products:
            graph_data = await self._get_product_subgraph(product['id'])
            product['graph_context'] = graph_data
            enriched.append(product)
        return enriched

    async def _get_product_subgraph(self, product_id: str) -> dict:
        """获取商品的关联子图"""
        query = """
        MATCH (p:Product {product_id: $product_id})
        OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(pop:Population)
        OPTIONAL MATCH (p)-[:CONTRAINDICATED_FOR]->(contra:Population)
        OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
        OPTIONAL MATCH (p)-[:OFTEN_BOUGHT_WITH]->(related:Product)
        OPTIONAL MATCH (p)<-[:ANSWERS]-(faq:FAQ)

        RETURN
            collect(DISTINCT pop.name) as suitable_for,
            collect(DISTINCT {name: contra.name, reason: contra.reason}) as contraindicated_for,
            collect(DISTINCT scenario.name) as scenarios,
            collect(DISTINCT {
                id: related.product_id,
                name: related.name,
                price: related.price
            })[0..3] as related_products,
            collect(DISTINCT {
                question: faq.question,
                answer: faq.answer
            })[0..3] as faqs
        """
        result = await self.neo4j.query(query, product_id=product_id)
        return result[0] if result else {}
```

---

## 4.4 Reply Sub-Agent

### Tool定义

```json
{
  "name": "output_reply",
  "description": "输出客服回复",
  "input_schema": {
    "type": "object",
    "properties": {
      "reply_text": {
        "type": "string",
        "maxLength": 150
      },
      "confidence": {"type": "number"},
      "products_mentioned": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_id": {"type": "string"},
            "name": {"type": "string"},
            "relevance": {"type": "string"}
          }
        }
      },
      "upsell_suggestions": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_id": {"type": "string"},
            "name": {"type": "string"},
            "price": {"type": "number"},
            "reason": {"type": "string"}
          }
        },
        "maxItems": 2
      },
      "requires_human_review": {"type": "boolean"},
      "review_reason": {"type": "string"}
    },
    "required": ["reply_text", "confidence"]
  }
}
```

### Prompt模板

```
# 角色定义
你是美团医疗器械店铺的专业客服。

# 任务
基于检索到的商品信息，生成专业、友好的回复。

# 用户问题
{user_message}

# 识别的意图
{intent}

# 检索到的商品信息（含完整关联图谱）
{retrieved_products_with_graph}

# 回复原则

## 1. 准确性（最重要）
- 只使用检索到的信息，不编造
- 医疗器械相关问题要谨慎
- 不确定时说"建议咨询医生"或"您可以查看商品详情"

## 2. 专业性
- 使用正确的产品术语
- 禁止说"可以治疗XXX"、"保证有效"
- 涉及适用人群时，主动提示禁忌人群

## 3. 简洁性
- 控制在100字以内
- 直接回答问题，不啰嗦

## 4. 友好性
- 以"亲"或"您好"开头
- 使用1-2个emoji
- 语气亲切但专业

## 5. 引导性
- 适时推荐关联商品（从related_products中选）
- 以"需要帮您下单吗？"或"还有其他问题吗？"结尾

# 禁止事项
❌ "可以治疗XXX"
❌ "保证有效"、"100%"
❌ 编造商品不存在的功能
❌ 说竞品坏话
❌ 透露进货成本

# 回复模板参考

## 商品咨询
"亲，这款{商品名}是{核心功能}，{关键参数}。{适用人群说明}。需要帮您下单吗？😊"

## 推荐场景
"亲，根据您的需求，推荐这款{商品名}，{推荐理由}。{价格说明}，很多顾客反馈不错呢~"

## 使用方法
"亲，这款{商品名}使用很简单：{使用步骤}。{注意事项}。还有其他问题吗？"

# 追销逻辑
如果检索结果包含related_products，选择1-2个推荐：
- 价格适中的优先
- 与用户需求相关的优先
- 自然融入回复，不生硬

# 输出
使用 output_reply 工具输出结果
```

---

## 4.5 FAQ快捷回复模板

对于logistics、greeting等简单意图，直接使用模板：

```yaml
faq_templates:
  greeting:
    - trigger: ["在吗", "你好", "hello", "hi"]
      reply: "亲，在的呢~请问有什么可以帮您？😊"

  logistics:
    - trigger: ["多久能到", "什么时候到", "几点送到"]
      reply: "亲，下单后预计{delivery_time}送达哦~具体以骑手实际配送为准。您可以在订单详情查看实时进度~"

    - trigger: ["发货了吗", "发了没"]
      reply: "亲，订单{order_status}。{status_detail}您可以在订单详情查看物流信息~"

    - trigger: ["能送到吗", "配送范围"]
      reply: "亲，我们支持3公里内配送~您下单时如果地址显示可配送就没问题的~"

  after_sales_notice:
    reply: "亲，售后问题这边帮您转接人工客服处理，请稍等~"
```

---
# 第五部分：Alert Agent 完整设计

## 5.1 增强检测架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Alert Agent 增强架构                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  定时触发（每5分钟）                                                         │
│      │                                                                       │
│      ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Anomaly Sub-Agent                                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │  Prophet    │  │  规则检测   │  │ Isolation   │                  │   │
│  │  │  时序预测   │  │  (价格/库存)│  │  Forest    │                  │   │
│  │  │  (销量异常) │  │             │  │  (多维异常) │                  │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                  │   │
│  │         └────────────────┴────────────────┘                          │   │
│  │                          │                                           │   │
│  │                   异常事件列表                                        │   │
│  └──────────────────────────┬───────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    RootCause Sub-Agent (Sonnet)                      │   │
│  │                    归因分析：竞品/库存/定价/外部/运营                  │   │
│  └──────────────────────────┬───────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Action Sub-Agent (Sonnet)                         │   │
│  │                    生成具体行动建议 + 预期效果                         │   │
│  └──────────────────────────┬───────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│                    企业微信通知 / 写入alerts表                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5.2 Prophet时序检测（替代Z-Score）

### 模型配置

```python
from prophet import Prophet
import pandas as pd
from datetime import datetime, timedelta

class ProphetAnomalyDetector:
    """基于Prophet的销量异常检测"""

    def __init__(self):
        self.models = {}  # product_id -> trained model
        self.min_training_days = 14  # 最少需要14天数据

    def train_model(self, product_id: str, sales_history: pd.DataFrame):
        """
        训练时序预测模型

        Args:
            product_id: 商品ID
            sales_history: DataFrame with columns ['ds', 'y']
                          ds: 日期 (datetime)
                          y: 销量 (int)
        """
        if len(sales_history) < self.min_training_days:
            return False

        model = Prophet(
            # 季节性配置
            yearly_seasonality=False,  # 医疗器械不需要年度季节性
            weekly_seasonality=True,   # 周末可能有差异
            daily_seasonality=False,

            # 节假日配置
            holidays=self._get_chinese_holidays(),

            # 置信区间
            interval_width=0.95,

            # 变化点检测
            changepoint_prior_scale=0.05,  # 默认0.05，越大越敏感

            # 增长模型
            growth='linear'
        )

        # 添加特殊事件回归器
        model.add_regressor('is_promotion')  # 促销日
        model.add_regressor('is_weather_event')  # 天气事件

        model.fit(sales_history)
        self.models[product_id] = model
        return True

    def detect(self, product_id: str, date: str, actual_sales: int,
               is_promotion: bool = False, is_weather_event: bool = False) -> dict:
        """
        检测某天销量是否异常

        Returns:
            {
                'is_anomaly': bool,
                'type': 'drop' | 'spike' | None,
                'severity': 'critical' | 'warning' | 'info',
                'expected': float,
                'actual': int,
                'lower_bound': float,
                'upper_bound': float,
                'deviation_percent': float
            }
        """
        model = self.models.get(product_id)
        if not model:
            return {'is_anomaly': False, 'reason': 'model_not_trained'}

        # 构建预测输入
        future = pd.DataFrame({
            'ds': [pd.to_datetime(date)],
            'is_promotion': [1 if is_promotion else 0],
            'is_weather_event': [1 if is_weather_event else 0]
        })

        # 预测
        forecast = model.predict(future)

        yhat = forecast['yhat'].iloc[0]
        yhat_lower = forecast['yhat_lower'].iloc[0]
        yhat_upper = forecast['yhat_upper'].iloc[0]

        # 异常判断
        result = {
            'expected': round(yhat, 1),
            'actual': actual_sales,
            'lower_bound': round(yhat_lower, 1),
            'upper_bound': round(yhat_upper, 1)
        }

        if actual_sales < yhat_lower:
            # 销量异常下降
            deviation = (yhat - actual_sales) / max(yhat, 1) * 100
            result.update({
                'is_anomaly': True,
                'type': 'drop',
                'severity': self._get_drop_severity(deviation, actual_sales),
                'deviation_percent': round(deviation, 1)
            })
        elif actual_sales > yhat_upper:
            # 销量异常上升（通常是好事，但需要关注库存）
            deviation = (actual_sales - yhat) / max(yhat, 1) * 100
            result.update({
                'is_anomaly': True,
                'type': 'spike',
                'severity': 'info',
                'deviation_percent': round(deviation, 1)
            })
        else:
            result['is_anomaly'] = False

        return result

    def _get_drop_severity(self, deviation_percent: float, actual: int) -> str:
        """判断下降严重程度"""
        if actual == 0:
            return 'critical'  # 零销量
        if deviation_percent > 70:
            return 'critical'
        if deviation_percent > 40:
            return 'warning'
        return 'info'

    def _get_chinese_holidays(self) -> pd.DataFrame:
        """中国节假日配置"""
        # 2026年节假日
        holidays = pd.DataFrame({
            'holiday': [
                'spring_festival', 'spring_festival', 'spring_festival',
                'qingming', 'labor_day', 'dragon_boat',
                'mid_autumn', 'national_day', 'national_day'
            ],
            'ds': pd.to_datetime([
                '2026-02-17', '2026-02-18', '2026-02-19',  # 春节
                '2026-04-05',  # 清明
                '2026-05-01',  # 劳动节
                '2026-05-31',  # 端午
                '2026-09-21',  # 中秋
                '2026-10-01', '2026-10-02'  # 国庆
            ]),
            'lower_window': [0, 0, 0, 0, 0, 0, 0, 0, 0],
            'upper_window': [1, 1, 1, 0, 2, 0, 0, 6, 6]
        })
        return holidays
```

---

## 5.3 完整异常检测规则

### Anomaly Sub-Agent Tool定义

```json
{
  "name": "output_anomalies",
  "description": "输出检测到的异常列表",
  "input_schema": {
    "type": "object",
    "properties": {
      "detection_summary": {
        "type": "object",
        "properties": {
          "total_products_checked": {"type": "integer"},
          "anomalies_found": {"type": "integer"},
          "critical_count": {"type": "integer"},
          "warning_count": {"type": "integer"}
        }
      },
      "anomalies": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "anomaly_id": {"type": "string"},
            "product_id": {"type": "string"},
            "product_name": {"type": "string"},
            "anomaly_type": {
              "enum": [
                "sales_drop_prophet", "sales_spike_prophet",
                "zero_sales", "consecutive_drop",
                "competitor_price_drop", "price_gap",
                "margin_warning", "margin_critical",
                "stockout_urgent", "stockout_warning", "overstock",
                "exposure_drop", "conversion_drop",
                "competitor_stockout_opportunity",
                "multi_factor"
              ]
            },
            "severity": {"enum": ["critical", "warning", "info"]},
            "detection_method": {"enum": ["prophet", "rule", "isolation_forest"]},
            "metrics": {
              "type": "object",
              "properties": {
                "expected_value": {"type": "number"},
                "actual_value": {"type": "number"},
                "deviation_percent": {"type": "number"},
                "threshold": {"type": "number"}
              }
            },
            "description": {"type": "string"},
            "detected_at": {"type": "string", "format": "date-time"}
          },
          "required": ["anomaly_id", "product_id", "anomaly_type", "severity", "description"]
        }
      }
    },
    "required": ["detection_summary", "anomalies"]
  }
}
```

### 检测规则配置

```yaml
anomaly_detection_rules:

  # ========== 销量异常（Prophet时序预测） ==========
  sales_prophet:
    enabled: true
    method: prophet
    config:
      interval_width: 0.95
      min_training_days: 14
    severity_mapping:
      drop:
        critical: "deviation > 70% OR actual = 0"
        warning: "deviation > 40%"
      spike:
        info: "any spike"  # 上涨通常是好事

  # ========== 连续下降（规则检测） ==========
  consecutive_drop:
    enabled: true
    method: rule
    config:
      days: 3
      threshold_percent: 50  # 连续3天低于均值50%
    severity: warning

  # ========== 零销量（规则检测） ==========
  zero_sales:
    enabled: true
    method: rule
    config:
      consecutive_days: 3
      min_historical_daily_sales: 1
    severity_mapping:
      3_days: warning
      5_days: critical
      7_days: critical  # 建议下架

  # ========== 竞品价格（规则检测） ==========
  competitor_price:
    enabled: true
    method: rule
    config:
      price_drop_threshold: 0.10  # 竞品降价>10%
      our_price_higher: true       # 且我们价格更高
    severity_mapping:
      single_competitor: warning
      multiple_competitors: critical
      drop_over_20_percent: critical

  # ========== 价格竞争力（规则检测） ==========
  price_gap:
    enabled: true
    method: rule
    config:
      gap_threshold: 0.15  # 我们价格高于竞品均价15%
    severity: warning

  # ========== 毛利异常（规则检测） ==========
  margin:
    enabled: true
    method: rule
    config:
      warning_threshold: 0.20   # 毛利率<20%
      critical_threshold: 0.10  # 毛利率<10%（亏损风险）
    severity_mapping:
      below_20: warning
      below_10: critical

  # ========== 库存异常（规则检测） ==========
  stockout:
    enabled: true
    method: rule
    config:
      urgent_days: 1
      warning_days: 3
      overstock_days: 90
    severity_mapping:
      urgent: critical   # <1天库存
      warning: warning   # <3天库存
      overstock: warning # >90天库存

  # ========== 流量异常（规则检测） ==========
  exposure:
    enabled: true
    method: rule
    config:
      drop_threshold: 0.50
      consecutive_days: 2
    severity: warning

  # ========== 转化异常（规则检测） ==========
  conversion:
    enabled: true
    method: rule
    config:
      drop_threshold: 0.50
    severity: warning

  # ========== 竞品缺货机会（规则检测） ==========
  competitor_stockout:
    enabled: true
    method: rule
    config:
      min_stockout_competitors: 2
    severity_mapping:
      2_competitors: warning
      3_or_more: critical  # 紧急补货机会

  # ========== 多因素叠加（聚合检测） ==========
  multi_factor:
    enabled: true
    method: aggregation
    config:
      min_anomaly_count: 3  # 同一商品3个以上异常
    severity: critical
    action: require_human
```

---

## 5.4 RootCause Sub-Agent

### Tool定义

```json
{
  "name": "output_root_causes",
  "description": "输出归因分析结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "product_id": {"type": "string"},
      "anomaly_type": {"type": "string"},
      "root_causes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "cause_type": {
              "enum": ["competitor", "inventory", "pricing", "external", "operation"]
            },
            "cause_detail": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "data_support": {
              "type": "object",
              "properties": {
                "metric": {"type": "string"},
                "before": {"type": "number"},
                "after": {"type": "number"},
                "change_percent": {"type": "number"}
              }
            }
          },
          "required": ["cause_type", "cause_detail", "confidence"]
        }
      },
      "primary_cause": {"type": "string"},
      "analysis_notes": {"type": "string"}
    },
    "required": ["product_id", "root_causes", "primary_cause"]
  }
}
```

### Prompt模板

```
# 角色定义
你是即时零售运营异常归因分析专家。

# 任务
分析异常事件的根本原因。

# 异常信息
商品ID：{product_id}
商品名：{product_name}
异常类型：{anomaly_type}
异常描述：{anomaly_description}
检测数据：{metrics}

# 相关数据

## 竞品数据（最近7天变化）
{competitor_data}

## 本店数据变化
{our_data_changes}

## 库存情况
{inventory_status}

## 定价变化
{pricing_history}

## 外部因素
{external_factors}  # 天气、节假日、平台活动

## 运营数据
{operation_metrics}  # 曝光、点击、转化

# 归因维度

| 维度 | 可能原因 | 关键证据 |
|------|----------|----------|
| 竞品因素 | 竞品降价、促销、缺货恢复、新竞品 | 竞品价格/销量变化 |
| 库存因素 | 缺货、库存不足、规格缺货 | 库存数据 |
| 定价因素 | 我方涨价、价格竞争力丧失 | 价格历史 |
| 外部因素 | 平台流量、天气、节假日 | 平台数据、天气 |
| 运营因素 | 曝光下降、排名变化、评价下降 | 运营指标 |

# 置信度判断

基于证据强度评估:
- 0.8-1.0: 有直接证据，时间高度吻合
- 0.6-0.8: 有相关证据，时间基本吻合
- 0.4-0.6: 有间接证据，可能相关
- <0.4: 猜测性判断

# 输出要求

1. 列出所有可能原因（按置信度排序）
2. 每个原因给出具体证据
3. 标注数据支撑（具体数值变化）
4. 明确主因（primary_cause）

# 输出
使用 output_root_causes 工具输出结果
```

---

## 5.5 Action Sub-Agent

### Tool定义

```json
{
  "name": "output_actions",
  "description": "输出行动建议",
  "input_schema": {
    "type": "object",
    "properties": {
      "product_id": {"type": "string"},
      "recommended_actions": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "action_type": {
              "enum": ["price_adjust", "promotion", "restock", "clearance", "delist", "optimize", "human_review"]
            },
            "priority": {"enum": ["P0", "P1", "P2", "P3"]},
            "action_detail": {"type": "string"},
            "parameters": {
              "type": "object",
              "properties": {
                "target_price": {"type": "number"},
                "discount_percent": {"type": "number"},
                "restock_quantity": {"type": "integer"},
                "promotion_duration_hours": {"type": "integer"}
              }
            },
            "expected_outcome": {"type": "string"},
            "estimated_impact": {
              "type": "object",
              "properties": {
                "sales_change_percent": {"type": "number"},
                "margin_change_percent": {"type": "number"},
                "investment_required": {"type": "number"}
              }
            },
            "deadline": {"type": "string"}
          },
          "required": ["action_type", "priority", "action_detail"]
        }
      },
      "monitoring": {
        "type": "object",
        "properties": {
          "metrics_to_watch": {"type": "array", "items": {"type": "string"}},
          "check_after_hours": {"type": "integer"},
          "success_criteria": {"type": "string"}
        }
      }
    },
    "required": ["product_id", "recommended_actions"]
  }
}
```

### Prompt模板

```
# 角色定义
你是即时零售运营策略专家，负责制定异常应对方案。

# 任务
基于异常和归因，给出具体可执行的行动建议。

# 异常信息
商品：{product_name}
异常类型：{anomaly_type}
严重程度：{severity}
主因分析：{primary_cause}

# 商品当前状态
当前价格：{current_price}
成本价：{cost_price}
当前库存：{stock}
日均销量：{avg_daily_sales}
竞品均价：{competitor_avg_price}

# 行动类型定义

| 类型 | 适用场景 | 参数 |
|------|----------|------|
| price_adjust | 价格竞争力不足 | target_price |
| promotion | 销量下滑、清库存 | discount_percent, duration |
| restock | 缺货/低库存 | quantity |
| clearance | 死库存 | discount_percent |
| delist | 持续亏损/无销量 | - |
| optimize | 曝光/转化问题 | 优化建议 |
| human_review | 复杂情况 | - |

# 优先级定义

| 级别 | 含义 | 响应时间 |
|------|------|----------|
| P0 | 正在亏损/紧急 | 立即 |
| P1 | 显著影响 | 4小时内 |
| P2 | 中等影响 | 24小时内 |
| P3 | 轻微影响 | 3天内 |

# 决策约束

1. 价格调整
   - 新价格 ≥ 成本 × 1.25（保证最低毛利25%）
   - 新价格 ≤ 竞品均价 × 1.05（保持竞争力）

2. 促销活动
   - 常规促销：8-9折，持续24-48小时
   - 清仓促销：5-7折，标注"清仓"

3. 补货建议
   - 安全库存 = 日均销量 × 7天
   - 建议补货量 = 安全库存 - 当前库存 + 预期增长

# 输出
使用 output_actions 工具输出结果
```

---
# 第六部分：Bundle Agent 完整设计

## 6.1 流程设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Bundle Agent 流程                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  触发: 每日23:00 / 手动触发                                                  │
│      │                                                                       │
│      ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    OrderMining Sub-Agent                             │   │
│  │                    FP-Growth关联规则挖掘                              │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Scene Sub-Agent (Sonnet)                          │   │
│  │                    场景理解 + 套餐命名 + 卖点提炼                      │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Pricing Sub-Agent                                 │   │
│  │                    定价策略 + 毛利保护                                │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│                    输出: 套餐建议（名称、组合、定价、卖点）                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6.2 OrderMining Sub-Agent

### 算法配置

```yaml
fp_growth_config:
  min_support: 0.01       # 最小支持度1%
  min_confidence: 0.30    # 最小置信度30%
  min_lift: 1.5           # 最小提升度1.5
  max_itemset_size: 4     # 最多4个商品组合
  min_order_count: 30     # 规则至少出现30次
```

### Tool定义

```json
{
  "name": "output_association_rules",
  "description": "输出关联规则挖掘结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "mining_summary": {
        "type": "object",
        "properties": {
          "total_orders_analyzed": {"type": "integer"},
          "rules_found": {"type": "integer"},
          "high_value_rules": {"type": "integer"}
        }
      },
      "rules": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "rule_id": {"type": "string"},
            "antecedent": {
              "type": "array",
              "items": {"type": "string"}
            },
            "consequent": {
              "type": "array",
              "items": {"type": "string"}
            },
            "support": {"type": "number"},
            "confidence": {"type": "number"},
            "lift": {"type": "number"},
            "order_count": {"type": "integer"},
            "potential_bundle_value": {"type": "number"}
          },
          "required": ["antecedent", "consequent", "support", "confidence", "lift"]
        }
      }
    },
    "required": ["mining_summary", "rules"]
  }
}
```

---

## 6.3 Scene Sub-Agent

### Tool定义

```json
{
  "name": "output_bundle_proposals",
  "description": "输出套餐提案",
  "input_schema": {
    "type": "object",
    "properties": {
      "bundles": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "bundle_id": {"type": "string"},
            "bundle_name": {"type": "string"},
            "tagline": {"type": "string"},
            "products": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "product_id": {"type": "string"},
                  "name": {"type": "string"},
                  "unit_price": {"type": "number"},
                  "role_in_bundle": {"type": "string"}
                }
              }
            },
            "target_scenario": {"type": "string"},
            "target_population": {"type": "string"},
            "value_proposition": {"type": "string"},
            "confidence_score": {"type": "number"},
            "recommendation_reason": {"type": "string"}
          },
          "required": ["bundle_name", "products", "target_scenario"]
        }
      }
    },
    "required": ["bundles"]
  }
}
```

### Prompt模板

```
# 角色定义
你是医疗器械套餐策划专家。

# 任务
基于关联规则，设计有吸引力的套餐组合。

# 输入数据

## 关联规则
{association_rules}

## 商品信息
{product_details}

# 场景模板

| 场景 | 典型组合 | 目标人群 |
|------|----------|----------|
| 感冒护理 | 体温计+口罩+酒精 | 家庭 |
| 外伤处理 | 创可贴+碘伏+纱布+棉签 | 家庭/户外 |
| 血糖管理 | 血糖仪+试纸+采血针+酒精棉 | 糖尿病患者 |
| 血压管理 | 血压计+记录本 | 高血压患者/老人 |
| 居家康复 | 轮椅+坐便器+护理垫 | 术后康复 |
| 婴儿护理 | 体温计+退热贴+棉签 | 新手父母 |

# 命名规则

格式选择：
1. [场景]套装：如"感冒护理套装"
2. [人群][场景]：如"家庭急救包"
3. [功能]组合：如"血糖监测全套"

要求：
- 4-8个字
- 突出价值感
- 避免过于医疗化的表述

# Tagline规则

格式：一句话卖点，10-15字
示例：
- "一站配齐，居家必备"
- "专业监测，关爱父母"
- "外出必备，有备无患"

# 输出
使用 output_bundle_proposals 工具输出结果
```

---

## 6.4 Pricing Sub-Agent

### Tool定义

```json
{
  "name": "output_bundle_pricing",
  "description": "输出套餐定价",
  "input_schema": {
    "type": "object",
    "properties": {
      "bundle_id": {"type": "string"},
      "pricing": {
        "type": "object",
        "properties": {
          "original_total": {"type": "number"},
          "bundle_price": {"type": "number"},
          "discount_percent": {"type": "number"},
          "savings_amount": {"type": "number"},
          "gross_margin_percent": {"type": "number"}
        }
      },
      "pricing_rationale": {"type": "string"},
      "approved": {"type": "boolean"},
      "rejection_reason": {"type": "string"}
    },
    "required": ["bundle_id", "pricing", "approved"]
  }
}
```

### 定价公式

```
套餐价 = 单品总价 × (1 - 折扣率)

折扣率 = 基础折扣 + 关联强度加成 + 毛利调整

基础折扣: 10%
关联强度加成: lift>2.0加5%, lift>3.0加8%
毛利调整: 确保套餐毛利≥25%

约束:
1. 套餐毛利 ≥ 25%
2. 折扣率 ≤ 20%
3. 价格尾数调整为.9或.8
```

---

# 第七部分：Listing Agent 完整设计

## 7.1 流程设计（支持1688+拼多多）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Listing Agent 流程                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  输入: 1688/拼多多商品链接                                                   │
│      │                                                                       │
│      ▼                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Parser Sub-Agent                                  │   │
│  │           解析商品信息（支持1688和拼多多两种格式）                     │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Matcher Sub-Agent                                 │   │
│  │                    匹配美团标品库（条形码/名称/特征）                   │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Filler Sub-Agent (Sonnet)                         │   │
│  │                    填充上架信息 + 标题SEO优化 + 定价建议               │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Compliance Sub-Agent                              │   │
│  │                    合规校验（医疗器械资质、禁售词、价格）              │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│                    输出: 可直接上架的商品信息 / 问题反馈                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7.2 Parser Sub-Agent

### Tool定义

```json
{
  "name": "output_parsed_product",
  "description": "输出解析后的商品信息",
  "input_schema": {
    "type": "object",
    "properties": {
      "source_platform": {"enum": ["alibaba", "pdd"]},
      "source_url": {"type": "string"},
      "parsed_data": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "brand": {"type": "string"},
          "barcode": {"type": "string"},
          "category": {"type": "string"},
          "specifications": {
            "type": "object",
            "additionalProperties": {"type": "string"}
          },
          "main_images": {"type": "array", "items": {"type": "string"}},
          "detail_images": {"type": "array", "items": {"type": "string"}},
          "price": {"type": "number"},
          "moq": {"type": "integer"},
          "weight_kg": {"type": "number"},
          "package_info": {"type": "string"}
        }
      },
      "cleaned_title": {"type": "string"},
      "parse_confidence": {"type": "number"}
    },
    "required": ["source_platform", "parsed_data", "cleaned_title"]
  }
}
```

### 标题清洗规则

```yaml
title_cleaning:
  remove_words:
    - "厂家直销"
    - "批发"
    - "爆款"
    - "热卖"
    - "新款"
    - "包邮"
    - "特价"
    - "促销"
    - "一件代发"

  keep_elements:
    - brand      # 品牌
    - model      # 型号
    - spec       # 规格
    - function   # 功能
    - material   # 材质
```

---

## 7.3 Filler Sub-Agent

### Tool定义

```json
{
  "name": "output_listing_info",
  "description": "输出上架信息",
  "input_schema": {
    "type": "object",
    "properties": {
      "optimized_title": {
        "type": "string",
        "maxLength": 30
      },
      "category_path": {"type": "string"},
      "suggested_price": {"type": "number"},
      "price_rationale": {"type": "string"},
      "selling_points": {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 5
      },
      "seo_keywords": {
        "type": "array",
        "items": {"type": "string"}
      },
      "specifications": {
        "type": "object",
        "additionalProperties": {"type": "string"}
      }
    },
    "required": ["optimized_title", "suggested_price", "selling_points"]
  }
}
```

### 标题优化规则

```
格式: {品类词} {品牌} {核心功能} {规格} {附加卖点}

长度: ≤30字

示例:
- 原标题: "欧姆龙家用电子血压计上臂式全自动智能语音播报老人用正品HEM-7121"
- 优化后: "欧姆龙血压计 上臂式智能语音 老人家用HEM-7121"
```

### 定价建议公式

```
建议售价 = MAX(
    成本 × 2.5,              # 保证毛利
    竞品均价 × 0.95,          # 保持竞争力
    美团同标品均价 × 0.98     # 平台对标
)

建议售价 = MIN(建议售价, 竞品最高价)  # 不超过最高价

尾数调整: 调整为.9或.8
```

---

## 7.4 Compliance Sub-Agent

### Tool定义

```json
{
  "name": "output_compliance_check",
  "description": "输出合规校验结果",
  "input_schema": {
    "type": "object",
    "properties": {
      "passed": {"type": "boolean"},
      "issues": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "rule_id": {"type": "string"},
            "severity": {"enum": ["fatal", "error", "warning", "info"]},
            "field": {"type": "string"},
            "issue": {"type": "string"},
            "suggestion": {"type": "string"}
          }
        }
      },
      "can_proceed": {"type": "boolean"},
      "requires_manual_review": {"type": "boolean"}
    },
    "required": ["passed", "issues", "can_proceed"]
  }
}
```

### 合规规则

```yaml
compliance_rules:

  # ========== 资质检查 ==========
  C1_medical_device_license:
    severity: fatal
    check: "医疗器械需要对应资质"
    action: block

  # ========== 禁售词 ==========
  C2_prohibited_words:
    severity: fatal
    words:
      - "处方"
      - "抗生素"
      - "激素"
      - "麻醉"
      - "毒品"
    action: block

  # ========== 虚假宣传 ==========
  C3_false_claims:
    severity: error
    words:
      - "治愈"
      - "根治"
      - "100%有效"
      - "无副作用"
      - "包治"
    action: force_modify

  # ========== 夸大宣传 ==========
  C4_exaggeration:
    severity: warning
    words:
      - "最好"
      - "第一"
      - "顶级"
      - "国际领先"
    action: suggest_modify

  # ========== 价格异常 ==========
  C5_price_anomaly:
    severity: warning
    check: "价格偏离市场均价>50%"
    action: require_confirm

  # ========== 图片检查 ==========
  C6_image_check:
    severity: info
    check: "主图数量<3张"
    action: suggest_add
```

---
# 第八部分：数据库设计

## 8.1 PostgreSQL Schema

### 核心业务表

```sql
-- 商品表
CREATE TABLE products (
    product_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    barcode VARCHAR(50),
    category VARCHAR(100),
    brand VARCHAR(100),
    cost_price DECIMAL(10,2),
    retail_price DECIMAL(10,2),
    stock INTEGER DEFAULT 0,
    monthly_sales INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',  -- active/inactive/delisted
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_barcode ON products(barcode);

-- 订单表
CREATE TABLE orders (
    order_id VARCHAR(50) PRIMARY KEY,
    platform VARCHAR(20) DEFAULT 'meituan',
    customer_phone_suffix VARCHAR(4),
    total_amount DECIMAL(10,2),
    status VARCHAR(20),
    order_time TIMESTAMP,
    delivery_address_type VARCHAR(20),  -- residential/office/hospital
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_orders_time ON orders(order_time);

-- 订单明细表
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) REFERENCES orders(order_id),
    product_id VARCHAR(32) REFERENCES products(product_id),
    quantity INTEGER,
    unit_price DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);

-- 竞品店铺表
CREATE TABLE competitor_stores (
    competitor_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200),
    platform VARCHAR(20) DEFAULT 'meituan',
    distance_km DECIMAL(3,2),
    rating DECIMAL(2,1),
    review_count INTEGER,
    threat_level VARCHAR(20),  -- high/medium/low
    last_crawl_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 竞品商品表
CREATE TABLE competitor_products (
    id SERIAL PRIMARY KEY,
    competitor_id VARCHAR(50) REFERENCES competitor_stores(competitor_id),
    product_name VARCHAR(200),
    barcode VARCHAR(50),
    price DECIMAL(10,2),
    monthly_sales INTEGER,
    is_stockout BOOLEAN DEFAULT FALSE,
    crawled_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_comp_products_competitor ON competitor_products(competitor_id);
CREATE INDEX idx_comp_products_barcode ON competitor_products(barcode);

-- 预警表
CREATE TABLE alerts (
    alert_id VARCHAR(50) PRIMARY KEY,
    product_id VARCHAR(32) REFERENCES products(product_id),
    alert_type VARCHAR(50),
    severity VARCHAR(20),  -- critical/warning/info
    detection_method VARCHAR(30),  -- prophet/rule/isolation_forest
    metrics JSONB,
    root_cause TEXT,
    recommended_action TEXT,
    status VARCHAR(20) DEFAULT 'pending',  -- pending/acknowledged/resolved/ignored
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE INDEX idx_alerts_product ON alerts(product_id);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_created ON alerts(created_at);

-- 选品运行记录表
CREATE TABLE selection_runs (
    run_id VARCHAR(50) PRIMARY KEY,
    trigger_type VARCHAR(20),  -- scheduled/manual/event
    trigger_params JSONB,
    status VARCHAR(20),  -- running/completed/failed
    recommendations JSONB,
    total_opportunities INTEGER,
    total_llm_tokens INTEGER,
    total_cost_usd DECIMAL(10,4),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 套餐表
CREATE TABLE bundles (
    bundle_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100),
    tagline VARCHAR(100),
    products JSONB,  -- [{product_id, name, unit_price, role}]
    original_price DECIMAL(10,2),
    bundle_price DECIMAL(10,2),
    discount_percent DECIMAL(4,2),
    confidence DECIMAL(3,2),
    lift DECIMAL(4,2),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 销量历史表（用于Prophet训练）
CREATE TABLE sales_history (
    id SERIAL PRIMARY KEY,
    product_id VARCHAR(32) REFERENCES products(product_id),
    sale_date DATE,
    quantity INTEGER,
    revenue DECIMAL(10,2),
    is_promotion BOOLEAN DEFAULT FALSE,
    is_weather_event BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sales_history_product_date ON sales_history(product_id, sale_date);

-- Prophet模型元数据表
CREATE TABLE prophet_models (
    product_id VARCHAR(32) PRIMARY KEY REFERENCES products(product_id),
    model_data BYTEA,  -- 序列化的模型
    training_samples INTEGER,
    last_trained_at TIMESTAMP,
    metrics JSONB,  -- {mape, rmse, coverage}
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 8.2 Neo4j Schema（含向量索引）

### 节点定义

```cypher
// 商品节点
CREATE CONSTRAINT product_id IF NOT EXISTS FOR (p:Product) REQUIRE p.product_id IS UNIQUE;

// 示例商品节点
CREATE (p:Product {
    product_id: 'P001',
    name: '欧姆龙电子血压计 HEM-7121',
    category: '血压计',
    brand: '欧姆龙',
    price: 299.00,
    description: '上臂式智能血压计，全自动测量，语音播报，适合家庭使用',
    embedding: [0.1, 0.2, ...]  // 1536维向量
})

// 人群节点
CREATE CONSTRAINT population_name IF NOT EXISTS FOR (pop:Population) REQUIRE pop.name IS UNIQUE;

// 场景节点
CREATE CONSTRAINT scenario_name IF NOT EXISTS FOR (s:Scenario) REQUIRE s.name IS UNIQUE;

// 症状节点
CREATE CONSTRAINT symptom_name IF NOT EXISTS FOR (sym:Symptom) REQUIRE sym.name IS UNIQUE;

// FAQ节点
CREATE (f:FAQ {
    question: '血压计怎么用',
    answer: '将袖带绑在上臂，按开始键即可自动测量...',
    question_embedding: [0.1, 0.2, ...]  // 1536维向量
})
```

### 向量索引

```cypher
// 商品描述向量索引（用于语义检索）
CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
FOR (p:Product) ON (p.embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }
}

// FAQ问题向量索引
CREATE VECTOR INDEX faq_embedding_index IF NOT EXISTS
FOR (f:FAQ) ON (f.question_embedding)
OPTIONS {
    indexConfig: {
        `vector.dimensions`: 1536,
        `vector.similarity_function`: 'cosine'
    }
}
```

### 关系定义

```cypher
// 适用人群
CREATE (p:Product)-[:SUITABLE_FOR {confidence: 0.9}]->(pop:Population)

// 禁忌人群（重要：带原因）
CREATE (p:Product)-[:CONTRAINDICATED_FOR {reason: '可能测量不准'}]->(pop:Population)

// 使用场景
CREATE (p:Product)-[:USED_IN]->(s:Scenario)

// 经常一起买
CREATE (p1:Product)-[:OFTEN_BOUGHT_WITH {
    support: 0.05,
    confidence: 0.35,
    lift: 2.1,
    order_count: 156
}]->(p2:Product)

// 可升级到
CREATE (p1:Product)-[:UPGRADE_TO {reason: '更精准'}]->(p2:Product)

// 可替代
CREATE (p1:Product)-[:ALTERNATIVE_TO {similarity: 0.85}]->(p2:Product)

// FAQ关联
CREATE (f:FAQ)-[:ANSWERS]->(p:Product)

// 症状关联
CREATE (p:Product)-[:HELPS_WITH]->(sym:Symptom)
```

### 初始化示例数据

```cypher
// 人群
CREATE (:Population {name: '老年人'})
CREATE (:Population {name: '高血压患者'})
CREATE (:Population {name: '糖尿病患者'})
CREATE (:Population {name: '孕妇'})
CREATE (:Population {name: '儿童'})
CREATE (:Population {name: '心律不齐患者'})

// 场景
CREATE (:Scenario {name: '日常血压监测'})
CREATE (:Scenario {name: '血糖管理'})
CREATE (:Scenario {name: '感冒护理'})
CREATE (:Scenario {name: '外伤处理'})
CREATE (:Scenario {name: '居家康复'})

// 商品与关系
MATCH (p:Product {product_id: 'P001'})
MATCH (pop1:Population {name: '老年人'})
MATCH (pop2:Population {name: '高血压患者'})
MATCH (pop3:Population {name: '心律不齐患者'})
MATCH (s:Scenario {name: '日常血压监测'})
CREATE (p)-[:SUITABLE_FOR {confidence: 0.95}]->(pop1)
CREATE (p)-[:SUITABLE_FOR {confidence: 0.95}]->(pop2)
CREATE (p)-[:CONTRAINDICATED_FOR {reason: '电子血压计对心律不齐患者测量可能不准，建议使用水银血压计'}]->(pop3)
CREATE (p)-[:USED_IN]->(s)
```

### GraphRAG查询

```cypher
// 获取商品完整上下文（用于客服回复）
MATCH (p:Product {product_id: $product_id})
OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(suitable:Population)
OPTIONAL MATCH (p)-[contra_rel:CONTRAINDICATED_FOR]->(contra:Population)
OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
OPTIONAL MATCH (p)-[bought:OFTEN_BOUGHT_WITH]->(related:Product)
OPTIONAL MATCH (faq:FAQ)-[:ANSWERS]->(p)

RETURN p.name AS product_name,
       p.description AS description,
       p.price AS price,
       collect(DISTINCT suitable.name) AS suitable_for,
       collect(DISTINCT {
           population: contra.name,
           reason: contra_rel.reason
       }) AS contraindicated_for,
       collect(DISTINCT scenario.name) AS scenarios,
       collect(DISTINCT {
           product_id: related.product_id,
           name: related.name,
           price: related.price,
           confidence: bought.confidence
       })[0..3] AS related_products,
       collect(DISTINCT {
           question: faq.question,
           answer: faq.answer
       })[0..5] AS faqs
```

---

## 8.3 Redis缓存设计

```yaml
redis_keys:

  # 热搜词缓存（1小时TTL）
  market:hot_keywords:
    type: string (JSON)
    ttl: 3600
    content: "[{keyword, heat_score, trend}, ...]"

  # 竞品数据缓存（30分钟TTL）
  competitor:{competitor_id}:products:
    type: string (JSON)
    ttl: 1800
    content: "[{product_name, price, is_stockout}, ...]"

  # 商品信息缓存（5分钟TTL）
  product:{product_id}:
    type: hash
    ttl: 300
    fields: name, price, stock, description

  # 图谱查询缓存（10分钟TTL）
  graph:product:{product_id}:context:
    type: string (JSON)
    ttl: 600
    content: "{suitable_for, contraindicated_for, related_products, ...}"

  # 客服会话缓存（30分钟TTL）
  session:{session_id}:
    type: hash
    ttl: 1800
    fields: user_id, conversation_history, last_intent, mentioned_products

  # Prophet预测缓存（1小时TTL）
  prophet:{product_id}:forecast:
    type: string (JSON)
    ttl: 3600
    content: "{yhat, yhat_lower, yhat_upper}"
```

---
# 第九部分：MCP Skills Layer

## 9.1 Skills 总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP Skills Layer                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                │
│  │  ActionBook    │  │    Neo4j       │  │   Database     │                │
│  │    Skill       │  │    Skill       │  │    Skill       │                │
│  │                │  │                │  │                │                │
│  │ • 美团数据采集 │  │ • 图谱查询     │  │ • 商品CRUD     │                │
│  │ • 1688商品解析 │  │ • 向量检索     │  │ • 订单查询     │                │
│  │ • 拼多多解析   │  │ • GraphRAG     │  │ • 统计分析     │                │
│  │ • 竞品监控     │  │ • 关系遍历     │  │ • Prophet数据  │                │
│  └────────────────┘  └────────────────┘  └────────────────┘                │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                │
│  │   Embedding    │  │   Reranker     │  │   Prophet      │                │
│  │    Skill       │  │    Skill       │  │    Skill       │                │
│  │                │  │                │  │                │                │
│  │ • 文本向量化   │  │ • BGE精排序    │  │ • 模型训练     │                │
│  │ • 批量Embed    │  │ • 相关性打分   │  │ • 异常检测     │                │
│  └────────────────┘  └────────────────┘  └────────────────┘                │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐                                    │
│  │   Notifier     │  │   Calculator   │                                    │
│  │    Skill       │  │    Skill       │                                    │
│  │                │  │                │                                    │
│  │ • 企业微信推送 │  │ • 评分计算     │                                    │
│  │ • 预警通知     │  │ • 毛利计算     │                                    │
│  │ • 报告发送     │  │ • 统计分析     │                                    │
│  └────────────────┘  └────────────────┘                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9.2 ActionBook Skill（含拼多多）

### 方法清单

| 方法名 | 平台 | 用途 | 频率限制 |
|--------|------|------|----------|
| meituan_keywords | 美团 | 热搜词 | 10/小时 |
| meituan_rankings | 美团 | 商品排行 | 10/小时 |
| competitor_stores | 美团 | 竞品店铺 | 20/小时 |
| competitor_products | 美团 | 竞品商品 | 50/小时 |
| alibaba_search | 1688 | 商品搜索 | 100/小时 |
| alibaba_detail | 1688 | 商品详情 | 100/小时 |
| alibaba_supplier | 1688 | 供应商信息 | 50/小时 |
| pdd_search | 拼多多 | 商品搜索 | 100/小时 |
| pdd_detail | 拼多多 | 商品详情 | 100/小时 |
| pdd_shop | 拼多多 | 店铺信息 | 50/小时 |

### 接口定义

```python
class ActionBookSkill:
    """ActionBook RPA采集技能"""

    async def meituan_keywords(
        self,
        store_id: str,
        category: str = None,
        limit: int = 50
    ) -> List[dict]:
        """获取美团热搜词"""
        pass

    async def competitor_stores(
        self,
        store_id: str,
        radius_km: float = 3.0
    ) -> List[dict]:
        """获取周边竞品店铺"""
        pass

    async def alibaba_search(
        self,
        keyword: str,
        sort_by: str = 'sales',  # sales/price/credit
        limit: int = 10
    ) -> List[dict]:
        """搜索1688商品"""
        pass

    async def pdd_search(
        self,
        keyword: str,
        sort_by: str = 'sales',  # sales/price
        limit: int = 10
    ) -> List[dict]:
        """搜索拼多多商品"""
        pass

    async def pdd_detail(
        self,
        url: str
    ) -> dict:
        """获取拼多多商品详情"""
        pass
```

### 输出格式

```python
# pdd_search输出
{
    "title": "鱼跃电子血压计",
    "price": 89.9,
    "original_price": 129.0,
    "sales_count": 10000,
    "shop_name": "鱼跃医疗旗舰店",
    "shop_score": 4.9,
    "url": "https://...",
    "images": ["https://..."],
    "has_coupon": True,
    "coupon_amount": 10
}
```

---

## 9.3 Neo4j Skill（含向量检索）

### 方法清单

| 方法名 | 用途 |
|--------|------|
| vector_search | 向量语义检索 |
| keyword_search | 关键词检索 |
| hybrid_search | 混合检索（向量+关键词+RRF） |
| get_product_graph | GraphRAG获取商品子图 |
| get_suitable_population | 获取适用人群 |
| get_related_products | 获取关联商品 |
| add_product | 添加商品节点 |
| add_relationship | 添加关系 |
| update_embedding | 更新向量 |

### 接口定义

```python
class Neo4jSkill:
    """Neo4j图谱+向量检索技能"""

    async def vector_search(
        self,
        query_embedding: List[float],
        index_name: str = 'product_embedding_index',
        limit: int = 10
    ) -> List[dict]:
        """向量语义检索"""
        query = """
        CALL db.index.vector.queryNodes($index_name, $limit, $embedding)
        YIELD node, score
        RETURN node.product_id as id, node.name as name,
               node.description as description, score
        """
        return await self.execute(query,
            index_name=index_name,
            embedding=query_embedding,
            limit=limit
        )

    async def hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        keywords: List[str],
        limit: int = 10
    ) -> List[dict]:
        """混合检索：向量+关键词+RRF融合"""
        # 1. 向量检索
        vector_results = await self.vector_search(query_embedding, limit=30)

        # 2. 关键词检索
        keyword_results = await self.keyword_search(keywords, limit=30)

        # 3. RRF融合
        merged = self._rrf_merge(vector_results, keyword_results)

        return merged[:limit]

    async def get_product_graph(
        self,
        product_id: str
    ) -> dict:
        """GraphRAG：获取商品完整关联子图"""
        query = """
        MATCH (p:Product {product_id: $product_id})
        OPTIONAL MATCH (p)-[:SUITABLE_FOR]->(suitable:Population)
        OPTIONAL MATCH (p)-[contra_rel:CONTRAINDICATED_FOR]->(contra:Population)
        OPTIONAL MATCH (p)-[:USED_IN]->(scenario:Scenario)
        OPTIONAL MATCH (p)-[bought:OFTEN_BOUGHT_WITH]->(related:Product)
        OPTIONAL MATCH (faq:FAQ)-[:ANSWERS]->(p)

        RETURN p AS product,
               collect(DISTINCT suitable.name) AS suitable_for,
               collect(DISTINCT {name: contra.name, reason: contra_rel.reason}) AS contraindicated_for,
               collect(DISTINCT scenario.name) AS scenarios,
               collect(DISTINCT {id: related.product_id, name: related.name, price: related.price})[0..3] AS related_products,
               collect(DISTINCT {question: faq.question, answer: faq.answer})[0..5] AS faqs
        """
        return await self.execute_single(query, product_id=product_id)
```

---

## 9.4 Embedding Skill

```python
class EmbeddingSkill:
    """文本向量化技能"""

    def __init__(self, model_name: str = 'BAAI/bge-large-zh-v1.5'):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def embed(self, text: str) -> List[float]:
        """单条文本向量化"""
        embedding = self.model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量文本向量化"""
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()
```

---

## 9.5 Reranker Skill

```python
class RerankerSkill:
    """BGE Reranker精排技能"""

    def __init__(self, model_name: str = 'BAAI/bge-reranker-v2-m3'):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        documents: List[dict],
        text_field: str = 'description',
        top_k: int = 5
    ) -> List[dict]:
        """对候选文档重排序"""
        pairs = [[query, doc.get(text_field, '')] for doc in documents]
        scores = self.model.predict(pairs)

        ranked = sorted(zip(documents, scores), key=lambda x: -x[1])
        return [item[0] for item in ranked[:top_k]]
```

---

## 9.6 Prophet Skill

```python
class ProphetSkill:
    """Prophet时序预测技能"""

    async def train_model(
        self,
        product_id: str,
        sales_data: pd.DataFrame
    ) -> dict:
        """训练Prophet模型"""
        model = Prophet(
            yearly_seasonality=False,
            weekly_seasonality=True,
            holidays=self._get_holidays(),
            interval_width=0.95
        )
        model.fit(sales_data)

        # 序列化保存
        await self._save_model(product_id, model)

        return {"status": "trained", "samples": len(sales_data)}

    async def detect_anomaly(
        self,
        product_id: str,
        date: str,
        actual_sales: int
    ) -> dict:
        """检测销量异常"""
        model = await self._load_model(product_id)
        if not model:
            return {"is_anomaly": False, "reason": "no_model"}

        forecast = model.predict(pd.DataFrame({'ds': [date]}))

        yhat = forecast['yhat'].iloc[0]
        lower = forecast['yhat_lower'].iloc[0]
        upper = forecast['yhat_upper'].iloc[0]

        if actual_sales < lower:
            return {
                "is_anomaly": True,
                "type": "drop",
                "expected": yhat,
                "actual": actual_sales,
                "bounds": [lower, upper]
            }
        elif actual_sales > upper:
            return {
                "is_anomaly": True,
                "type": "spike",
                "expected": yhat,
                "actual": actual_sales,
                "bounds": [lower, upper]
            }

        return {"is_anomaly": False}
```

---

## 9.7 Notifier Skill

```python
class NotifierSkill:
    """企业微信通知技能"""

    async def send_alert(
        self,
        severity: str,
        title: str,
        product_name: str,
        description: str,
        root_cause: str,
        action: str
    ):
        """发送预警通知"""
        emoji = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}

        message = f"""
{emoji.get(severity, '')} 【{severity.upper()}预警】{title}

📦 商品: {product_name}
📊 异常: {description}
🔍 原因: {root_cause}
💡 建议: {action}

⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """

        await self._send_wechat_work(message)

    async def send_daily_report(
        self,
        date: str,
        metrics: dict,
        top_recommendations: List[dict]
    ):
        """发送每日选品报告"""
        pass
```

---
# 第十部分：参数配置

## 10.1 评分模型参数

```yaml
# config/scoring.yaml

selection_scoring:
  # 权重配置
  weights:
    market_heat: 0.25      # 市场热度
    competition_gap: 0.20  # 竞争空位
    supply_chain: 0.20     # 供应链
    profit_margin: 0.20    # 利润空间
    category_synergy: 0.10 # 品类协同
    seasonal_fit: 0.05     # 季节契合

  # 权重可调范围
  weight_ranges:
    market_heat: [0.15, 0.35]
    competition_gap: [0.10, 0.30]
    supply_chain: [0.10, 0.30]
    profit_margin: [0.15, 0.30]
    category_synergy: [0.05, 0.20]
    seasonal_fit: [0.00, 0.15]

  # 推荐阈值
  thresholds:
    strong_recommend: 80   # ≥80 强烈推荐
    recommend: 70          # 70-80 推荐
    optional: 60           # 60-70 可选
    not_recommend: 60      # <60 不推荐

heat_score:
  # 搜索量归一化阈值
  volume_thresholds: [1000, 5000, 10000, 50000]
  volume_scores: [0.2, 0.4, 0.6, 0.8, 1.0]

  # 增长率上限
  growth_cap: 0.5

  # 转化率基准
  conversion_baseline: 0.1

supplier_scoring:
  alibaba:
    weights:
      qualification: 0.30
      price: 0.30
      moq: 0.20
      delivery: 0.20
  pdd:
    weights:
      price: 0.40
      shop_score: 0.25
      sales: 0.20
      delivery: 0.15

margin:
  # 毛利率评级
  excellent_threshold: 0.50
  good_threshold: 0.40
  fair_threshold: 0.30
  minimum_threshold: 0.25  # 低于此值不推荐

  # 成本倍率
  cost_multiplier: 2.5
```

---

## 10.2 异常检测参数

```yaml
# config/anomaly.yaml

prophet:
  # 置信区间
  interval_width: 0.95

  # 最小训练样本
  min_training_days: 14

  # 季节性配置
  yearly_seasonality: false
  weekly_seasonality: true
  daily_seasonality: false

  # 变化点灵敏度
  changepoint_prior_scale: 0.05

sales_anomaly:
  # 严重程度判定
  severity:
    critical_deviation: 70  # 偏离>70%为critical
    warning_deviation: 40   # 偏离>40%为warning
    zero_sales_is_critical: true

consecutive_drop:
  days: 3
  threshold_percent: 50

zero_sales:
  consecutive_days: 3
  min_historical_sales: 1
  severity_mapping:
    3: warning
    5: critical
    7: critical  # 建议下架

competitor_price:
  drop_threshold: 0.10
  urgency_threshold: 0.20
  multiple_competitor_threshold: 2

price_gap:
  threshold: 0.15

margin_warning:
  warning_threshold: 0.20
  critical_threshold: 0.10

stockout:
  urgent_days: 1
  warning_days: 3
  overstock_days: 90

exposure_drop:
  threshold: 0.50
  consecutive_days: 2

conversion_drop:
  threshold: 0.50
```

---

## 10.3 客服参数

```yaml
# config/customer_service.yaml

intent:
  # 模型选择
  model: claude-haiku  # 意图识别用Haiku降本

  # 置信度阈值
  high_confidence: 0.9
  low_confidence: 0.7

  # 转人工触发词
  human_handoff_keywords:
    - 投诉
    - 举报
    - 315
    - 消协
    - 退款
    - 赔偿
    - 律师
    - 起诉
    - 骗子
    - 假货

retrieval:
  # Hybrid Search配置
  vector_weight: 0.6
  keyword_weight: 0.4

  # 召回数量
  initial_recall: 50
  after_rerank: 5

  # RRF参数
  rrf_k: 60

reply:
  # 回复长度限制
  max_length: 150

  # 追销配置
  max_upsell_products: 2

  # 模型选择
  model: claude-sonnet-4-20250514
```

---

## 10.4 系统参数

```yaml
# config/system.yaml

llm:
  models:
    simple: claude-haiku           # 简单任务
    default: claude-sonnet-4-20250514   # 常规任务
    complex: claude-opus-4-20250514      # 复杂决策

  temperature: 0  # 确定性输出
  max_tokens: 4096
  max_retries: 3
  retry_delay: [1, 2, 4]  # 指数退避

concurrency:
  data_collection: 4       # 数据采集并发
  supplier_query: 3        # 1688/拼多多查询并发
  db_connection_pool: 20   # 数据库连接池
  redis_connection_pool: 10

cache:
  hot_keywords_ttl: 3600      # 1小时
  competitor_data_ttl: 1800   # 30分钟
  product_info_ttl: 300       # 5分钟
  graph_query_ttl: 600        # 10分钟
  prophet_forecast_ttl: 3600  # 1小时

scheduled_tasks:
  daily_selection: "0 6 * * *"      # 每日6点选品
  competitor_crawl_am: "0 8 * * *"  # 上午8点采集
  competitor_crawl_pm: "0 14 * * *" # 下午2点采集
  alert_scan: "*/5 * * * *"         # 每5分钟扫描
  bundle_mining: "0 23 * * *"       # 每日23点套餐挖掘
  daily_report: "0 22 * * *"        # 每日22点日报
  prophet_retrain: "0 3 * * 0"      # 每周日3点重训练
```

---

# 第十一部分：部署与监控

## 11.1 部署架构

```yaml
# docker-compose.prod.yaml

services:
  api:
    image: ai-store-manager:latest
    replicas: 3
    resources:
      limits:
        cpus: '4'
        memory: 8G
    environment:
      - ENV=production
      - DATABASE_URL=postgresql://...
      - NEO4J_URI=bolt://neo4j:7687
      - REDIS_URL=redis://redis:6379
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  worker:
    image: ai-store-manager:latest
    command: celery -A app.worker worker
    replicas: 2
    resources:
      limits:
        cpus: '4'
        memory: 16G

  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=ai_store
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}

  neo4j:
    image: neo4j:5-enterprise
    volumes:
      - neo4j_data:/data
    environment:
      - NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  langfuse:
    image: langfuse/langfuse:latest
    environment:
      - DATABASE_URL=postgresql://...
```

---

## 11.2 监控配置

```yaml
# Langfuse追踪配置
langfuse:
  enabled: true
  trace_sample_rate: 1.0  # 100%追踪

  # 追踪维度
  trace_metadata:
    - agent_name
    - sub_agent_name
    - model_used
    - input_tokens
    - output_tokens
    - latency_ms
    - status

# Prometheus指标
prometheus:
  metrics:
    - name: agent_execution_duration_seconds
      type: histogram
      labels: [agent, sub_agent, status]

    - name: llm_tokens_total
      type: counter
      labels: [model, agent]

    - name: llm_cost_usd_total
      type: counter
      labels: [model]

    - name: alerts_triggered_total
      type: counter
      labels: [type, severity]

    - name: customer_service_messages_total
      type: counter
      labels: [intent, handled_by]

# 告警规则
alerting:
  rules:
    - name: API高延迟
      condition: api_latency_p99 > 5s for 5m
      severity: warning
      notify: wechat_work

    - name: LLM成本异常
      condition: daily_llm_cost > $50
      severity: warning
      notify: wechat_work

    - name: 选品任务失败
      condition: selection_run_failed
      severity: critical
      notify: wechat_work
```

---

# 第十二部分：开发计划

## 12.1 开发阶段（总计16周）

| 阶段 | 周数 | 内容 | 交付物 |
|------|------|------|--------|
| Phase 1 | 2周 | 核心框架 | 项目骨架、数据库、Neo4j图谱 |
| Phase 2 | 3周 | Selection Agent | 6个Sub-Agent + Tool Use |
| Phase 3 | 2周 | CustomerService Agent | Hybrid Search + GraphRAG + Reranker |
| Phase 4 | 2周 | Alert Agent | Prophet时序检测 + 规则引擎 |
| Phase 5 | 2周 | Bundle + Listing | 套餐挖掘 + 双渠道上架 |
| Phase 6 | 1周 | Orchestrator + API | 路由 + FastAPI |
| Phase 7 | 1周 | 可观测性 | Langfuse + Prometheus + Grafana |
| Phase 8 | 2周 | 集成测试 + UAT | 端到端测试 + 用户验收 |
| Phase 9 | 1周 | 部署上线 | 生产环境部署 |

## 12.2 技术增强集成时间线

### 第一阶段：开发时同步完成（全部技术）

| 技术 | 集成阶段 | 优先级 | 依赖条件 |
|------|----------|--------|----------|
| Tool Use | Phase 1-6 | P0 | 无 |
| Neo4j向量索引 | Phase 1 | P0 | 无 |
| Embedding Skill | Phase 1 | P0 | 无 |
| Prophet时序检测 | Phase 4 | P0 | 14天历史数据 |
| Hybrid Search | Phase 3 | P0 | 向量索引就绪 |
| GraphRAG | Phase 3 | P0 | 图谱数据 |
| Reranker | Phase 3 | P0 | 加载BGE模型 |
| Self-Reflection | Phase 2 | P0 | 无 |

**说明**：以上技术均不依赖运营数据积累，开发阶段直接集成。

### 第二阶段：运营1-2个月后

| 技术 | 需要的数据 | 数据量要求 |
|------|------------|------------|
| XGBoost评分模型 | 选品效果反馈 | 300-500条推荐记录 |
| LLM自动构建图谱 | 客服对话记录 | 1000+轮对话 |
| Contextual Bandit | 用户点击反馈 | 5000+次曝光（可选） |

## 12.3 团队配置

| 角色 | 人数 | 职责 |
|------|------|------|
| Tech Lead | 1 | 架构设计、LangGraph、LLM工程 |
| 后端工程师 | 2 | FastAPI、数据库、Skills |
| AI工程师 | 1 | Prompt工程、向量检索、Prophet |
| 前端工程师 | 1 | 管理后台 |
| 运维 | 0.5 | 部署、监控 |

## 12.4 验收标准

| 功能 | 验收标准 |
|------|----------|
| 选品 | 每日6点自动运行，输出TOP20，评分明细完整 |
| 客服 | 80%问题自动回复，响应<10秒，准确率>90% |
| 预警 | Prophet检测准确率>70%，误报率<30% |
| 套餐 | 自动生成套餐，置信度>0.3，lift>1.5 |
| 上架 | 2分钟内完成解析+定价+合规校验 |

## 12.5 成本预估

| 项目 | 月成本 |
|------|--------|
| LLM调用 | $40-50/店铺 |
| 服务器 | $200-300 |
| Neo4j Enterprise | $0（社区版） |
| Langfuse | $0（自部署） |
| **总计** | **$250-350/月 + $40-50/店铺** |

---

# 附录：技术增强对照表

| 原方案 | 增强方案 | 效果提升 |
|--------|----------|----------|
| JSON输出 | Tool Use | 可靠性100% |
| Z-Score检测 | Prophet时序 | 准确率+30%，误报-50% |
| 关键词检索 | Hybrid Search | 召回率+30% |
| 单节点返回 | GraphRAG子图 | 回答质量+25% |
| 无精排 | BGE Reranker | 排序准确+20% |
| 单次输出 | Self-Reflection | 决策准确+15% |
| 仅1688 | 1688+拼多多 | 供应链覆盖+50% |

---
# 参数自学习系统设计

## 一、核心思路

```
运营反馈 → 效果标注 → 模型学习 → 参数更新 → 持续迭代
```

---

## 二、反馈信号定义

### 选品效果标注

| 反馈类型 | 数据来源 | 标注值 |
|----------|----------|--------|
| 是否采购 | 采购记录 | 0/1 |
| 采购后30天销量 | 销售数据 | 数值 |
| 采购后毛利率 | 财务数据 | 数值 |
| 是否滞销 | 库存数据 | 0/1 |

### 综合效果评分

```python
def calculate_selection_outcome(product_id: str, days: int = 30) -> float:
    """
    计算选品效果得分 (0-1)
    """
    # 是否采购
    purchased = get_purchase_status(product_id)
    if not purchased:
        return 0.0

    # 销量表现 (vs 预期)
    actual_sales = get_sales(product_id, days)
    expected_sales = get_expected_sales(product_id)
    sales_ratio = min(actual_sales / max(expected_sales, 1), 2.0) / 2.0  # 0-1

    # 毛利表现
    margin = get_margin(product_id)
    margin_score = min(margin / 0.5, 1.0)  # 50%毛利得1分

    # 是否滞销
    is_slow = is_slow_moving(product_id)
    slow_penalty = 0.5 if is_slow else 1.0

    # 综合得分
    outcome = (sales_ratio * 0.4 + margin_score * 0.4 + 0.2) * slow_penalty
    return outcome
```

---

## 三、方案一：Learning to Rank（推荐）

### 原理
用历史选品效果训练排序模型，自动学习最优特征权重

### 实现

```python
import xgboost as xgb
from sklearn.model_selection import train_test_split

class SelectionRanker:
    """选品排序模型 - 自动学习权重"""

    def __init__(self):
        self.model = None
        self.feature_names = [
            'market_heat',
            'competition_gap',
            'supply_chain',
            'profit_margin',
            'category_synergy',
            'seasonal_fit'
        ]

    def prepare_training_data(self, days: int = 60) -> tuple:
        """
        准备训练数据
        """
        # 获取历史推荐记录
        recommendations = get_historical_recommendations(days)

        X = []  # 特征
        y = []  # 效果得分

        for rec in recommendations:
            features = [
                rec['market_heat_score'],
                rec['competition_gap_score'],
                rec['supply_chain_score'],
                rec['profit_margin_score'],
                rec['category_synergy_score'],
                rec['seasonal_fit_score']
            ]
            outcome = calculate_selection_outcome(rec['product_id'])

            X.append(features)
            y.append(outcome)

        return np.array(X), np.array(y)

    def train(self):
        """训练模型"""
        X, y = self.prepare_training_data()

        if len(X) < 100:
            print("样本不足100条，暂不训练")
            return False

        X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2)

        self.model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            objective='reg:squarederror'
        )

        self.model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            early_stopping_rounds=10,
            verbose=False
        )

        # 输出学到的特征重要性（即权重）
        importances = self.model.feature_importances_
        learned_weights = dict(zip(self.feature_names, importances))

        print("学到的权重:", learned_weights)
        return learned_weights

    def predict(self, features: dict) -> float:
        """预测选品得分"""
        if self.model is None:
            # 模型未训练，使用默认权重
            return self._default_score(features)

        X = [[features[name] for name in self.feature_names]]
        return self.model.predict(X)[0]

    def get_learned_weights(self) -> dict:
        """获取学到的权重（归一化）"""
        if self.model is None:
            return None

        importances = self.model.feature_importances_
        total = sum(importances)
        normalized = {name: imp/total for name, imp in zip(self.feature_names, importances)}
        return normalized
```

### 权重更新流程

```python
# 每周日凌晨执行
async def weekly_model_update():
    ranker = SelectionRanker()

    # 训练模型
    learned_weights = ranker.train()

    if learned_weights:
        # 保存学到的权重
        await save_learned_weights(learned_weights)

        # 与当前权重对比
        current_weights = await get_current_weights()

        # 生成调整建议
        suggestions = generate_weight_suggestions(current_weights, learned_weights)

        # 通知运营审核
        await notify_weight_update(suggestions)
```

---

## 四、方案二：贝叶斯优化（自动调参）

### 原理
在权重可调范围内搜索最优参数组合

### 实现

```python
from bayes_opt import BayesianOptimization

class WeightOptimizer:
    """贝叶斯优化自动调参"""

    def __init__(self):
        # 权重搜索范围
        self.pbounds = {
            'market_heat': (0.15, 0.35),
            'competition_gap': (0.10, 0.30),
            'supply_chain': (0.10, 0.30),
            'profit_margin': (0.15, 0.30),
            'category_synergy': (0.05, 0.20),
            'seasonal_fit': (0.00, 0.15)
        }

    def objective(self, **weights) -> float:
        """
        目标函数：评估一组权重的效果
        使用历史数据回测
        """
        # 归一化权重
        total = sum(weights.values())
        normalized = {k: v/total for k, v in weights.items()}

        # 用这组权重重新计算历史推荐的得分
        historical_recs = get_historical_recommendations(days=30)

        total_outcome = 0
        for rec in historical_recs:
            # 用新权重计算得分
            new_score = sum(
                normalized[dim] * rec[f'{dim}_score']
                for dim in weights.keys()
            )

            # 获取实际效果
            actual_outcome = calculate_selection_outcome(rec['product_id'])

            # 计算相关性（得分高的是否效果好）
            total_outcome += new_score * actual_outcome

        return total_outcome / len(historical_recs)

    def optimize(self, n_iter: int = 50) -> dict:
        """运行优化"""
        optimizer = BayesianOptimization(
            f=self.objective,
            pbounds=self.pbounds,
            random_state=42
        )

        optimizer.maximize(
            init_points=10,
            n_iter=n_iter
        )

        # 获取最优权重
        best_weights = optimizer.max['params']

        # 归一化
        total = sum(best_weights.values())
        normalized = {k: round(v/total, 2) for k, v in best_weights.items()}

        return normalized
```

---

## 五、方案三：在线学习（实时调整）

### 原理
每次选品效果反馈后，实时微调权重

### 实现

```python
class OnlineWeightLearner:
    """在线学习权重调整"""

    def __init__(self, learning_rate: float = 0.01):
        self.lr = learning_rate
        self.weights = {
            'market_heat': 0.25,
            'competition_gap': 0.20,
            'supply_chain': 0.20,
            'profit_margin': 0.20,
            'category_synergy': 0.10,
            'seasonal_fit': 0.05
        }
        self.bounds = {
            'market_heat': (0.15, 0.35),
            'competition_gap': (0.10, 0.30),
            'supply_chain': (0.10, 0.30),
            'profit_margin': (0.15, 0.30),
            'category_synergy': (0.05, 0.20),
            'seasonal_fit': (0.00, 0.15)
        }

    def update(self, features: dict, outcome: float, predicted: float):
        """
        根据反馈更新权重

        Args:
            features: 各维度得分 {'market_heat': 85, ...}
            outcome: 实际效果 (0-1)
            predicted: 预测得分 (0-100)
        """
        # 计算误差
        error = outcome - (predicted / 100)

        # 梯度更新
        for dim, score in features.items():
            gradient = error * (score / 100)
            new_weight = self.weights[dim] + self.lr * gradient

            # 限制在范围内
            min_w, max_w = self.bounds[dim]
            new_weight = max(min_w, min(max_w, new_weight))

            self.weights[dim] = new_weight

        # 归一化
        total = sum(self.weights.values())
        self.weights = {k: v/total for k, v in self.weights.items()}

        return self.weights
```

---

## 六、方案四：阈值自动校准

### 搜索量阈值自动校准

```python
async def calibrate_volume_thresholds():
    """
    基于实际美团数据校准搜索量阈值
    """
    # 获取过去30天热搜词数据
    keywords = await get_meituan_keywords(days=30)

    volumes = [k['search_volume'] for k in keywords]

    # 计算分位数
    p25 = np.percentile(volumes, 25)
    p50 = np.percentile(volumes, 50)
    p75 = np.percentile(volumes, 75)
    p90 = np.percentile(volumes, 90)

    # 更新阈值
    new_thresholds = [
        int(p25),   # 低热度
        int(p50),   # 中热度
        int(p75),   # 高热度
        int(p90)    # 爆款
    ]

    return new_thresholds
```

### 异常检测阈值自动校准

```python
async def calibrate_anomaly_thresholds():
    """
    基于历史误报率校准异常检测阈值
    """
    # 获取过去30天的预警记录
    alerts = await get_alerts(days=30)

    # 计算误报率
    false_positives = len([a for a in alerts if a['status'] == 'ignored'])
    total = len(alerts)
    fp_rate = false_positives / max(total, 1)

    current_threshold = await get_config('sales_zscore_drop')

    if fp_rate > 0.3:
        # 误报太多，放宽阈值
        new_threshold = current_threshold - 0.2  # 如 -2.5 → -2.7
        print(f"误报率{fp_rate:.1%}过高，放宽阈值: {current_threshold} → {new_threshold}")
    elif fp_rate < 0.1:
        # 误报很少，可以收紧
        new_threshold = current_threshold + 0.1  # 如 -2.5 → -2.4
        print(f"误报率{fp_rate:.1%}较低，收紧阈值: {current_threshold} → {new_threshold}")
    else:
        new_threshold = current_threshold

    return new_threshold
```

---

## 七、自学习系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           参数自学习系统                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  数据采集层                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │ 选品推荐记录 │  │ 采购执行记录 │  │ 销售效果数据 │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
│         └─────────────────┴─────────────────┘                               │
│                           │                                                  │
│                           ▼                                                  │
│  效果标注层                                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    效果评分计算                                     │    │
│  │    outcome = f(是否采购, 销量表现, 毛利表现, 是否滞销)              │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                                 ▼                                           │
│  模型学习层                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                │
│  │ XGBoost Ranker │  │ 贝叶斯优化     │  │ 阈值校准       │                │
│  │ (权重学习)     │  │ (参数搜索)     │  │ (分位数)       │                │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘                │
│          └───────────────────┴───────────────────┘                          │
│                              │                                               │
│                              ▼                                               │
│  参数更新层                                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    参数版本管理                                     │    │
│  │    current_version → new_version (需人工审核 or 自动灰度)          │    │
│  └──────────────────────────────┬─────────────────────────────────────┘    │
│                                 │                                           │
│                                 ▼                                           │
│                         生产环境参数配置                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 八、定时任务配置

```yaml
scheduled_learning_tasks:

  # 每日：阈值校准
  daily_calibration:
    cron: "0 4 * * *"
    tasks:
      - calibrate_volume_thresholds
      - calibrate_anomaly_thresholds
    auto_apply: true  # 自动生效

  # 每周：权重学习
  weekly_weight_learning:
    cron: "0 3 * * 0"
    tasks:
      - train_selection_ranker
      - run_bayesian_optimization
    auto_apply: false  # 需人工审核
    notify: true

  # 每月：全量回测
  monthly_backtest:
    cron: "0 2 1 * *"
    tasks:
      - full_parameter_backtest
      - generate_optimization_report
    notify: true
```

---

## 九、参数版本管理

```python
class ParameterVersionManager:
    """参数版本管理"""

    async def create_version(self, params: dict, source: str) -> str:
        """创建新版本"""
        version_id = f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        await db.insert('parameter_versions', {
            'version_id': version_id,
            'params': params,
            'source': source,  # 'manual' / 'xgboost' / 'bayesian' / 'calibration'
            'status': 'pending',  # pending → approved → active → archived
            'created_at': datetime.now(),
            'metrics': None  # 上线后填充效果指标
        })

        return version_id

    async def approve_and_activate(self, version_id: str):
        """审核通过并激活"""
        # 归档当前版本
        current = await self.get_active_version()
        if current:
            await db.update('parameter_versions',
                {'version_id': current['version_id']},
                {'status': 'archived'}
            )

        # 激活新版本
        await db.update('parameter_versions',
            {'version_id': version_id},
            {'status': 'active', 'activated_at': datetime.now()}
        )

        # 更新配置
        new_params = await self.get_version(version_id)
        await update_runtime_config(new_params['params'])

    async def rollback(self, to_version_id: str):
        """回滚到指定版本"""
        await self.approve_and_activate(to_version_id)
```

---

## 十、集成到技术方案

在 `section_10_11_12.md` 中增加自学习模块：

```yaml
# config/learning.yaml

learning:
  enabled: true

  # 权重学习
  weight_learning:
    method: xgboost  # xgboost / bayesian / online
    min_samples: 100
    retrain_frequency: weekly
    auto_apply: false  # 需人工审核

  # 阈值校准
  threshold_calibration:
    enabled: true
    frequency: daily
    auto_apply: true

    targets:
      - volume_thresholds
      - anomaly_zscore
      - margin_thresholds

  # 效果追踪
  outcome_tracking:
    enabled: true
    evaluation_days: 30  # 采购后30天评估效果

    metrics:
      - adoption_rate    # 推荐采纳率
      - sales_vs_expected  # 销量达成率
      - margin_achievement  # 毛利达成率
      - slow_moving_rate   # 滞销率
```

---

## 十一、推荐方案

| 场景 | 推荐方案 | 理由 |
|------|----------|------|
| **权重学习** | XGBoost Ranker | 可解释、稳定、样本需求适中 |
| **阈值校准** | 分位数自动校准 | 简单有效、实时性好 |
| **参数搜索** | 贝叶斯优化 | 搜索效率高、适合连续参数 |
| **上线策略** | 人工审核 + 灰度 | 保证安全、可回滚 |

---
# 参数自动学习优化方案

## 一、问题分析

当前hardcode参数分三类：

| 类型 | 示例 | 优化方法 |
|------|------|----------|
| 评分权重 | market_heat: 0.25 | Learning to Rank |
| 阈值参数 | volume_thresholds: [1000, 5000...] | 数据分布自适应 |
| 业务规则 | minimum_threshold: 0.25 | 贝叶斯优化 + 业务约束 |

---

## 二、评分权重自动学习

### 方案：Learning to Rank (LTR)

**原理**：用选品效果作为标签，让模型自动学习最优权重

**数据构建**：

```python
# 每条选品推荐记录
{
    "recommendation_id": "R001",
    "product_keyword": "电子血压计",
    "timestamp": "2026-03-01",

    # 特征（即评分维度的原始分数）
    "features": {
        "market_heat_score": 75,
        "competition_gap_score": 60,
        "supply_chain_score": 80,
        "profit_margin_score": 65,
        "category_synergy_score": 50,
        "seasonal_fit_score": 40
    },

    # 当时的加权总分
    "predicted_score": 68.5,

    # 实际效果（标签）
    "outcome": {
        "was_purchased": true,           # 是否采购
        "purchase_quantity": 50,         # 采购数量
        "actual_monthly_sales": 120,     # 实际月销
        "actual_margin": 0.42,           # 实际毛利
        "days_to_first_sale": 2          # 首单天数
    },

    # 综合效果评分（0-1）
    "outcome_score": 0.85
}
```

**效果评分计算**：

```python
def calculate_outcome_score(outcome: dict) -> float:
    """
    计算选品效果评分
    """
    if not outcome['was_purchased']:
        return 0.0

    score = 0.0

    # 销量达成（40%权重）
    sales_ratio = outcome['actual_monthly_sales'] / max(outcome['expected_sales'], 1)
    score += min(sales_ratio, 1.5) / 1.5 * 0.4

    # 毛利达成（30%权重）
    if outcome['actual_margin'] >= 0.40:
        score += 0.3
    elif outcome['actual_margin'] >= 0.30:
        score += 0.2
    elif outcome['actual_margin'] >= 0.25:
        score += 0.1

    # 动销速度（20%权重）
    if outcome['days_to_first_sale'] <= 3:
        score += 0.2
    elif outcome['days_to_first_sale'] <= 7:
        score += 0.1

    # 采购转化（10%权重）
    score += 0.1  # 已采购

    return score
```

**模型训练**：

```python
import xgboost as xgb
from sklearn.model_selection import train_test_split

class WeightLearner:
    """
    自动学习评分权重
    """

    def __init__(self):
        self.model = xgb.XGBRanker(
            objective='rank:pairwise',
            learning_rate=0.1,
            max_depth=3,
            n_estimators=100
        )
        self.feature_names = [
            'market_heat_score',
            'competition_gap_score',
            'supply_chain_score',
            'profit_margin_score',
            'category_synergy_score',
            'seasonal_fit_score'
        ]

    def prepare_data(self, recommendations: List[dict]):
        """准备训练数据"""
        X = []
        y = []

        for rec in recommendations:
            features = [rec['features'][f] for f in self.feature_names]
            X.append(features)
            y.append(rec['outcome_score'])

        return np.array(X), np.array(y)

    def train(self, recommendations: List[dict]):
        """训练模型"""
        X, y = self.prepare_data(recommendations)

        # 按时间分组（同一天的推荐作为一组）
        groups = self._get_groups(recommendations)

        self.model.fit(X, y, group=groups)

        # 提取学到的权重（特征重要性）
        importance = self.model.feature_importances_
        learned_weights = importance / importance.sum()

        return dict(zip(self.feature_names, learned_weights))

    def get_learned_weights(self) -> dict:
        """获取学习到的权重"""
        importance = self.model.feature_importances_
        normalized = importance / importance.sum()

        return {
            'market_heat': round(normalized[0], 2),
            'competition_gap': round(normalized[1], 2),
            'supply_chain': round(normalized[2], 2),
            'profit_margin': round(normalized[3], 2),
            'category_synergy': round(normalized[4], 2),
            'seasonal_fit': round(normalized[5], 2)
        }
```

**定期更新流程**：

```python
async def weekly_weight_optimization():
    """
    每周自动优化权重
    """
    # 1. 获取最近30天的选品效果数据
    recommendations = await db.get_recommendations_with_outcomes(days=30)

    if len(recommendations) < 100:
        logger.info("数据不足，跳过本次优化")
        return

    # 2. 训练模型
    learner = WeightLearner()
    learned_weights = learner.train(recommendations)

    # 3. 验证权重合理性（业务约束）
    if not validate_weights(learned_weights):
        logger.warning("学习到的权重不符合业务约束，使用默认值")
        return

    # 4. A/B测试：50%流量使用新权重
    await config.set_ab_test_weights(
        control=current_weights,
        treatment=learned_weights,
        traffic_split=0.5
    )

    # 5. 一周后评估效果
    # 如果treatment组效果更好，全量切换

def validate_weights(weights: dict) -> bool:
    """业务约束校验"""
    # 利润权重不能太低
    if weights['profit_margin'] < 0.15:
        return False

    # 供应链权重不能太低
    if weights['supply_chain'] < 0.10:
        return False

    # 单一维度不能过高
    if max(weights.values()) > 0.40:
        return False

    return True
```

---

## 三、阈值参数自适应

### 方案：基于数据分布的动态阈值

**原理**：根据实际数据的分位数自动调整阈值

**搜索量阈值自适应**：

```python
class AdaptiveThresholds:
    """
    自适应阈值管理
    """

    async def update_volume_thresholds(self):
        """
        根据实际搜索量分布更新阈值
        """
        # 获取近30天的热搜词数据
        keywords = await actionbook.get_historical_keywords(days=30)
        volumes = [k['search_volume'] for k in keywords]

        # 计算分位数
        p20 = np.percentile(volumes, 20)
        p40 = np.percentile(volumes, 40)
        p60 = np.percentile(volumes, 60)
        p80 = np.percentile(volumes, 80)

        new_thresholds = [
            int(p20),   # 低热度
            int(p40),   # 中低热度
            int(p60),   # 中等热度
            int(p80)    # 高热度
        ]

        # 平滑更新（避免剧烈变化）
        current = config.get('volume_thresholds')
        smoothed = [
            int(0.7 * c + 0.3 * n)
            for c, n in zip(current, new_thresholds)
        ]

        await config.set('volume_thresholds', smoothed)

        return smoothed

    async def update_margin_thresholds(self):
        """
        根据实际毛利分布更新阈值
        """
        # 获取在售商品的毛利率
        products = await db.get_active_products_with_margin()
        margins = [p['gross_margin'] for p in products]

        # 计算分位数
        excellent = np.percentile(margins, 80)  # Top 20%
        good = np.percentile(margins, 60)       # Top 40%
        fair = np.percentile(margins, 40)       # Top 60%

        # 业务底线约束
        new_thresholds = {
            'excellent': max(excellent, 0.40),  # 不低于40%
            'good': max(good, 0.30),            # 不低于30%
            'fair': max(fair, 0.25),            # 不低于25%
            'minimum': 0.20                      # 硬底线不变
        }

        await config.set('margin_thresholds', new_thresholds)
```

**异常检测阈值自适应**：

```python
async def update_anomaly_thresholds():
    """
    根据历史异常数据调整检测阈值
    """
    # 获取近60天的预警记录
    alerts = await db.get_alerts(days=60)

    # 统计误报率
    false_positive_rate = len([a for a in alerts if a['was_false_positive']]) / len(alerts)

    # 统计漏报（通过人工标记）
    missed_alerts = await db.get_missed_anomalies(days=60)
    false_negative_rate = len(missed_alerts) / (len(alerts) + len(missed_alerts))

    current_zscore = config.get('sales_zscore_drop')

    # 调整策略
    if false_positive_rate > 0.30:
        # 误报太多，放宽阈值
        new_zscore = current_zscore - 0.2  # 从-2.5调到-2.7
    elif false_negative_rate > 0.20:
        # 漏报太多，收紧阈值
        new_zscore = current_zscore + 0.2  # 从-2.5调到-2.3
    else:
        new_zscore = current_zscore

    # 限制范围
    new_zscore = max(-3.5, min(-1.5, new_zscore))

    await config.set('sales_zscore_drop', new_zscore)
```

---

## 四、贝叶斯优化（复杂参数组合）

**适用场景**：多个参数联合优化，寻找全局最优

```python
from bayes_opt import BayesianOptimization

class ParameterOptimizer:
    """
    贝叶斯优化参数
    """

    def __init__(self):
        self.optimizer = BayesianOptimization(
            f=self.objective_function,
            pbounds={
                'market_heat_weight': (0.15, 0.35),
                'competition_gap_weight': (0.10, 0.30),
                'supply_chain_weight': (0.10, 0.30),
                'profit_margin_weight': (0.15, 0.30),
                'volume_threshold_1': (500, 2000),
                'volume_threshold_2': (3000, 8000),
            },
            random_state=42
        )

    def objective_function(self, **params) -> float:
        """
        目标函数：使用参数运行选品，评估效果
        """
        # 构建配置
        weights = {
            'market_heat': params['market_heat_weight'],
            'competition_gap': params['competition_gap_weight'],
            'supply_chain': params['supply_chain_weight'],
            'profit_margin': params['profit_margin_weight'],
            'category_synergy': 0.10,  # 固定
            'seasonal_fit': 1.0 - sum([
                params['market_heat_weight'],
                params['competition_gap_weight'],
                params['supply_chain_weight'],
                params['profit_margin_weight'],
                0.10
            ])
        }

        # 使用历史数据回测
        score = self.backtest(weights, params)

        return score

    def backtest(self, weights: dict, params: dict) -> float:
        """
        历史数据回测，返回效果评分
        """
        # 获取历史推荐和实际效果
        historical = db.get_historical_recommendations(days=60)

        total_score = 0
        for rec in historical:
            # 用新权重重新计算得分
            new_score = self.calculate_score(rec['features'], weights)

            # 看新得分的排序是否和实际效果一致
            correlation = self.rank_correlation(new_score, rec['outcome_score'])
            total_score += correlation

        return total_score / len(historical)

    def optimize(self, n_iter: int = 50):
        """运行优化"""
        self.optimizer.maximize(n_iter=n_iter)
        return self.optimizer.max
```

---

## 五、实现架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         参数自动学习系统                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  数据采集层                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 选品效果记录 │ 预警准确性记录 │ 客服满意度 │ 销量/毛利数据           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  学习层                                                                      │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐                  │
│  │ Weight Learner │ │ Threshold      │ │ Bayesian       │                  │
│  │ (XGBoost LTR)  │ │ Adapter        │ │ Optimizer      │                  │
│  │ 评分权重学习   │ │ 阈值自适应     │ │ 参数组合优化   │                  │
│  └───────┬────────┘ └───────┬────────┘ └───────┬────────┘                  │
│          │                  │                  │                            │
│          └──────────────────┴──────────────────┘                            │
│                             │                                                │
│                             ▼                                                │
│  验证层                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 业务约束校验 │ A/B测试 │ 回测验证 │ 人工审核（可选）                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│  配置层                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                     Config Service                                    │   │
│  │  • 参数版本管理                                                       │   │
│  │  • 灰度发布                                                           │   │
│  │  • 回滚能力                                                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 六、定时任务配置

```yaml
parameter_learning:

  # 权重学习（每周一凌晨）
  weight_learning:
    schedule: "0 3 * * 1"
    min_samples: 100
    method: "xgboost_ltr"
    auto_apply: false  # 需要A/B测试验证

  # 阈值自适应（每天凌晨）
  threshold_adaptation:
    schedule: "0 4 * * *"
    smoothing_factor: 0.3
    auto_apply: true

  # 异常检测阈值（每周）
  anomaly_threshold:
    schedule: "0 5 * * 1"
    target_fpr: 0.20  # 目标误报率20%
    auto_apply: true

  # 贝叶斯全局优化（每月）
  bayesian_optimization:
    schedule: "0 2 1 * *"
    n_iterations: 50
    auto_apply: false  # 需要人工审核
```

---

## 七、数据库表

```sql
-- 参数版本历史
CREATE TABLE parameter_versions (
    version_id VARCHAR(50) PRIMARY KEY,
    parameter_type VARCHAR(50),  -- weights/thresholds/anomaly
    parameter_values JSONB,
    learning_method VARCHAR(50),  -- xgboost/adaptive/bayesian
    training_samples INTEGER,
    validation_score DECIMAL(5,4),
    status VARCHAR(20) DEFAULT 'candidate',  -- candidate/ab_testing/active/archived
    created_at TIMESTAMP DEFAULT NOW(),
    activated_at TIMESTAMP
);

-- 选品效果追踪
CREATE TABLE recommendation_outcomes (
    id SERIAL PRIMARY KEY,
    recommendation_id VARCHAR(50),
    product_keyword VARCHAR(100),
    features JSONB,
    predicted_score DECIMAL(5,2),
    was_purchased BOOLEAN,
    purchase_date DATE,
    actual_monthly_sales INTEGER,
    actual_margin DECIMAL(5,4),
    outcome_score DECIMAL(5,4),
    created_at TIMESTAMP DEFAULT NOW()
);

-- A/B测试记录
CREATE TABLE parameter_ab_tests (
    test_id VARCHAR(50) PRIMARY KEY,
    parameter_type VARCHAR(50),
    control_version VARCHAR(50),
    treatment_version VARCHAR(50),
    traffic_split DECIMAL(3,2),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    control_metrics JSONB,
    treatment_metrics JSONB,
    winner VARCHAR(20),  -- control/treatment/inconclusive
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 八、总结

| 参数类型 | 优化方法 | 频率 | 自动应用 |
|----------|----------|------|----------|
| 评分权重 | XGBoost LTR | 每周 | 需A/B测试 |
| 搜索量阈值 | 分位数自适应 | 每天 | 自动 |
| 毛利率阈值 | 分位数自适应 | 每天 | 自动（有底线） |
| 异常检测阈值 | 误报率反馈 | 每周 | 自动 |
| 参数组合 | 贝叶斯优化 | 每月 | 需人工审核 |

**核心原则**：
1. **数据驱动**：所有调整基于效果数据
2. **约束保护**：业务底线不可突破
3. **渐进更新**：平滑调整，避免剧烈变化
4. **可回滚**：保留历史版本，随时回滚
