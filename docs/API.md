# API 文档

**Base URL**: `http://localhost:8000`

所有接口返回统一格式：

```json
{
  "success": true,
  "data": { ... },
  "message": ""
}
```

分页接口返回：

```json
{
  "success": true,
  "data": [ ... ],
  "total": 100,
  "page": 1,
  "page_size": 20
}
```

异步任务接口返回：

```json
{
  "success": true,
  "task_id": "sel_abc123def456",
  "message": "Task started"
}
```

---

## 认证

当前版本无认证要求（内网部署）。生产环境建议通过 Nginx 添加 Basic Auth 或 JWT 中间件。

---

## 错误码

| HTTP 状态码 | 含义 | 示例 |
|-------------|------|------|
| 200 | 成功 | — |
| 201 | 创建成功 | 新增商品 |
| 400 | 请求参数错误 | `{"success": false, "message": "Invalid input"}` |
| 404 | 资源不存在 | `{"success": false, "message": "Product 'xxx' not found"}` |
| 500 | 内部错误 | `{"success": false, "message": "Internal server error"}` |

---

## 系统

### GET /health

基本存活检查。

**响应**:
```json
{"status": "ok"}
```

### GET /ready

深度就绪检查，验证 PostgreSQL / Neo4j / Redis 连接。

**响应**:
```json
{
  "status": "ok",
  "postgres": true,
  "neo4j": true,
  "redis": true
}
```

降级时 `status` 为 `"degraded"`，对应服务为 `false`。

---

## 选品 (Selection)

### POST /api/selection/run

触发一次选品分析（异步执行）。

**请求**:
```json
{
  "keywords": ["血压计", "体温计"],
  "categories": ["医疗器械"]
}
```

所有字段可选。

**响应**:
```json
{
  "success": true,
  "task_id": "sel_a1b2c3d4e5f6",
  "message": "Selection run started"
}
```

### GET /api/selection/runs

获取选品运行记录（最近 50 条）。

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "run_id": "sel_a1b2c3d4e5f6",
      "status": "completed",
      "keywords": ["血压计"],
      "categories": ["医疗器械"],
      "result_count": 20,
      "created_at": "2026-02-12T06:00:00Z"
    }
  ]
}
```

### GET /api/selection/runs/{run_id}

获取单次运行详情（含推荐结果和原始 Agent 状态）。

**响应**:
```json
{
  "success": true,
  "data": {
    "run_id": "sel_a1b2c3d4e5f6",
    "status": "completed",
    "keywords": ["血压计"],
    "categories": ["医疗器械"],
    "result_count": 20,
    "created_at": "2026-02-12T06:00:00Z",
    "recommendations": [
      {
        "keyword": "电子血压计",
        "score": 85.5,
        "scores_detail": { "market_heat": 90, "competition_gap": 80 },
        "recommended_action": "strong_recommend",
        "supplier_links": { "alibaba": "https://...", "pdd": "https://..." }
      }
    ],
    "raw_state": { ... }
  }
}
```

### GET /api/selection/recommendations

获取最新一次完成的选品推荐。

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "keyword": "电子血压计",
      "score": 85.5,
      "recommended_action": "strong_recommend"
    }
  ]
}
```

---

## 客服 (Customer Service)

### POST /api/cs/chat

发送客服消息并获取 AI 回复。

**请求**:
```json
{
  "session_id": "user_001_session_1",
  "message": "老人用什么血压计好？",
  "conversation_history": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "您好，请问有什么可以帮您？"}
  ]
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "session_id": "user_001_session_1",
    "reply": "亲，推荐这款欧姆龙电子血压计 HEM-7121...",
    "intent": "product_recommendation",
    "sources": [
      {
        "product_id": "prod_001",
        "name": "欧姆龙电子血压计 HEM-7121",
        "score": 0.92,
        "suitable_for": ["老年人", "高血压患者"],
        "contraindicated_for": [{"population": "心律不齐患者", "reason": "建议使用水银血压计"}]
      }
    ]
  }
}
```

### GET /api/cs/sessions/{session_id}

获取会话历史（Redis 存储，7 天过期）。

**响应**:
```json
{
  "success": true,
  "data": {
    "session_id": "user_001_session_1",
    "messages": [
      {"role": "user", "content": "老人用什么血压计好？"},
      {"role": "assistant", "content": "亲，推荐...", "intent": "product_recommendation"}
    ]
  }
}
```

---

## 预警 (Alerts)

### POST /api/alerts/scan

触发一次预警扫描（异步执行）。

**响应**:
```json
{
  "success": true,
  "data": {
    "task_id": "scan_abc123",
    "message": "Alert scan started"
  }
}
```

### GET /api/alerts

查询预警列表。

**Query 参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `severity` | string | 筛选严重级别：`critical` / `warning` / `info` |
| `status` | string | 筛选状态：`pending` / `acknowledged` / `resolved` / `ignored` |
| `product_id` | string | 筛选商品 ID |

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "alert_id": "alert_001",
      "product_id": "prod_001",
      "alert_type": "sales_decline",
      "severity": "warning",
      "detection_method": "prophet",
      "metrics": {"actual": 15, "predicted": 45, "deviation": -66.7},
      "root_cause": "竞品降价20%导致客户流失",
      "recommended_action": "建议将价格从¥299调至¥269",
      "status": "pending",
      "created_at": "2026-02-12T08:30:00Z"
    }
  ]
}
```

### GET /api/alerts/{alert_id}

获取单条预警详情。

### PATCH /api/alerts/{alert_id}

更新预警状态。

**请求**:
```json
{
  "status": "acknowledged"
}
```

`status` 可选值：`acknowledged` / `resolved` / `ignored`。

---

## 套餐 (Bundles)

### POST /api/bundles/generate

触发套餐生成（异步执行）。

**请求**:
```json
{
  "min_support": 0.01,
  "min_confidence": 0.3,
  "max_bundles": 10
}
```

所有字段可选。

**响应**:
```json
{
  "success": true,
  "task_id": "bnd_abc123",
  "message": "Bundle generation started"
}
```

### GET /api/bundles

获取套餐列表（排除已删除）。

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "bundle_id": "bnd_001",
      "name": "感冒护理套装",
      "tagline": "一站配齐，居家必备",
      "products": [{"product_id": "prod_001", "name": "体温计"}, ...],
      "original_price": 89.00,
      "bundle_price": 75.90,
      "discount_percent": 14.72,
      "confidence": 0.45,
      "lift": 2.1,
      "status": "active",
      "created_at": "2026-02-12T23:00:00Z"
    }
  ]
}
```

### PATCH /api/bundles/{bundle_id}

更新套餐（名称、状态、价格）。

**请求**:
```json
{
  "status": "inactive",
  "bundle_price": 69.90
}
```

### DELETE /api/bundles/{bundle_id}

软删除套餐（`status` → `deleted`）。

---

## 上架 (Listing)

### POST /api/listing/parse

快速解析商品链接，返回原始商品数据。

**请求**:
```json
{
  "url": "https://detail.1688.com/offer/xxx.html",
  "platform": "alibaba"
}
```

`platform`：`alibaba` 或 `pdd`。

**响应**:
```json
{
  "success": true,
  "data": {
    "title": "欧姆龙家用电子血压计...",
    "price": 128.00,
    "specs": [...],
    "images": [...],
    "supplier": {...}
  }
}
```

### POST /api/listing/create

创建上架任务（异步，包含解析→匹配→优化→合规校验全流程）。

**请求**:
```json
{
  "source_url": "https://detail.1688.com/offer/xxx.html",
  "platform": "alibaba",
  "raw_product_data": "",
  "overrides": {}
}
```

**响应**:
```json
{
  "success": true,
  "task_id": "lst_abc123",
  "message": "Listing creation started"
}
```

### GET /api/listing/{listing_id}

查询上架任务状态和结果。

**响应**:
```json
{
  "success": true,
  "data": {
    "listing_id": "lst_abc123",
    "status": "completed",
    "product_data": {
      "optimized_title": "欧姆龙血压计 上臂式智能语音 老人家用HEM-7121",
      "suggested_price": 299.00,
      "compliance": {"status": "pass", "warnings": []},
      "matched_standard": {...}
    },
    "created_at": "2026-02-12T10:00:00Z"
  }
}
```

---

## 商品 (Products)

### GET /api/products

分页查询商品列表。

**Query 参数**:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数（1-100） |
| `search` | string | — | 按名称/条码模糊搜索 |
| `status` | string | — | 筛选状态 |

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "product_id": "prod_001",
      "name": "欧姆龙电子血压计 HEM-7121",
      "barcode": "4975479409875",
      "category": "血压计",
      "brand": "欧姆龙",
      "cost_price": 128.00,
      "retail_price": 299.00,
      "stock": 50,
      "monthly_sales": 120,
      "status": "active"
    }
  ],
  "total": 85,
  "page": 1,
  "page_size": 20
}
```

### GET /api/products/{product_id}

获取商品详情。

### POST /api/products

创建商品。

**请求**:
```json
{
  "name": "欧姆龙电子血压计 HEM-7121",
  "barcode": "4975479409875",
  "category": "血压计",
  "brand": "欧姆龙",
  "description": "上臂式全自动智能语音播报",
  "cost_price": 128.00,
  "retail_price": 299.00,
  "stock": 50,
  "status": "active"
}
```

`name` 必填，其余可选。

### PUT /api/products/{product_id}

更新商品（部分更新）。

### GET /api/products/{product_id}/sales

获取商品近 90 天销量记录。

**响应**:
```json
{
  "success": true,
  "data": [
    {"date": "2026-02-11", "quantity": 8, "revenue": 2392.00},
    {"date": "2026-02-10", "quantity": 12, "revenue": 3588.00}
  ]
}
```

---

## 仪表盘 (Dashboard)

### GET /api/dashboard/overview

运营概览。

**响应**:
```json
{
  "success": true,
  "data": {
    "total_products": 85,
    "today_orders": 42,
    "pending_alerts": 3,
    "pending_tasks": 1
  }
}
```

### GET /api/dashboard/sales-trend

近 30 天销售趋势。

**响应**:
```json
{
  "success": true,
  "data": [
    {"date": "2026-02-11", "quantity": 156, "revenue": 45800.00},
    {"date": "2026-02-10", "quantity": 142, "revenue": 41200.00}
  ]
}
```

### GET /api/dashboard/top-products

近 30 天销量 TOP 10 商品。

**响应**:
```json
{
  "success": true,
  "data": [
    {
      "product_id": "prod_001",
      "name": "欧姆龙电子血压计 HEM-7121",
      "total_sales": 320,
      "revenue": 95680.00
    }
  ]
}
```
