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

## 数据同步模块 (`src/sync/`)

牵牛花（`qnh.meituan.com`）数据采集引擎，支持全量和增量同步。

### 架构

| 文件 | 职责 |
|------|------|
| `base.py` | `BaseSyncer` 抽象基类 — 全量/增量/智能选择、重试、状态持久化 |
| `qnh_auth.py` | 认证管理 — Cookie持久化、CDP提取、滑块验证码、自动重登录 |
| `qnh_client.py` | HTTP客户端 — csec参数注入、限流、并发控制、auth自动刷新 |
| `products.py` | 商品主档同步（SPU/SKU/价格/状态） |
| `orders.py` | 订单数据同步（金额/状态/商品明细） |
| `metrics.py` | 每日经营指标（订单额/客单价/毛利/渠道分布） |
| `inventory.py` | 库存快照 + 库存流水增量 |
| `traffic.py` | 商品流量（曝光/点击/转化） |
| `reviews.py` | 评价数据（评分/内容/回复） |
| `scheduler.py` | 定时调度器（cron式调度） |

### 调度策略

```
products   → 全量 06:00 + 增量 every 4h
orders     → 增量 every 30min
metrics    → 全量 23:30
inventory  → 增量 every 1h
traffic    → 全量 23:00
reviews    → 增量 every 4h
```

### 快速开始

```python
from src.sync import QNHClient, QNHAuth, ProductSyncer, SyncScheduler

auth = QNHAuth()  # 从环境变量或浏览器CDP获取session
async with QNHClient(auth=auth) as client:
    syncer = ProductSyncer(client=client, db_pool=pool)
    result = await syncer.sync()  # 智能选择全量或增量
    print(result.summary)
```

### 数据库迁移

```bash
psql -f migrations/postgres/002_sync_tables.sql
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `QNH_USERNAME` | 牵牛花登录账号 |
| `QNH_PASSWORD` | 牵牛花登录密码 |
| `QNH_SESSION_FILE` | Session持久化路径（默认 `~/.qnh_session.json`） |
| `QNH_CDP_ENDPOINT` | Chrome CDP端口（默认 `http://127.0.0.1:9222`） |

## 开发计划

详见 SPEC.md 第十二部分
