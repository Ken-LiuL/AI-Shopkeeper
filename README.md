# AI店长 — 智能医疗器械零售运营系统

> 美团即时零售（医疗器械类目）AI 驱动运营系统。当前核心功能：**智能客服** + **智能上架**。

[![Backend CI](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/frontend-ci.yml)
[![Deploy](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/deploy.yml/badge.svg)](https://github.com/Ken-LiuL/AI-Shopkeeper/actions/workflows/deploy.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

---

## 核心功能

### 🤖 智能客服（已上线）

Chrome 扩展拦截美团商家后台 WebSocket 消息，转发至 AI 后端，实时生成专业回复。

- **LangGraph 5 步管线**：意图识别 → 混合检索 → Reranker 精排 → GraphRAG 知识丰富 → 回复生成
- **三种回复模式**：建议模式（默认）/ 半自动填充 / 全自动发送
- **医疗器械合规过滤**：16 条硬拦截 + 6 条软替换，杜绝违规表述
- **置信度兜底**：低置信度自动转人工，中置信度标记需审核
- **效果量化**：响应时间、接管率、转人工率实时追踪

### 📤 智能上架（已上线）

从 1688/拼多多商品页一键导入，AI 自动完成标品匹配、信息填充、合规校验。

- **Chrome 扩展一键导入**：在 1688/拼多多商品页点击导入按钮，自动提取商品信息
- **LangGraph 4 步管线**：商品解析 → 标品匹配 → 信息填充（SEO 标题、智能定价、卖点生成）→ 合规校验
- **医疗器械合规校验**：注册证/备案号核查、禁忌词过滤、自动修复
- **批量上架**：支持多商品并行处理
- **进度追踪**：实时展示每步处理进度

### 🔔 智能预警

- Prophet 时序异常检测 + IsolationForest 异常识别
- 规则引擎 + 归因分析 + 行动建议

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    接入层                              │
│   Next.js 管理后台  ·  Chrome 扩展（客服+上架）        │
└────────────────────────┬─────────────────────────────┘
                         │  HTTP
                         ▼
┌──────────────────────────────────────────────────────┐
│                FastAPI  (8000)                         │
│   /api/customer-service · /api/listing · /api/alerts  │
│   /health · /ready · /api/dashboard                   │
└────────────────────────┬─────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ CS Agent │   │ Listing  │   │  Alert   │   ← LangGraph 状态机
   │ (5 nodes)│   │ (4 nodes)│   │ (3 nodes)│
   └────┬─────┘   └────┬─────┘   └────┬─────┘
        └───────────────┼──────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│                  Skills Layer                          │
│  EmbeddingSkill · RerankerSkill · Neo4jSkill          │
│  DatabaseSkill · ComplianceFilter · Notifier          │
└────────────────────────┬─────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │PostgreSQL│   │  Neo4j   │   │  Redis   │
   │   16     │   │ 5 + APOC │   │    7     │
   └──────────┘   └──────────┘   └──────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 框架 | LangGraph ≥ 0.2 |
| LLM | OpenRouter (Gemini Flash / DeepSeek V3 / Claude Sonnet) |
| Web 框架 | FastAPI + Uvicorn |
| 前端 | Next.js 14 + TailwindCSS + shadcn/ui |
| 数据库 | PostgreSQL 16 + Neo4j 5 + Redis 7 |
| 向量化 | BGE-large-zh (1024d) + BGE-Reranker |
| CI/CD | GitHub Actions → Docker → VPS |

## 快速开始

### 环境要求

- Docker & Docker Compose
- OpenRouter API Key（或 Anthropic API Key）

### 1. 克隆 & 配置

```bash
git clone https://github.com/Ken-LiuL/AI-Shopkeeper.git
cd AI-Shopkeeper
cp .env.example .env
# 编辑 .env，填入 API Key
```

### 2. 启动

```bash
docker compose up -d
# PostgreSQL + Neo4j + Redis + App 全部自动启动
# Migration 在容器启动时自动执行
```

### 3. 验证

```bash
curl http://localhost:8000/health   # 健康检查
curl http://localhost:8000/ready    # 深度就绪检查（含 DB 连通性）
```

### 4. 前端（开发模式）

```bash
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

### 5. Chrome 扩展

1. 打开 `chrome://extensions`，启用开发者模式
2. 加载已解压的扩展 → 选择 `chrome-extension/` 目录
3. 打开美团商家后台，扩展自动注入客服助手面板
4. 打开 1688/拼多多商品页，点击「📤 导入AI店长」一键上架

详见 [chrome-extension/README.md](chrome-extension/README.md)

## API 端点

### 客服

| 端点 | 说明 |
|------|------|
| `POST /api/customer-service/chat` | AI 客服对话 |
| `POST /api/customer-service/chat/stream` | 流式对话 |
| `GET /api/customer-service/sessions` | 会话列表 |
| `GET /api/customer-service/metrics` | 效果指标（响应时间/接管率） |
| `POST /api/customer-service/feedback` | 回复反馈（采纳/编辑/忽略） |

### 上架

| 端点 | 说明 |
|------|------|
| `POST /api/listing/create` | 创建上架任务 |
| `POST /api/listing/batch` | 批量上架 |
| `GET /api/listing/{id}/status` | 进度查询 |
| `GET /api/listing/{id}` | 完整详情 |
| `GET /api/listing` | 上架列表 |

### 系统

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /ready` | 深度就绪检查（DB/Neo4j/Redis） |
| `GET /api/dashboard/overview` | 运营概览 |

## 项目结构

```
src/
├── main.py                    # FastAPI 入口
├── agents/
│   ├── customer_service/      # 客服 Agent
│   │   ├── nodes.py           # 主编排（chat 函数）
│   │   ├── pipeline.py        # LangGraph 5 步管线
│   │   ├── fast_path.py       # 快速秒回
│   │   ├── intent.py          # 意图识别
│   │   ├── search.py          # 混合检索 + Reranker
│   │   └── compliance.py      # 合规过滤
│   ├── listing/               # 上架 Agent
│   │   ├── nodes.py           # Parser→Matcher→Filler→Compliance
│   │   └── graph.py           # LangGraph 图定义
│   └── alert/                 # 预警 Agent
├── compliance/                # 共享合规规则（医疗器械）
├── services/                  # 业务服务（cs_metrics 等）
├── api/                       # FastAPI 路由
├── db/                        # 数据库连接（postgres/neo4j/redis）
└── skills/                    # Skills Layer

chrome-extension/              # Chrome 扩展
├── content_script.js          # 美团客服消息拦截
├── listing_content_script.js  # 1688/拼多多商品提取
├── background.js              # Service Worker
└── popup.html/js              # 配置面板

frontend/                      # Next.js 管理后台
migrations/                    # 数据库迁移（自动执行）
scripts/                       # 运维脚本
```

## 部署

### CI/CD（GitHub Actions）

- **Backend CI**: ruff lint + syntax check + Docker build test
- **Frontend CI**: TypeScript check + ESLint + Next.js build
- **Deploy**: Docker build → zstd 流式传输 → VPS 自动部署

Push to `main` → 自动检测变更区域 → 按需部署前端（Vercel）/ 后端（VPS）。

### 生产环境

```bash
# VPS 上的 docker-compose.yml 已通过 CI 自动同步
# Migration 在容器启动时自动执行
# 健康检查：CI 部署后自动验证 /health 端点
```

## 配置

| 环境变量 | 必填 | 说明 |
|---------|------|------|
| `OPENROUTER_API_KEY` | 是* | OpenRouter API Key |
| `ANTHROPIC_API_KEY` | 是* | Anthropic API Key（二选一） |
| `DATABASE_URL` | 否 | PostgreSQL 连接串（Docker 自动配置） |
| `NEO4J_URI` | 否 | Neo4j Bolt 地址（Docker 自动配置） |
| `REDIS_URL` | 否 | Redis 连接 URL（Docker 自动配置） |
| `CS_USE_PIPELINE` | 否 | 客服 LangGraph 管线开关（默认 `true`） |
| `CS_CONFIDENCE_LOW` | 否 | 低置信度阈值，自动转人工（默认 `0.4`） |
| `CS_CONFIDENCE_MED` | 否 | 中置信度阈值，标记需审核（默认 `0.6`） |
| `ALERT_WEBHOOK_URL` | 否 | 飞书告警 Webhook URL |

## License

Proprietary — All rights reserved.
