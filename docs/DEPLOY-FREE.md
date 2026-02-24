# 免费部署指南：Railway + Vercel

## 架构

```
用户 → Vercel (Next.js 前端) → Railway (FastAPI 后端)
                                  ├── PostgreSQL (pgvector)
                                  └── Redis
```

## 费用

| 服务 | 方案 | 费用 |
|------|------|------|
| Railway | Trial/Hobby | 免费 $5/月额度 |
| Vercel | Hobby | 免费 |

---

## 一、后端部署到 Railway

### 1. 创建项目

1. 登录 [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo
3. 选择 `ai-store-manager` 仓库（根目录即后端）

### 2. 添加数据库插件

在 Railway 项目中：
- **+ New** → **Database** → **PostgreSQL** （自动注入 `DATABASE_URL`, `PGHOST` 等）
- **+ New** → **Database** → **Redis** （自动注入 `REDIS_URL`）

### 3. 设置环境变量

在 Railway Dashboard → 后端服务 → **Variables** 中添加：

```
VECTOR_STORE=postgres
OPENROUTER_API_KEY=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
NEO4J_URI=
NEO4J_USER=
NEO4J_PASSWORD=
PROMETHEUS_ENABLED=false
```

> PostgreSQL 和 Redis 的连接信息由插件自动注入，**无需手动设置**。

### 4. 确认部署

- Railway 会自动检测 `Dockerfile` 并构建
- 健康检查路径已配置为 `/health`
- 部署成功后，在 Settings → Networking → **Generate Domain** 获取公开 URL

---

## 二、前端部署到 Vercel

### 1. 导入项目

1. 登录 [vercel.com](https://vercel.com)
2. **Add New** → **Project** → 导入 GitHub 仓库
3. **Root Directory** 设为 `frontend`
4. Framework 自动检测为 Next.js

### 2. 设置环境变量

在 Vercel → Project Settings → **Environment Variables** 中添加：

```
NEXT_PUBLIC_API_URL=https://你的railway后端域名
```

例如：`https://ai-store-manager-production.up.railway.app`

### 3. 部署

点击 Deploy，完成。

---

## 三、部署后验证

1. 访问 Railway 后端：`https://你的域名/health` → 应返回 `{"status":"ok"}`
2. 访问 Vercel 前端：打开首页，检查数据加载

---

## 四、注意事项

- **Railway 免费额度**：$5/月，含 500 小时执行时间。休眠不计费。超出需升级。
- **PostgreSQL pgvector**：首次部署后需手动执行 `CREATE EXTENSION vector;`（可通过 Railway 的 psql 连接）
- **Neo4j 已移除**：代码中 Neo4j 初始化会 graceful fallback，不影响运行
- **CORS**：后端已配置 `allow_origins=["*"]`，生产环境建议改为 Vercel 域名
- **前端 API 代理**：`vercel.json` 中的 rewrites 可选用，也可直接通过 `NEXT_PUBLIC_API_URL` 跨域访问
