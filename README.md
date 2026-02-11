# AI店长 - 智能零售管理系统

美团即时零售（医疗器械类目）智能运营系统

## 功能模块

| 模块 | 描述 |
|------|------|
| Selection Agent | 智能选品（市场分析 → 缺品识别 → 供应链评估 → 综合评分） |
| CustomerService Agent | 智能客服（意图识别 → Hybrid Search → GraphRAG → 回复生成） |
| Alert Agent | 智能预警（Prophet时序检测 → 归因分析 → 行动建议） |
| Bundle Agent | 智能套餐（FP-Growth关联挖掘 → 场景设计 → 定价） |
| Listing Agent | 智能上架（1688/拼多多解析 → 标品匹配 → 合规校验） |

## 技术栈

- **Agent框架**: LangGraph 0.2.x
- **LLM**: Claude API (Haiku/Sonnet/Opus 分层)
- **Web框架**: FastAPI
- **数据库**: PostgreSQL 16 + Neo4j 5 + Redis 7
- **时序预测**: Prophet
- **检索增强**: BGE Embedding + BGE Reranker + Neo4j Vector Index
- **可观测性**: Langfuse + Prometheus + Grafana

## 项目结构

```
ai-store-manager/
├── SPEC.md                    # 完整技术方案
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── config/                    # 配置文件
│   ├── scoring.yaml
│   ├── anomaly.yaml
│   ├── customer_service.yaml
│   └── system.yaml
├── src/
│   ├── __init__.py
│   ├── main.py                # FastAPI 入口
│   ├── config.py              # 配置加载
│   ├── agents/                # Agent 定义
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # 总调度
│   │   ├── selection/         # 选品 Agent
│   │   ├── customer_service/  # 客服 Agent
│   │   ├── alert/             # 预警 Agent
│   │   ├── bundle/            # 套餐 Agent
│   │   └── listing/           # 上架 Agent
│   ├── skills/                # MCP Skills Layer
│   │   ├── __init__.py
│   │   ├── actionbook.py      # 数据采集（美团/1688/拼多多）
│   │   ├── neo4j_skill.py     # 图谱 + 向量检索
│   │   ├── database.py        # PostgreSQL CRUD
│   │   ├── embedding.py       # BGE 向量化
│   │   ├── reranker.py        # BGE Reranker
│   │   ├── prophet_skill.py   # 时序预测
│   │   ├── calculator.py      # 评分/毛利计算
│   │   └── notifier.py        # 企业微信通知
│   ├── models/                # 数据模型
│   │   ├── __init__.py
│   │   ├── product.py
│   │   ├── order.py
│   │   ├── alert.py
│   │   └── bundle.py
│   ├── db/                    # 数据库
│   │   ├── __init__.py
│   │   ├── postgres.py        # PostgreSQL 连接
│   │   ├── neo4j.py           # Neo4j 连接
│   │   └── redis.py           # Redis 连接
│   └── api/                   # API 路由
│       ├── __init__.py
│       ├── selection.py
│       ├── customer_service.py
│       ├── alerts.py
│       ├── bundles.py
│       └── listing.py
├── migrations/                # 数据库迁移
│   ├── postgres/
│   │   └── 001_initial.sql
│   └── neo4j/
│       └── 001_schema.cypher
├── tests/
│   ├── __init__.py
│   ├── test_selection.py
│   ├── test_customer_service.py
│   ├── test_alert.py
│   └── test_bundle.py
└── scripts/
    ├── seed_data.py           # 初始化数据
    └── train_prophet.py       # 训练Prophet模型
```

## 开发计划

详见 SPEC.md 第十二部分
