# SPEC vs 落地差距追踪

> 基于 SPEC.md 的设计 vs 当前代码实现，2026-03-30 审查

## 状态图标
- ✅ 已修复
- 🔧 进行中
- 📋 计划中
- ❌ 延后/放弃

---

## P0 安全问题

| # | 问题 | 状态 | 备注 |
|---|------|------|------|
| S1 | API Key 明文泄露到 Git | ✅ | `.env.production` 已删，`llm.py` 硬编码已移除 |
| S2 | admin/admin 默认密码 | ✅ | 改为 `ADMIN_PASSWORD` 环境变量，未设置时自动生成随机密码 |
| S3 | Neo4j 无认证 | ✅ | `docker-compose.yml` 已启用 `neo4j/changeme123` |
| S4 | CORS 全开 | ✅ | localhost 仅 dev 环境允许，methods/headers 收紧 |
| S5 | Git history 中的泄露 Key | 📋 | 需要 `git filter-branch` 或 BFG Repo-Cleaner |

## 数据采集清理

| # | 问题 | 状态 | 备注 |
|---|------|------|------|
| D1 | anti_detect 模块 | ✅ | 整个目录已删除 (1890 行) |
| D2 | sync 采集器 | ✅ | 22 个文件已删除 (~6000 行) |
| D3 | ActionBook/MeituanH5 Skills | ✅ | 2 个文件已删除 (~2250 行) |
| D4 | 采集 API (sync.py/store_config.py) | ✅ | 已删除 |
| D5 | Dockerfile Chromium/Xvfb/PyTorch | ✅ | 已移除，镜像大幅瘦身 |
| D6 | 调度器残留采集任务 | ✅ | 注册表已清理 |

## SPEC 功能差距

### Selection Agent (SPEC 第三部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| SEL1 | 4 阶段 LangGraph 流程 | ✅ 已实现 | graph.py 完整 |
| SEL2 | 6 个 Sub-Agent | ✅ 已实现 | 全部有节点实现 |
| SEL3 | Self-Reflection (Scorer) | ✅ 已实现 | `call_tool_with_reflection` 接入 |
| SEL4 | Supplier 双渠道比价 | ✅ | 改为从 DB 查询竞品/成本数据 |
| SEL5 | Tool Use 结构化输出 | ✅ 已实现 | 7 个 Tool Schema 定义完整 |

### CustomerService Agent (SPEC 第四部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| CS1 | Intent Sub-Agent | ✅ | `intent.py` 已拆出且被 pipeline 使用 |
| CS2 | Hybrid Search 管线 | ✅ | `search.py` 已拆出且被 pipeline 使用 |
| CS3 | Reranker (BGE Top-5) | ✅ 已实现 | 代码在，fallback 到 RRF |
| CS4 | GraphRAG 子图丰富 | ✅ 已实现 | 依赖 Neo4j 在线 |
| CS5 | Reply Sub-Agent | 📋 | 目前内联在 chat()，计划拆出 `reply.py` |
| CS6 | Fast-Path 秒回 | ✅ | SPEC 没要求但已实现并拆出 `fast_path.py` |
| CS7 | LangGraph 状态机 | ❌ 延后 | 当前函数编排模式工作正常，LangGraph 非必要 |
| CS8 | nodes.py 模块化 | ✅ | Phase 1+2 完成，内联实现已替换为子模块调用 |

### Alert Agent (SPEC 第五部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| ALT1 | Prophet 时序检测 | ✅ 已实现 | |
| ALT2 | 规则检测 | ✅ 已实现 | |
| ALT3 | Isolation Forest | ❌ 延后 | Tool Schema 有但代码未实现，投入产出比低 |
| ALT4 | RootCause Sub-Agent | ✅ 已实现 | |
| ALT5 | Action + Self-Reflection | ✅ 已实现 | |

### Bundle Agent (SPEC 第六部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| BDL1 | OrderMining → Scene → Pricing | ✅ 已实现 | |
| BDL2 | GraphRAG 增强 | ✅ 已实现 | |

### Listing Agent (SPEC 第七部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| LST1 | Parser → Matcher → Filler → Compliance | ✅ 已实现 | |
| LST2 | URL 解析 (1688/拼多多) | ❌ 延后 | 依赖已删的 ActionBook，改为手动导入 |

### 技术增强层 (SPEC 第二部分)

| # | SPEC 要求 | 状态 | 备注 |
|---|-----------|------|------|
| TE1 | Tool Use 结构化输出 | ✅ 已实现 | 全部 Agent |
| TE2 | Self-Reflection | ✅ 已实现 | 4 个 Agent |
| TE3 | Hybrid Search | ✅ 已实现 | CS 中 |
| TE4 | GraphRAG | ✅ 已实现 | 多 Agent |
| TE5 | Reranker | ✅ 已实现 | BGE CrossEncoder |
| TE6 | Prophet | ✅ 已实现 | Alert 中 |
| TE7 | Isolation Forest | ❌ 延后 | |

---

## 后续优先级

1. **Git history 清理** — 用 BFG 清除泄露的 API Key
2. **模型优化** — 关键决策路径评估是否需要回 Claude
3. **前端精简** — 17 页砍到 5 核心页面

---

## 2026-03-31 新增功能

### 客服 Agent 增强
| # | 功能 | 状态 | 备注 |
|---|------|------|------|
| NEW1 | 置信度兜底 + 自动转人工 | ✅ | confidence < 0.4 强制转人工，0.4-0.6 标记需人工 |
| NEW2 | 医疗器械合规过滤 | ✅ | 16 条硬拦截 + 6 条软替换，独立模块 compliance.py |
| NEW3 | 效果量化埋点 | ✅ | cs_metrics 表 + /metrics API，记录响应时间/接管率 |
| NEW4 | 基础监控告警 | ✅ | /health + /ready + 飞书 webhook |

### 智能上架
| # | 功能 | 状态 | 备注 |
|---|------|------|------|
| NEW5 | 上架前端页面 | ✅ | /listing 分步表单 + 可编辑结果 |
| NEW6 | API 进度追踪 | ✅ | 每步更新 DB，轮询进度 |
| NEW7 | 批量上架 | ✅ | POST /api/listing/batch |
| NEW8 | 共享合规规则 | ✅ | src/compliance/ 包，客服+上架共用 |
| NEW9 | Chrome 扩展导入 | ✅ | 1688/拼多多一键导入 |

### 工程质量
| # | 改进 | 状态 | 备注 |
|---|------|------|------|
| NEW10 | Sidebar 精简 | ✅ | 隐藏空壳页面，保留核心功能 |
| NEW11 | CS nodes.py 技术债清理 | ✅ | 删除重复代码，使用子模块调用 |
| NEW12 | Migration 自动化 | ✅ | 移入 postgres/ 目录，部署时自动执行 |
