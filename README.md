# AI店长 — 智能医疗器械零售运营系统

> 美团即时零售（医疗器械类目）AI 驱动运营系统，覆盖客服、选品、预警、套餐、上架、定价六大核心环节。

[![CI](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/Ken-LiuL/AI-Shopkeeper/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)]()

---

## 系统架构

```
┌───────────────────────────────────────────────────────────────┐
│                        接入层                                  │
│   Next.js 管理后台  ·  企业微信  ·  APScheduler 定时任务       │
└──────────────────────────┬────────────────────────────────────┘
                           │  HTTP / WebSocket
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                   FastAPI  (8000)                              │
│   /api/selection · /api/cs · /api/alerts · /api/bundles       │
│   /api/listing · /api/products · /api/dashboard               │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                  Orchestrator（总调度）                         │
│         接收请求 → 路由到子 Agent → 聚合结果返回                │
└──┬──────────┬──────────┬──────────┬──────────┬────────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│选品  │ │客服  │ │预警  │ │套餐  │ │上架  │   ← LangGraph 状态机
│Agent │ │Agent │ │Agent │ │Agent │ │Agent │
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
   └────────┴────────┴────────┴────────┘
                     │
                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    Skills Layer                                │
│  Neo4jSkill · DatabaseSkill · EmbeddingSkill · RerankerSkill  │
│  ProphetSkill · CalculatorSkill · Notifier                    │
└──────────────────────────┬────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐    ┌──────────┐     ┌──────────┐
   │PostgreSQL│    │  Neo4j   │     │  Redis   │
   │   16     │    │ 5 + APOC │     │    7     │
   │ (业务数据)│    │(知识图谱) │     │  (缓存)  │
   └──────────┘    └──────────┘     └──────────┘
```

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| Agent 框架 | LangGraph | ≥ 0.2 |
| LLM 调用 | OpenRouter (Gemini Flash / DeepSeek V3 / Claude Sonnet) + Anthropic 直连 | — |
| Web 框架 | FastAPI + Uvicorn | ≥ 0.115 |
| 前端 | Next.js + TailwindCSS + Recharts | — |
| 关系数据库 | PostgreSQL | 16 |
| 图数据库 | Neo4j Community + APOC | 5 |
| 缓存 | Redis (hiredis) | 7 |
| 向量化 | BGE-large-zh (sentence-transformers) | 1024d |
| 精排 | BGE-Reranker | — |
| 时序预测 | Prophet | ≥ 1.1 |
| 可观测性 | Langfuse + Prometheus + Grafana | — |
| CI | GitHub Actions (ruff + pytest + coverage) | — |

## 功能模块

| Agent / 服务 | 职责 | 说明 |
|-------------|------|------|
| **CustomerService** | 智能客服：意图识别→路由→混合检索→精排→GraphRAG→回复生成 | LangGraph 8节点，Chrome 扩展透传 |
| **Selection** | 智能选品：市场分析→竞品监控→缺品识别→供应链评估→综合评分 | LangGraph 8节点 |
| **Alert** | 智能预警：Prophet 时序检测→规则引擎→归因分析→行动建议 | LangGraph 3节点 |
| **Bundle** | 智能套餐：FP-Growth 关联挖掘→场景设计→定价 | LangGraph 3节点 |
| **Listing** | 智能上架：1688/拼多多商品信息解析→标品匹配→信息填充→合规校验 | LangGraph 4节点 |
| **Pricing** | 动态定价：竞品价格对比→毛利分析→弹性估算→调价建议→批量执行 | 增效核心 |
| **DailyReport** | 智能日报：销售对比→热销/滞销→客服统计→预警→明日待办→推送 | 每日22:00自动推送 |
| **Replenishment** | 智能补货：安全库存计算→补货建议→一键生成采购单 | 降本核心 |

> 详细说明见 [docs/AGENTS.md](docs/AGENTS.md)

## 数据导入方式

系统数据通过以下两种方式导入，**不使用爬虫或自动化抓取**：

| 方式 | 说明 |
|------|------|
| **Chrome 扩展** | 安装在商家浏览器上，拦截美团商家后台 WebSocket 客服消息，实时转发至后端 AI 客服接口 |
| **手动上传** | 运营人员将商品数据、订单数据、竞品信息等通过管理后台手动上传（CSV/Excel） |

Chrome 扩展安装说明见 [chrome-extension/README.md](chrome-extension/README.md)。

## 快速开始（5 分钟）

### 环境要求

- Python 3.11+
- Docker & Docker Compose
- 一个 OpenRouter API Key（或 Anthropic API Key）

### 1. 克隆 & 安装

```bash
git clone https://github.com/Ken-LiuL/AI-Shopkeeper.git
cd AI-Shopkeeper
cp .env.example .env
# 编辑 .env，填入 API Key
```

### 2. 启动基础设施

```bash
docker compose up -d          # PostgreSQL 16 + Neo4j 5 + Redis 7
make health-check             # 等待所有服务 ready
```

### 3. 初始化数据库 & 种子数据

```bash
make migrate-pg               # PostgreSQL schema
make migrate-neo4j            # Neo4j schema + 向量索引
make seed                     # 示例商品 + 订单 + FAQ
python scripts/seed_knowledge_graph.py  # 知识图谱
```

### 4. 启动应用

```bash
# 方式一：开发模式（auto-reload）
make dev                      # → http://localhost:8000

# 方式二：Docker
docker compose --profile app up -d
```

### 5. 访问

| 服务 | 地址 |
|------|------|
| API 文档 (Swagger) | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |
| 深度就绪检查 | http://localhost:8000/ready |
| Neo4j Browser | http://localhost:7474 |
| 前端管理台 | http://localhost:3000（`cd frontend && npm run dev`）|

## API 概览

所有 API 返回统一格式：`{"success": true, "data": ..., "message": ""}`

| 模块 | 端点 | 说明 |
|------|------|------|
| 客服 | `POST /api/cs/chat` | 发送咨询消息 |
| 选品 | `POST /api/selection/run` | 触发选品分析 |
| | `GET /api/selection/recommendations` | 获取最新推荐 |
| 预警 | `POST /api/alerts/scan` | 触发预警扫描 |
| | `GET /api/alerts` | 查询预警列表 |
| 套餐 | `POST /api/bundles/generate` | 触发套餐生成 |
| 上架 | `POST /api/listing/create` | 创建上架任务 |
| | `POST /api/listing/parse` | 解析商品链接 |
| 定价 | `GET /api/pricing/suggestions` | 调价建议 |
| | `POST /api/pricing/apply` | 批量调价 |
| 商品 | `GET/POST/PUT /api/products` | 商品 CRUD |
| 补货 | `GET /api/replenishment/suggestions` | 补货建议 |
| | `POST /api/replenishment/purchase-order` | 生成采购单 |
| 分析 | `GET /api/analytics/customer-service` | 客服统计 |
| | `GET /api/analytics/conversion` | 转化追踪 |
| 仪表盘 | `GET /api/dashboard/overview` | 运营概览 |

> 完整 API 文档见 [docs/API.md](docs/API.md)

## Agent 交互流程

```
用户请求 / 定时触发
       │
       ▼
  Orchestrator.run(task_type, input)
       │
       ├─ task_type="customer_service" ──→ CSGraph.ainvoke()
       │     intent → route ─┬─ faq → reply
       │                     ├─ search → rerank → graphrag → reply
       │                     └─ human (转人工)
       │
       ├─ task_type="selection" ──→ SelectionGraph.ainvoke()
       │     fetch_data → [market ∥ competitor ∥ inventory ∥ seasonal]
       │     → gap_identification → supplier_evaluation → scorer
       │
       ├─ task_type="alert" ──→ AlertGraph.ainvoke()
       │     anomaly_detection ─┬─ 无异常 → END
       │                        └─ 有异常 → root_cause → action
       │
       ├─ task_type="bundle" ──→ BundleGraph.ainvoke()
       │     order_mining → scene_design → pricing
       │
       └─ task_type="listing" ──→ ListingGraph.ainvoke()
             parser → matcher → filler → compliance
```

## 配置说明

### 环境变量（.env）

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `LLM_PROVIDER` | 否 | LLM 提供商：`openrouter` 或 `anthropic` | `openrouter` |
| `OPENROUTER_API_KEY` | 是* | OpenRouter API Key | — |
| `ANTHROPIC_API_KEY` | 是* | Anthropic API Key（直连时） | — |
| `POSTGRES_HOST` | 否 | PostgreSQL 主机 | `localhost` |
| `POSTGRES_PORT` | 否 | PostgreSQL 端口 | `5432` |
| `POSTGRES_DB` | 否 | 数据库名 | `ai_store` |
| `POSTGRES_USER` | 否 | 数据库用户 | `postgres` |
| `POSTGRES_PASSWORD` | 否 | 数据库密码 | `postgres` |
| `NEO4J_URI` | 否 | Neo4j Bolt 地址 | `bolt://localhost:7687` |
| `NEO4J_USER` | 否 | Neo4j 用户 | `neo4j` |
| `NEO4J_PASSWORD` | 否 | Neo4j 密码 | `neo4jpassword` |
| `REDIS_URL` | 否 | Redis 连接 URL | `redis://localhost:6379/0` |
| `LANGFUSE_PUBLIC_KEY` | 否 | Langfuse 追踪 Public Key | — |
| `LANGFUSE_SECRET_KEY` | 否 | Langfuse 追踪 Secret Key | — |
| `LANGFUSE_HOST` | 否 | Langfuse 服务地址 | `http://localhost:3000` |
| `WECHAT_WEBHOOK_URL` | 否 | 企业微信机器人 Webhook | — |

> *二选一：使用 OpenRouter 填 `OPENROUTER_API_KEY`，直连 Anthropic 填 `ANTHROPIC_API_KEY`。

### YAML 配置文件

| 文件 | 说明 |
|------|------|
| `config/system.yaml` | 系统参数：LLM 模型、并发、缓存 TTL、定时任务 cron、数据库连接 |
| `config/scoring.yaml` | 选品评分：六维度权重、热度评分参数、供应商评分、毛利阈值 |
| `config/anomaly.yaml` | 预警检测：Prophet 参数、销量异常阈值、库存预警天数 |
| `config/customer_service.yaml` | 客服配置：意图识别、检索参数、回复模板 |

## 开发指南

### 运行测试

```bash
make test                     # pytest -v --tb=short
pytest tests/test_cs_graph.py # 单个测试文件
pytest -k "test_intent"       # 按名称过滤
```

测试环境自动设置 `TESTING=1`，跳过调度器启动和外部依赖。

### 代码规范

```bash
make lint                     # ruff check + mypy
ruff check src tests --fix    # 自动修复
```

- **Linter**: Ruff (E, F, I, N, W, UP, B, A, SIM)
- **Type Checker**: mypy (strict mode)
- **Line Length**: 100
- **Target**: Python 3.11

### 项目结构

```
src/
├── main.py              # FastAPI 入口 + lifespan
├── config.py            # YAML 配置加载（支持 ${ENV_VAR:default}）
├── metrics.py           # Prometheus 指标定义
├── scheduler.py         # APScheduler 定时任务
├── agents/
│   ├── orchestrator.py  # 总调度器
│   ├── llm.py           # 统一 LLM 调用（OpenRouter/Anthropic + Langfuse）
│   ├── tools.py         # Anthropic tool schema 定义
│   ├── prompts/         # 各 Agent 的 Prompt 模板
│   ├── selection/       # 选品 Agent（graph + nodes + state）
│   ├── customer_service/# 客服 Agent
│   ├── alert/           # 预警 Agent
│   ├── bundle/          # 套餐 Agent
│   └── listing/         # 上架 Agent
├── skills/              # Skills Layer
│   ├── neo4j_skill.py   # 知识图谱 + 向量检索
│   ├── database.py      # PostgreSQL CRUD
│   ├── embedding.py     # BGE 向量化
│   ├── reranker.py      # BGE 精排
│   ├── prophet_skill.py # 时序预测
│   ├── calculator.py    # 评分/毛利计算
│   └── notifier.py      # 企业微信通知
├── models/              # Pydantic 数据模型
├── db/                  # 数据库连接管理（postgres/neo4j/redis）
├── api/                 # FastAPI 路由
├── sync/                # ETL 数据处理（手动上传后处理）
└── learning/            # 自适应学习（权重/阈值/版本管理）

chrome-extension/        # Chrome 扩展（客服消息透传）
frontend/                # Next.js 管理后台
```

## 部署

### Docker Compose（推荐）

```bash
# 开发环境
docker compose up -d

# 生产环境（含应用容器）
docker compose --profile app up -d
```

### 生产注意事项

- 反向代理：Nginx 配置 HTTPS + WebSocket 转发
- 进程管理：Dockerfile 内置 `uvicorn --workers 2`，建议配合 Supervisor
- 数据库：启用 PostgreSQL 主从复制，Neo4j 配置认证
- 监控：Prometheus + Grafana 仪表盘
- 备份：PostgreSQL `pg_dump` 每日备份，Neo4j `neo4j-admin dump` 每日备份

> 详细部署文档见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## 文档导航

| 文档 | 说明 |
|------|------|
| [docs/API.md](docs/API.md) | 完整 API 文档 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计 |
| [docs/AGENTS.md](docs/AGENTS.md) | Agent 详细说明 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 部署指南 |
| [docs/客户方案书.md](docs/客户方案书.md) | 客户方案书 |
| [SPEC.md](SPEC.md) | 完整技术规格书（历史版本，部分内容已过时） |

## 许可证

Proprietary — All rights reserved.
