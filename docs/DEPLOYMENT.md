# 部署文档

## 环境要求

| 组件 | 最低版本 | 推荐 |
|------|---------|------|
| Python | 3.11 | 3.11 |
| Docker | 24+ | 最新 |
| Docker Compose | v2 | 最新 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 20 GB | 50 GB |
| CPU | 2 核 | 4 核 |

### 端口使用

| 端口 | 服务 |
|------|------|
| 8000 | FastAPI 应用 |
| 5432 | PostgreSQL |
| 7474 | Neo4j Browser (HTTP) |
| 7687 | Neo4j Bolt |
| 6379 | Redis |
| 9090 | Prometheus 指标端点 |
| 3000 | 前端 / Langfuse（按需） |

---

## Docker Compose 部署

### 开发环境

```bash
# 1. 启动基础设施
docker compose up -d

# 2. 验证服务健康
docker compose ps
# 或
make health-check

# 3. 初始化数据库
make migrate-pg
make migrate-neo4j

# 4. 种子数据
make seed
python scripts/seed_knowledge_graph.py
python scripts/seed_faq.py

# 5. 启动应用（开发模式，auto-reload）
make dev
```

### 生产环境

```bash
# 1. 准备 .env 文件
cp .env.example .env
# 编辑 .env，设置生产密码和 API Key

# 2. 启动全部服务（含应用容器）
docker compose up -d

# 应用容器默认注释，取消注释 docker-compose.yml 中的 app service
# 或创建 docker-compose.prod.yml:
```

**docker-compose.prod.yml**:

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      NEO4J_URI: bolt://neo4j:7687
      REDIS_URL: redis://redis:6379
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 2G
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## 生产环境配置

### Nginx 反向代理

```nginx
upstream app_backend {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name ai-store.example.com;

    ssl_certificate     /etc/ssl/certs/fullchain.pem;
    ssl_certificate_key /etc/ssl/private/privkey.pem;

    # 安全头
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header Strict-Transport-Security "max-age=31536000" always;

    # API
    location /api/ {
        proxy_pass http://app_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 长时间运行的 Agent 任务
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Swagger 文档
    location /docs {
        proxy_pass http://app_backend;
    }
    location /openapi.json {
        proxy_pass http://app_backend;
    }

    # 健康检查（内部）
    location /health {
        proxy_pass http://app_backend;
        access_log off;
    }

    # 前端静态文件
    location / {
        root /var/www/ai-store/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}

server {
    listen 80;
    server_name ai-store.example.com;
    return 301 https://$host$request_uri;
}
```

### Supervisor（非 Docker 部署时）

```ini
[program:ai-store-manager]
command=/path/to/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2
directory=/path/to/ai-store-manager
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/ai-store/error.log
stdout_logfile=/var/log/ai-store/access.log
environment=
    POSTGRES_HOST="localhost",
    POSTGRES_PASSWORD="secure_password",
    OPENROUTER_API_KEY="sk-xxx",
    LLM_PROVIDER="openrouter"
```

---

## 数据库迁移

### PostgreSQL

迁移文件位于 `migrations/postgres/`：

| 文件 | 说明 |
|------|------|
| `001_initial.sql` | 核心表：products, orders, order_items, alerts, bundles, sales_history 等 |
| `002_sync_tables.sql` | 数据同步表：sync_state, sync_logs 等 |
| `003_api_support_tables.sql` | API 支持表：selection_runs, bundle_tasks, listings 等 |

```bash
# 全部迁移
make migrate-pg
# 或手动
psql -h localhost -U postgres -d ai_store -f migrations/postgres/001_initial.sql
psql -h localhost -U postgres -d ai_store -f migrations/postgres/002_sync_tables.sql
psql -h localhost -U postgres -d ai_store -f migrations/postgres/003_api_support_tables.sql
```

使用 `scripts/migrate.py` 自动执行：

```bash
python scripts/migrate.py --postgres-only  # 仅 PostgreSQL
python scripts/migrate.py --neo4j-only     # 仅 Neo4j
python scripts/migrate.py                   # 全部
```

### Neo4j

迁移文件位于 `migrations/neo4j/001_schema.cypher`：
- 约束（Product、Population、Scenario、FAQ 唯一性）
- 向量索引（Product.embedding、FAQ.question_embedding，1024d，cosine）
- 全文索引（Product、FAQ 文本字段）
- 种子数据（Population、Scenario 节点）

```bash
make migrate-neo4j
# 或手动
cat migrations/neo4j/001_schema.cypher | cypher-shell -a bolt://localhost:7687
```

---

## 监控配置

### Prometheus

应用内置 `prometheus_client`，在 9090 端口暴露指标。

**核心指标**:

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `llm_tokens_total` | Counter | model, type | LLM Token 消耗 |
| `llm_request_duration_seconds` | Histogram | model | LLM 请求耗时 |
| `agent_execution_duration_seconds` | Histogram | agent_type | Agent 执行耗时 |
| `agent_execution_total` | Counter | agent_type, status | Agent 执行次数 |
| `alerts_triggered_total` | Counter | alert_type, severity | 预警触发次数 |
| `alerts_active` | Gauge | severity | 当前活跃预警数 |
| `customer_service_requests_total` | Counter | intent, route | 客服请求量 |
| `db_query_duration_seconds` | Histogram | db, operation | 数据库查询耗时 |

**Prometheus 配置** (`prometheus.yml`):

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'ai-store-manager'
    static_configs:
      - targets: ['localhost:9090']
```

### Grafana 仪表盘

推荐面板：

1. **LLM 成本监控**：按模型统计 token 消耗，计算日/周/月费用
2. **Agent 性能**：执行耗时 P50/P95/P99，成功/失败率
3. **预警概览**：活跃预警数、各级别分布、日趋势
4. **客服指标**：请求量、意图分布、转人工比例
5. **系统健康**：数据库查询耗时、连接池使用率

### Langfuse 追踪

每次 LLM 调用自动记录到 Langfuse：

- Trace：完整调用链
- Generation：单次 LLM 调用的 input/output/tokens/duration
- 支持按 trace_name 分类查看

配置：在 `.env` 中设置 `LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY`。

---

## 备份策略

### PostgreSQL

```bash
# 每日备份（crontab）
0 2 * * * pg_dump -h localhost -U postgres ai_store | gzip > /backup/pg/ai_store_$(date +\%Y\%m\%d).sql.gz

# 保留 30 天
0 3 * * * find /backup/pg/ -name "*.sql.gz" -mtime +30 -delete

# 恢复
gunzip < /backup/pg/ai_store_20260212.sql.gz | psql -h localhost -U postgres -d ai_store
```

### Neo4j

```bash
# 停机备份
neo4j-admin database dump neo4j --to-path=/backup/neo4j/

# 在线备份（Enterprise 版）
neo4j-admin database backup neo4j --to-path=/backup/neo4j/

# 恢复
neo4j-admin database load neo4j --from-path=/backup/neo4j/neo4j.dump --overwrite-destination
```

### Redis

Redis 配置了 `volumes` 持久化，默认使用 RDB 快照。

```bash
# 手动触发快照
redis-cli BGSAVE

# 备份 RDB 文件
cp /var/lib/redis/dump.rdb /backup/redis/dump_$(date +%Y%m%d).rdb
```

### 备份策略总结

| 数据库 | 频率 | 保留 | 方式 |
|--------|------|------|------|
| PostgreSQL | 每日 02:00 | 30 天 | pg_dump + gzip |
| Neo4j | 每日 03:00 | 14 天 | neo4j-admin dump |
| Redis | 随 RDB 自动 | 7 天 | 文件拷贝 |

---

## 故障排查

### 常见问题

**Q: 启动时 Neo4j 健康检查一直失败？**

Neo4j 启动较慢（30-60s），等待 healthcheck 通过即可。如超过 2 分钟，检查：
```bash
docker logs ai-store-manager-neo4j-1
```

**Q: Prophet 相关功能报错？**

Prophet 依赖 `cmdstanr`，首次安装较慢。确保 Dockerfile 构建成功，或本地：
```bash
pip install prophet
```

**Q: LLM 调用超时？**

检查 `LLM_PROVIDER` 和对应 API Key。OpenRouter 偶尔有延迟，可临时切换：
```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-xxx
```
