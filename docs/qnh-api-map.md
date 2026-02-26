# 牵牛花 API 完整图谱

通过 Playwright 浏览器逆向抓包获取，2026-02-24。

## API 网关分类

### 1. goldengateway — 数据分析网关 (核心)
> ⚠️ 需要 mtgsig 签名，纯 HTTP 调用返回 403。必须在浏览器环境执行。

| 路径 | 方法 | 用途 |
|------|------|------|
| `/goldengateway/empower/generic/table/query` | POST | **通用数据查询** — 门店指标、热销商品、消费排行、订单趋势等 |
| `/goldengateway/empower/complexModule/queryTable` | POST | 复杂模块查询（多维度数据） |
| `/goldengateway/empower/homepage/channelDistributeList` | POST | 渠道分布（美团闪购/饿了么/京东到家占比） |
| `/goldengateway/empower/homepage/getMode` | POST | 首页显示模式 |
| `/goldengateway/poi/queryPoiTree` | POST | 门店树结构 |

### 2. /api/v1/, /api/v2/ — 基础业务 API
> ✅ Cookie 认证即可访问，无需 mtgsig。

| 路径 | 方法 | 用途 |
|------|------|------|
| `/api/v1/sac/account/auth` | POST | 账号认证/登录状态检查 |
| `/api/v1/isLogined` | GET | 登录状态检查 |
| `/api/v1/merchant/storeCategory/queryAll` | POST | 商品分类列表 |
| `/api/v1/merchant/spu/page` | POST | **SPU 分页列表（全量商品）** ⚠️ TODO: 需抓包验证 |
| `/api/v1/merchant/spu/detail` | GET | **SPU 详情（含描述、规格、多图）** ⚠️ TODO: 需抓包验证 |
| `/api/v1/merchant/sku/listBySpuId` | GET | **SKU 列表（按 SPU）** ⚠️ TODO: 需抓包验证 |
| `/api/v1/common/poi/queryByTypeThenAggByType` | POST | 门店按类型聚合查询 |
| `/api/v1/tenant/channels` | GET | 渠道列表 |
| `/api/v1/tenant/channel/batchQuery` | POST | 批量查渠道 |
| `/api/v1/tenant/aggTenantLevelConfig` | POST | 租户级别配置 |
| `/api/v1/tenant/queryPoiManageMode` | POST | 门店管理模式 |
| `/api/v1/tenant/modules` | GET | 模块列表 |
| `/api/v1/sac/auth/appMenuList` | GET | 菜单权限列表 |
| `/api/v1/notice/detail` | GET | 通知详情 |
| `/api/v2/assistant/getPoiTasksWithTotal` | GET | 待办任务（含总数） |

### 2b. 商品管理 API (qnh-gw3, 已验证)

> ⚠️ qnh-gw3 路径需要 h5guard 签名，直接 HTTP 返回 403，必须通过浏览器 fetch 执行。
> 2026-02-27 抓包验证。

| 路径 | 方法 | 用途 | 状态 |
|------|------|------|------|
| `/qnh-gw3/api/product/tenant/page-query` | POST | **SPU 分页列表** — `{page, pageSize, current}` | ✅ 已验证 |
| `/qnh-gw3/api/product/tenant/detail` | POST | **SPU 详情** — `{spuId}` | 待验证参数 |
| `/qnh-gw3/api/product/store/page-query-spu` | POST | 门店商品列表 | 待验证 |
| `/qnh-gw3/api/product/tenant/page-query-sku` | POST | SKU 分页列表 | 待验证 |

**SPU 列表返回字段：**
`tenantId, spuId, spuName, picUrlList[], skus[], brand, weightType` 等

**备选方案（已验证可用）：**
- 热销商品排行 `homepage_hotsale_goods_rank_table_view_new` — goldengateway，含部分商品数据
- 商品分类 `/api/v1/merchant/storeCategory/queryAll` — 已验证，可获取分类树

### 3. /common/ — 通用服务网关
> ✅ Cookie 认证即可访问。

| 路径 | 方法 | 用途 |
|------|------|------|
| `/common/tenant/config/tenant-channel-config/list/v1` | POST | 租户渠道配置列表 |
| `/common/auth/match/queryCombinationRule` | POST | 权限组合规则 |
| `/common/auth/account/queryPermissionCodes` | GET | 权限码查询 |
| `/common/auth/login-select-tenant-account` | GET | 登录租户选择 |
| `/common/auth/queryCombinationRule` | GET | 权限规则 |
| `/common/tenant/notices/query` | GET | 租户通知查询 |
| `/common/push/message/pageQueryAccountMessage` | POST | 推送消息分页查询 |
| `/common/push/message/getTenantAccountConfig` | GET | 推送配置 |
| `/common/message/im/getQnhXmAccount` | GET | IM 账号信息 |

### 4. /core/ — 核心业务网关
| 路径 | 方法 | 用途 |
|------|------|------|
| `/core/poi/b/store/selector/region` | GET | 门店区域选择器 |
| `/core/poi/b/warehouse/selector/region` | GET | 仓库区域选择器 |

### 5. /workbench/ — 工作台网关
| 路径 | 方法 | 用途 |
|------|------|------|
| `/workbench/b/dashboard/query/upcoming` | GET | 待办工单查询 |
| `/workbench/b/dashboard/task/labels` | GET | 任务标签 |
| `/workbench/b/notify/rule/get` | GET | 通知规则 |
| `/workbench/b/dialog/chatting/customerName` | GET | 当前对话客户名 |

### 6. /qnh-gw2/ — 旧版网关
| 路径 | 方法 | 用途 |
|------|------|------|
| `/qnh-gw2/common/grayrelease/querylitesetnameV2` | GET | 灰度发布配置 |

### 7. /support/ — 支持服务
| 路径 | 方法 | 用途 |
|------|------|------|
| `/support/tenant/service/remindInfo` | GET | 服务到期提醒 |
| `/support/tenant/user-preference/query` | GET | 用户偏好设置 |

### 8. api.neixin.cn — IM 即时消息
| 路径 | 方法 | 用途 |
|------|------|------|
| `/msg/api/chat/v3/chatlist/appid` | POST | 会话列表（按应用） |
| `/msg/api/pub/v1/chatlist` | POST | 公开会话列表 |
| `/msg/api/pub/v1/chatlist/info` | POST | 会话详情 |
| `/msg/api/chat/v3/chatlist/info` | POST | 聊天会话详情 |
| `/msg/api/pub/v3/history/chat/range` | POST | **聊天历史**（按时间范围） |
| `/msg/api/data/v1/offline` | POST | 离线消息 |
| `/read/api/v2/list` | POST | 已读消息列表 |
| `/pubread/v2/user/chat/getUnread` | POST | 未读消息数 |

## 安全机制

### csec 查询参数（所有请求必需）
```
yodaReady=h5&csecplatform=4&csecversion=4.2.0
```

### mtgsig 签名（goldengateway 必需）
- 由 h5guard.js 在浏览器端生成
- 包含时间戳、设备指纹、请求签名等
- 纯 HTTP 无法绕过，需要在浏览器环境执行
- **建议使用 ActionBook/Playwright 在真实浏览器中调用 goldengateway API**

### Cookie 认证
- 优先级: config/qnh_cookies.json > QNH_COOKIES_JSON env > session file
- `/api/v1/`, `/common/`, `/core/`, `/workbench/`, `/support/` 均可用 cookie 直接访问
- IM API (neixin.cn) 需要单独的 mtgsig 签名

## 数据同步策略

### 可直接 HTTP 同步 (cookie 认证)
- 商品分类 (`/api/v1/merchant/storeCategory/queryAll`)
- 门店信息 (`/api/v1/common/poi/queryByTypeThenAggByType`)
- 渠道列表 (`/api/v1/tenant/channels`)
- 待办任务 (`/api/v2/assistant/getPoiTasksWithTotal`)
- 工作台数据 (`/workbench/b/dashboard/...`)
- 推送消息 (`/common/push/message/...`)

### 需要浏览器环境 (mtgsig / h5guard)
- 门店指标/销售数据 (`/goldengateway/empower/generic/table/query`)
- 渠道分布 (`/goldengateway/empower/homepage/channelDistributeList`)
- 行业对标 (`/goldengateway/empower/complexModule/queryTable`)
- **商品管理 SPU/SKU** (`/qnh-gw3/api/product/tenant/*`) — h5guard 签名
- 聊天历史 (`api.neixin.cn/msg/api/pub/v3/history/chat/range`)
