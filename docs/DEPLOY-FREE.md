# 免费部署指南：Render + Vercel

## 架构

```
用户 → Vercel (Next.js 前端) → Render (FastAPI 后端)
                                  ├── PostgreSQL (pgvector)
                                  └── Redis
```

## 费用

| 服务 | 方案 | 费用 |
|------|------|------|
| Render | Free | 免费 |
| Vercel | Hobby | 免费 |

---

## 一、后端部署到 Render

### 方式 A：Blueprint 一键部署（推荐）

1. 登录 [render.com](https://render.com)（支持 GitHub 登录）
2. **New** → **Blueprint**
3. 连接 GitHub，选择 `AI-Shopkeeper` 仓库
4. Render 自动读取 `render.yaml`，创建：
   - Web Service（FastAPI 后端）
   - PostgreSQL 数据库
   - Redis 缓存
5. 点击 **Apply** 等待部署完成

### 方式 B：手动创建

1. **New** → **Web Service** → 连接 GitHub repo
2. **Runtime**: Docker
3. **Region**: Singapore
4. **Plan**: Free
5. 添加环境变量：
   ```
   VECTOR_STORE=postgres
   OPENROUTER_API_KEY=<your-key>
   OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
   OPENROUTER_MODEL=anthropic/claude-sonnet-4
   ```
6. 单独创建 PostgreSQL 和 Redis，将连接 URL 填入 `DATABASE_URL` 和 `REDIS_URL`

### 获取后端 URL

部署完成后，Render 会分配类似 `https://ai-store-manager-xxxx.onrender.com` 的 URL。

---

## 二、前端部署到 Vercel

1. 登录 [vercel.com](https://vercel.com)
2. **New Project** → 选择 GitHub repo → Root Directory 设为 `frontend`
3. 添加环境变量：
   ```
   NEXT_PUBLIC_API_URL=https://ai-store-manager-xxxx.onrender.com
   ```
4. 部署

---

## 三、GitHub Actions 自动部署（可选）

1. 在 Render Dashboard → Web Service → **Settings** → **Deploy Hook** 复制 URL
2. 在 GitHub repo → **Settings** → **Secrets** 添加：
   - `RENDER_DEPLOY_HOOK_URL`: Render deploy hook URL
   - `VERCEL_TOKEN` / `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID`: Vercel 相关

Push 到 main 分支会自动触发部署。

---

## 注意事项

- Render 免费层 512MB RAM，已配置单 worker
- 免费层服务 15 分钟无请求会休眠，首次请求需 ~30s 冷启动
- PostgreSQL 免费层 90 天后过期，需手动续期
- Redis 免费层 25MB 内存限制
