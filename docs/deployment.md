# 部署文档

## 架构

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Vercel    │     │   VPS        │     │  美团/QNH   │
│  (前端)     │────▶│ (后端+采集)   │────▶│  (数据源)    │
│  Next.js    │     │  Docker      │     │             │
└─────────────┘     └──────────────┘     └─────────────┘
                         │
                    ┌────┴────┐
                    │PostgreSQL│
                    │  Redis   │
                    │  Neo4j   │
                    └─────────┘
```

- **前端**: Vercel (Next.js, 自动部署)
- **后端**: VPS `192.144.227.205` Docker Compose
- **CI/CD**: GitHub Actions push to main → 自动部署

## VPS 部署

### 前置条件

- Docker + Docker Compose
- 至少 4GB 内存（Chromium + PyTorch）
- 开放 8000 端口

### 首次部署

```bash
# 1. 创建目录
mkdir -p /opt/aishop

# 2. 克隆代码
git clone https://github.com/Ken-LiuL/AI-Shopkeeper.git /opt/aishop/repo

# 3. 配置环境变量
cp /opt/aishop/repo/.env.example /opt/aishop/.env
vi /opt/aishop/.env  # 填写必要配置

# 4. 复制 docker-compose
cp /opt/aishop/repo/docker-compose.yml /opt/aishop/

# 5. 启动
cd /opt/aishop
docker compose up -d
```

### 必要环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | ✅ (docker 内自动) |
| `OPENROUTER_API_KEY` | LLM API Key | ✅ |
| `WM_POI_ID` | 美团店铺 ID | ✅ |
| `SYNC_MODE` | `local` 启用浏览器采集 | ✅ |
| `DISABLE_SYNC` | `false` 启用同步 | ✅ |
| `JWT_SECRET_KEY` | JWT 签名密钥 | ✅ |
| `REDIS_URL` | Redis 连接 | 可选 |

### CI/CD 自动部署

Push to `main` 触发 GitHub Actions:
1. 打包代码 → SCP 到 VPS
2. Docker build（利用 cache）
3. `docker compose up -d --force-recreate --no-deps app`
4. Health check

GitHub Secrets 需要:
- `VPS_SSH_KEY`: SSH 私钥
- `VPS_HOST`: VPS IP
- `VERCEL_TOKEN` / `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID`

## 数据采集激活

### 1. 提交美团 Cookie

登录 yiyao.meituan.com → 浏览器 F12 → Application → Cookies → 复制所有 Cookie

通过前端设置页提交，或直接调 API:

```bash
curl -X POST http://VPS_IP:8000/api/sync/cookie \
  -H "Content-Type: application/json" \
  -d '{"cookie_json": {"key1": "val1", ...}}'
```

### 2. 手动触发同步

```bash
curl -X POST http://VPS_IP:8000/api/sync/trigger
```

### 3. 查看同步状态

```bash
curl http://VPS_IP:8000/api/sync/status
```

## 定时任务调度（CST）

| 时间 | 任务 | 数据源 |
|------|------|--------|
| 01:30 | 商品预同步 | 美团买药 |
| 02:00 | 商品全量 | 美团买药 |
| 03:00 | QNH 全量 | 牵牛花 |
| 每小时 | 订单增量 | 美团买药 |
| 每 6h | 评价 + 退款 | 美团买药 |
| 04:00 | 关联购买 ETL | 本地 |
| 04:30 | 类目映射 ETL | 本地+QNH |
| 05:00 | 配送超时 ETL | 本地 |
| 06:00 | 统计指标 | 美团买药 |
| 07:00 | 日报 ETL | 本地 |
| 08:00 | 竞品采集 | H5 |
| 08:00 | 销售历史 ETL | 本地 |
| 08:30 | 评价分析 ETL | 本地 |
| 09:30 | 竞品变动 ETL | 本地 |
| 10:00 | FAQ 自动生成 | 本地 |
| 每周日 05:00 | 季节性 ETL | 本地 |
| 每周一 06:00 | 政策爬取 | 外部 |

## 故障排查

### 后端不响应

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker logs aishop-app --tail 100 -f

# 重启
docker compose restart app
```

### 同步失败

```bash
# 查看同步日志
docker logs aishop-app 2>&1 | grep -i "sync\|error"

# 常见原因:
# 1. Cookie 过期 → 重新提交
# 2. API 路径变更 → 查看日志中的 HTTP 状态码
# 3. 数据库连接失败 → docker compose restart postgres
```

### Docker Build 失败

```bash
# 清理旧镜像释放空间
docker system prune -f

# 手动构建（查看详细错误）
cd /opt/aishop/repo && docker build -t aishop-app:latest .
```

### 内存不足

```bash
# 查看内存使用
docker stats --no-stream

# app 容器限制 4GB，如果 OOM:
# 1. 增加 swap
# 2. 或减少 Chromium 并发
```
