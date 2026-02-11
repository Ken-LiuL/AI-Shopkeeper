# Demo 测试结果

**日期:** 2026-02-12 01:40 CST  
**测试人:** QA Agent  
**环境:** macOS arm64, Python 3.13, venv `.venv/`

## 环境搭建

- ✅ venv 存在，`pip install -e .` 成功
- ✅ 所有依赖安装成功 (langgraph, anthropic, fastapi, etc.)
- ✅ `.env` 加载正常

## Bug 修复

### 1. Langfuse `.trace()` 调用失败
- **文件:** `src/agents/llm.py:96`
- **原因:** Langfuse 在 `config/system.yaml` 中 `enabled: true`，但没有配置 `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`。新版 langfuse SDK 初始化时不报错，但调用 `.trace()` 时抛 `AttributeError`。
- **修复:** 在 `langfuse.trace()` 调用处加了 try/except，失败时 gracefully 降级为无追踪模式。
- **状态:** ✅ 已修复

## Demo 运行结果

### `scripts/demo_selection.py`

- **状态:** ❌ 失败 — API 余额不足
- **现象:** 脚本框架正常运行，mock 数据采集成功（5 热搜词、3 排行榜、3 竞品店铺），但所有 Claude API 调用返回 400:
  ```
  Your credit balance is too low to access the Anthropic API.
  Please go to Plans & Billing to upgrade or purchase credits.
  ```
- **失败节点:** market_analysis, competitor_analysis, inventory_analysis, seasonal_analysis, gap_identification, scorer — 全部 6 个 LLM 节点
- **Graph 行为:** 错误被正确捕获并累积到 `errors[]`，不会崩溃。每个节点有 retry（看到重复错误），最终 graceful 返回空结果。

### `scripts/demo_customer_service.py`

- **状态:** ⏭ 未运行（同样的 API Key 问题，跳过）

## Token 消耗

- 0 tokens（所有请求被拒绝，未消耗）

## 阻塞问题

| # | 问题 | 严重性 | 状态 |
|---|------|--------|------|
| 1 | **Anthropic API Key 余额为零** | 🔴 Blocker | 需充值 |
| 2 | Langfuse 未配置但默认 enabled | 🟡 Medium | ✅ 已修复 |

## 下一步

1. **充值 Anthropic API 账户**（或更换有效 Key），然后重跑两个 demo
2. 考虑在 `config/system.yaml` 中将 `langfuse.enabled` 默认改为 `false`
3. Graph 的错误重试逻辑看起来会无限重试（错误重复出现很多次），建议加 max retry 限制
