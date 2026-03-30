# API 端点审计报告

- 项目：`AI-Shopkeeper`
- 审计时间：2026-03-30 (UTC)
- 审计范围：`frontend/**/*.ts(x)` + `frontend/lib/api.ts` vs `src/api/*.py`

## 方法

1. 收集前端直接调用：`fetchAPI(...)`、`fetch('/api/...')`、页面内 `/api/...` 链接。
2. 同时纳入 `frontend/lib/api.ts` 里定义的 API 路径（按要求检查）。
3. 收集后端 `@router.get/post/put/delete/patch` 端点并按前缀还原完整路径。
4. 对比后：
   - 对「部分使用」文件：在未被前端调用端点上方加 `# UNUSED: no frontend caller`
   - 对「确认无用且未注册」文件：删除文件

---

## 已执行变更

### A) 已删除（确认幽灵 API 文件）

> 这两个文件在 `src/main.py` 中未注册、且前端无调用，属于明确死代码。

- `src/api/pricing_intelligence.py`（已删除）
- `src/api/selection_intelligence.py`（已删除）

### B) 已标注 UNUSED（部分使用文件）

以下文件存在“部分端点被前端调用，部分未被调用”，已对未调用端点逐一标注：

- `src/api/alerts.py`（4个未调用）
- `src/api/bundles.py`（8个未调用）
- `src/api/competitors.py`（5个未调用）
- `src/api/customer_service.py`（7个未调用）
- `src/api/dashboard.py`（5个未调用）
- `src/api/insights.py`（2个未调用）
- `src/api/inventory.py`（5个未调用）
- `src/api/knowledge.py`（7个未调用）
- `src/api/listing.py`（5个未调用）
- `src/api/orders.py`（6个未调用）
- `src/api/pricing.py`（2个未调用）
- `src/api/products.py`（15个未调用）
- `src/api/selection.py`（3个未调用）

---

## 全文件级“前端未调用”候选（本轮保守保留）

> 按“有疑问保留”原则，本轮未删除以下文件（尽管前端未调用）。它们可能仍被外部系统、运维流程或后续功能使用。

- `src/api/ab_testing.py`
- `src/api/boss_assistant.py`
- `src/api/chat.py`
- `src/api/feedback.py`
- `src/api/metrics_api.py`
- `src/api/replenishment.py`
- `src/api/stores.py`
- `src/api/sync_receiver.py`
- `src/api/sync_status.py`
- `src/api/system.py`

---

## 受保护端点检查

按要求，以下端点未删除：

- `/health`, `/ready`（系统端点）
- `/api/sync/ingest`（Chrome 扩展用）
- `/api/manual-import/*`（手动上传用）
- `/api/auth/*`（认证用）

---

## 结果摘要

- 删除死文件：2
- 标注未调用端点：74（分布在13个“部分使用”文件中）
- 保护性保留全文件候选：10

本次改动以“可审计、可回滚、低风险”为优先：
- 明确死代码直接删除
- 有潜在外部调用风险的仅做 `UNUSED` 标注，不破坏行为
