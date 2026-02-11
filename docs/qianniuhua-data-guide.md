# 牵牛花（美团商家后台）数据采集指南

> 店铺: 七悦康医疗器械光谷店（租户ID: 1011766）
> 探索日期: 2026-02-12
> 基础URL: `https://qnh.meituan.com/home.html`

---

## 1. 系统架构概述

### 技术架构
- **框架**: 微前端架构（bifrost），主页面 + 多个子应用
- **路由**: Hash路由 (`#/module/submodule/page`)
- **UI库**: Ant Design + 自定义 wand 组件库
- **侧边栏**: `wand-side-menu-v2`，hover触发弹出式子菜单
- **布局**: `saas-platform-layout` 包含侧边栏 + 主内容区
- **页面加载**: 子应用通过微前端容器动态加载，某些内容使用iframe
- **CDP端口**: 9222（本地Chrome远程调试）

### 认证
- 登录后Cookie自动携带认证信息
- API请求附带参数: `yodaReady=h5&csecplatform=4&csecversion=4.2.0`
- 安全组件: csec（美团安全SDK）

---

## 2. 完整菜单结构与URL路由

### 2.1 首页
- **URL**: `#/data/home/new`
- **子页面**: 无
- **功能**: 数据概览仪表板

### 2.2 商品
| 子菜单 | URL Hash | 说明 |
|--------|----------|------|
| 商品资料 | - | 分组标题 |
| 商品主档 | `#/unifiedGoods/tenant/spu-list` | SPU级商品管理 |
| 门店商品 | `#/goods/store-goods-list` | 门店维度商品 |
| 渠道商品 | `#/goods/channel-goods-list` | 渠道维度商品 |
| 商品类目 | `#/goods/category` | 类目管理 |
| 店内分类 | `#/goods/store-category` | 自定义分类 |
| 组合关系 | `#/goods/combination` | 组合商品 |
| 商品标签 | `#/goods/tag` | 标签管理 |
| 总部商品审核 | `#/goods/audit` | 审核流程 |
| 商品品牌 | `#/goods/brand` | 品牌管理 |
| 商品策略 | `#/goods/strategy` | 定价策略等 |
| 商品排序 | `#/goods/sort` | 排序设置 |

### 2.3 库存
| 子菜单 | URL Hash | 说明 |
|--------|----------|------|
| **库存查询** | | |
| 库存查询 | `#/stock/query` | 实时库存 |
| 库存流水 | `#/stock/flow` | 库存变动记录 |
| 库存查询-新 | `#/stock/query-new` | 新版库存查询 |
| **出入库管理** | | |
| 收货单（新） | `#/stock/receipt-new` | 入库收货 |
| 出库单 | `#/stock/outbound` | 出库操作 |
| 出库订单查询 | - | 出库订单 |
| 拣货任务查询 | - | 拣货任务 |
| 复核任务查询 | - | 复核任务 |
| 分拣任务查询 | - | 分拣任务 |
| 销售退货单 | - | 退货入库 |
| 收货单 | - | 旧版收货 |
| **仓内管理** | | |
| 盘点单 | `#/stock/inventory` | 盘点操作 |
| 调整单 | `#/stock/adjustment` | 库存调整 |
| 调拨差异单 | - | 调拨差异 |
| 报损单 | - | 库存报损 |
| 盘点需求单 | - | 盘点计划 |
| 盘点单（新） | - | 新版盘点 |
| 调整单（新） | - | 新版调整 |
| **储位管理** | | |
| 区域管理 | - | 仓库区域 |
| 区域组设置 | - | 区域分组 |
| 库位区域配置 | - | 库位配置 |
| 库位管理 | - | 库位CRUD |
| 商品配置管理 | - | 商品-库位映射 |
| **基础数据** | | |
| 货主货品查询 | - | 基础数据 |
| **差异中心** | | |
| 差异单 | - | 差异处理 |
| 差异任务 | - | 差异任务 |
| **预约单** | - | |
| **打印中心** | - | |

### 2.4 中心仓
| 子菜单 | 说明 |
|--------|------|
| **物流订单** | |
| 出库订单 | 仓库出库 |
| 生产订单 | 生产相关 |
| **入库管理**: 预约单、收货单 | |
| **出库管理**: 出库单、拣货任务、分拣任务、复核任务 | |
| **在库管理**: 盘点单、调整单、效期预警 | |
| **库存管理**: 库存查询、库存流水 | |
| **打印中心** | |
| **基础设置**: 商品配置管理、货主货品查询 | |
| **规则与策略**: 网格策略配置、预约规则管理、门店与网格关系配置 | |
| **物流货品**: 货主货品 | |
| **差异中心**: 差异单、差异任务 | |

### 2.5 采购
| 子菜单 | 说明 |
|--------|------|
| **供应商**: 商品供货关系、供应商管理 | |
| **补货参考** | |
| 要货单 | 门店要货 |
| 采购计划 | 采购规划 |
| 采购单 | 实际采购（`#/purchase/order`类似） |
| 采购退货单 | 退货给供应商 |
| 采购调整单 | 调整 |
| 调拨单 | 门店间调拨 |
| **配销管理**: 配销单 | |
| **采购设置**: 订货设置、补货参数设置 | |
| **库存健康**: 设置、报表 | |
| **外部采购**: 账户管理 | |
| **采购价监控**: 监控、规则 | |
| 订货王、货源中心、网采中心 | |
| 采购设置（新） | |

### 2.6 营销
| 子菜单 | 说明 |
|--------|------|
| 促销活动导航 | 活动入口 |
| 活动管理 | 创建/管理促销 |
| 活动商品列表 | 参与活动的商品 |
| 活动定价预警 | 价格预警 |

### 2.7 订单
| 子菜单 | 说明 |
|--------|------|
| 订单查询 | 分组标题 |
| 订单列表 | 全部订单（`#/order/list`） |
| 退单列表 | 退款/退货订单 |
| 订单履约看板 | 实时履约监控 |

### 2.8 配送
| 子菜单 | 说明 |
|--------|------|
| 异常上报 | 配送异常 |
| 聚合配送 | 多渠道配送管理 |
| 钱包总 | 配送钱包 |
| 账户管理 | 配送账户 |

### 2.9 评价
| 子菜单 | 说明 |
|--------|------|
| 核心评价指标 | 评分统计 |
| 评价详情 | 具体评价内容 |

### 2.10 财务
| 子菜单 | 说明 |
|--------|------|
| **对账管理** | |
| 牵牛花账单 | 系统账单（`#/finance/bill`） |
| 渠道销售账单 | 各渠道销售 |
| 销售抽佣账单 | 平台佣金 |
| **发票管理** | |
| 销项票管理 | 开票管理 |
| **台账管理** | |
| 线下台账 | 线下交易记录 |

### 2.11 数据（⭐ 最重要的数据采集模块）
| 子菜单 | 说明 |
|--------|------|
| **数据概览** | 核心仪表板（`#/data/home/new`） |
| **流量** | |
| 流量概览 | 店铺流量分析 |
| 商品流量分析 | 单品流量 |
| **经营** | |
| 经营分析 | 经营趋势 |
| 经营详情 | 详细经营数据 |
| 门店营业时长 | 营业时段分析 |
| 订单热力图 | 订单时间分布 |
| **促销** | |
| 促销分析 | 活动效果 |
| 活动明细 | 活动详情 |
| **商品** | |
| 品类分析 | 按品类统计 |
| 商品详情 | 单品销售数据 |
| 商品销售缺勤 | 缺勤分析 |
| 无动销商品 | 零销售商品 |
| 商品指标监控 | 商品KPI |
| **库存** | |
| 库存周转分析 | 周转率 |
| 出入库汇总 | 进出汇总 |
| **履约** | |
| 订单实时监控 | 实时订单 |
| 拣货分析 | 拣货效率 |
| 配送分析 | 配送效率 |
| 标缺商品 | 标记缺货 |
| **服务** | |
| 服务问题分析 | 服务质量 |
| 门店履约监控 | 履约率 |
| **采购** | |
| 供应商价值分析 | 供应商评估 |
| **效能** | |
| 仓店人效分析 | 人力效率 |
| **盈亏** | |
| 盈亏分析 | 利润分析 |
| 实时毛利监控 | 实时毛利 |
| 线下台账统计 | 线下统计 |
| 毛利成本核对 | 成本核对 |
| **预警中心** | 异常预警 |

### 2.12 任务
- 批量任务

### 2.13 设置
| 子菜单 | 说明 |
|--------|------|
| 商品设置 | 商品相关配置 |
| 审核配置 | 审批流程 |
| 采购设置 | 采购配置 |
| 仓库管理 | 仓库信息 |
| 门店管理 | 门店CRUD |
| 门店分组 | 门店分组 |
| 组织结构 | 组织架构 |
| 账号管理 | 用户账号 |
| 角色管理 | 权限角色 |
| 岗位管理 | 岗位设置 |
| 上线申请列表 | 上线审批 |
| 企业主体管理 | 企业信息 |
| 渠道接入 | 渠道配置 |
| 订单设置 | 订单配置 |
| 风险用户设置 | 风控 |
| 订单管理设置 | 订单管理 |
| 营销设置 | 营销配置 |
| 商品管理设置 | 商品管理 |

### 2.14 其他菜单
| 菜单 | 子菜单 |
|------|--------|
| 日志 | 商品上下架、商品主档删除、日志中心 |
| 审批管理 | 待审批、已审批、已发起、审批找人策略 |
| 增值 | 增值服务、应用中心 |
| 工作台 | - |
| 监控 | 实时监控、监控回放 |
| 差异判责 | 判责任务、批量判责、判责单、落责单 |

---

## 3. 数据概览页面详细分析

### 页面: `#/data/home/new`

#### 筛选条件
- **时间**: 日/周/月/自定义，可选前一日/后一日
- **门店**: 多选（光谷店、贝诺臣医疗 等）
- **渠道**: 全部渠道/单选

#### 核心指标（3行 × 多列）
**第一行 - 收入指标:**
| 指标 | 示例值 | 说明 |
|------|--------|------|
| 有效订单金额 | 670.93 | 含周同比、环比 |
| 有效订单数 | 15 | 订单量 |
| 客单价 | 44.73 | 平均单价 |
| 净利润 | - | 利润 |
| 线上毛利 | - | 线上渠道毛利 |
| 线下其他 | - | 线下收入 |

**第二行 - 成本指标:**
| 指标 | 示例值 |
|------|--------|
| 实付金额 | 414.64 |
| 实付客单价 | 27.64 |
| 商品销售额 | 500.60 |
| 包装费 | 14.50 |
| 配送费 | 155.33 |
| 顾客数 | 15 |

**第三行 - 运营指标:**
| 指标 | 示例值 |
|------|--------|
| 商品动销率 | - |
| 整单超时率 | 0% |
| 缺货退款率 | - |
| 周转天数(金额) | - |
| 售罄缺勤损失 | - |

#### 图表
- **趋势分析**: 按小时的柱状图（订单量/金额）
- **渠道分布**: 饼图 — 京东到家(1), 美团闪购(7), 饿了么(7)

#### 标签页
- 门店数据（默认）
- 仓数据
- 待办事项（99+）
- 行业对标

---

## 4. 已发现的API端点

### 通用API（主框架层）
```
POST /api/v1/tenant/aggTenantLevelConfig     # 租户配置
GET  /api/v1/tenant/modules                   # 模块列表
POST /api/v1/sac/account/auth                 # 账号鉴权
POST /api/v1/tenant/channel/batchQuery        # 渠道批量查询
POST /api/v1/tenant/channels                  # 渠道列表
POST /api/v1/tenant/chainRelation             # 连锁关系
POST /api/v1/tenant/spu/bigSquirrelTenantId   # 租户SPU
POST /api/v1/store/spu/fieldSetting           # 字段设置
POST /common/tenant/config/tenant-channel-config/list/v1  # 渠道配置
POST /common/auth/match/queryCombinationRule   # 权限规则
POST /common/auth/account/queryPermissionCodes # 权限码
```

### 灰度/配置API
```
POST /core/pms/shangou/tenant/grey/config/query       # 灰度配置
POST /core/pms/shangou/distribute/store/grey/query     # 门店灰度
GET  /qnh-gw3/api/product/support/gray/waima-merge-core # 外卖合并灰度
```

### 数据API
```
POST /api/v2/assistant/getPoiTasksWithTotal    # 待办任务统计
     body: [1175006,1221411,1232550]           # POI门店ID列表
```

### 重要说明
- 大部分页面内容通过**微前端子应用**加载，实际数据API请求发生在子应用内部
- 子应用可能请求不同域名的API（如 `shangou-*` 系列服务）
- 需要在具体页面打开Network面板才能捕获完整的数据API

---

## 5. 数据采集策略

### 5.1 推荐优先级

#### 🟢 高优先级（日常运营必需）
1. **数据概览** (`#/data/home/new`) — 每日核心指标
2. **订单列表** (`#/order/list`) — 订单明细
3. **商品主档** (`#/unifiedGoods/tenant/spu-list`) — 商品基础数据
4. **库存查询** — 实时库存
5. **评价详情** — 客户反馈

#### 🟡 中优先级（定期分析）
6. **经营分析/详情** — 经营趋势（周/月）
7. **盈亏分析** — 利润分析
8. **促销分析** — 活动效果评估
9. **财务账单** — 对账
10. **商品详情(数据)** — 单品分析

#### 🔵 低优先级（按需）
11. 库存周转分析
12. 供应商价值分析
13. 流量分析
14. 配送分析

### 5.2 采集方法

#### 方法一: CDP + 页面DOM抓取（推荐）
最可靠的方法。通过CDP连接浏览器，导航到目标页面，等待加载完成后提取DOM数据。

```javascript
// 基础CDP连接模式（参考 /tmp/qnh-slider.mjs）
import WebSocket from 'ws';

async function connectCDP() {
  const resp = await fetch('http://127.0.0.1:9222/json');
  const targets = await resp.json();
  const page = targets.find(t => t.url.includes('qnh.meituan'));
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  // ... send CDP commands
}
```

#### 方法二: 网络请求拦截 + API重放
1. 打开目标页面
2. 通过 CDP `Network.enable` 捕获所有API请求
3. 记录请求URL、Headers、Body
4. 后续直接调用API获取数据

```javascript
// 拦截示例
await send('Network.enable');
ws.on('message', (d) => {
  const msg = JSON.parse(d.toString());
  if (msg.method === 'Network.requestWillBeSent') {
    // 记录API请求
  }
  if (msg.method === 'Network.responseReceived') {
    // 获取响应数据
    send('Network.getResponseBody', { requestId: msg.params.requestId });
  }
});
```

#### 方法三: ActionBook CLI 操作
```bash
# 导航到页面
actionbook browser goto "https://qnh.meituan.com/home.html#/data/home/new"

# 获取页面快照
actionbook browser snapshot

# 截图
actionbook browser screenshot /path/to/save.png

# 执行JS获取数据
actionbook browser eval '(function(){ /* extract data */ })()'

# 点击元素
actionbook browser click refId
```

### 5.3 侧边栏导航操作流程

由于牵牛花使用hover弹出式子菜单，导航需要:

1. **定位菜单项坐标**: 查询 `.wand-side-menu-v2-nav-item-content` 元素
2. **CDP mouseMoved 悬停**: 触发子菜单弹出
3. **等待500-800ms**: 子菜单渲染
4. **定位子菜单项**: 在 `.wand-side-menu-v2-popup-container` 中查找
5. **CDP click**: mousePressed + mouseReleased
6. **等待2-3s**: 页面加载

```javascript
// 示例: 导航到"订单列表"
// 1. Hover "订单" menu
await send('Input.dispatchMouseEvent', {type:'mouseMoved', x:69, y:317});
await sleep(600);
// 2. Find "订单列表" in popup and click
const coords = await getSubMenuCoords('订单列表');
await send('Input.dispatchMouseEvent', {type:'mousePressed', ...coords, button:'left', clickCount:1});
await send('Input.dispatchMouseEvent', {type:'mouseReleased', ...coords, button:'left', clickCount:1});
await sleep(3000);
// 3. Now page is loaded at #/order/list
```

### 5.4 数据导出功能

> ⚠️ 具体导出按钮需要进入每个页面后确认。根据初步观察:

- **订单列表**: 通常有"导出"按钮，可导出Excel
- **库存查询**: 有导出功能
- **财务账单**: 有账单下载
- **数据报表**: 部分页面支持数据导出

导出操作流程:
1. 设置筛选条件（时间范围、门店、渠道等）
2. 点击"导出"按钮
3. 等待文件生成
4. 下载文件（通常是Excel格式）

### 5.5 跨域iframe处理

部分页面内容在iframe中加载，需要使用CDP的 `Page.createIsolatedWorld` 在iframe context中执行JS:

```javascript
// 获取iframe frame tree
const tree = await send('Page.getFrameTree');
const frames = tree.result.frameTree.childFrames || [];

// 为每个iframe创建执行上下文
for (const frame of frames) {
  const world = await send('Page.createIsolatedWorld', {
    frameId: frame.frame.id,
    worldName: 'dataExtract'
  });
  
  // 在iframe中执行JS
  const result = await send('Runtime.evaluate', {
    expression: '(function(){ /* extract data */ })()',
    contextId: world.result.executionContextId,
  });
}
```

---

## 6. 渠道信息

当前店铺接入的渠道:
- **美团闪购** — 美团外卖/闪购平台
- **饿了么** — 饿了么平台
- **京东到家** — 京东到家平台

门店POI ID列表: `[1175006, 1221411, 1232550]`

---

## 7. 关键发现和注意事项

### 技术注意事项
1. **微前端架构**: 页面内容通过微前端子应用异步加载，直接修改URL hash可能导致404，需要通过菜单点击导航
2. **安全SDK**: 请求需要csec安全参数，直接API调用可能需要处理这些参数
3. **Session管理**: 长时间不操作可能导致session过期，需要重新登录
4. **加载时间**: 页面加载需要2-5秒，快速连续导航可能导致页面白屏
5. **元素定位**: sidebar用CSS class `wand-side-menu-v2-*`，主内容区域用 `saas-platform-layout-*`

### 数据采集建议
1. 每次只采集一个模块的数据，避免频繁切换页面
2. 使用 CDP Network 拦截获取API端点，然后直接调用API效率更高
3. 对于表格数据，优先使用"导出"功能获取Excel，避免分页爬取
4. 数据概览页面的指标可以通过修改日期参数批量获取历史数据
5. 建议建立定时任务，每天凌晨采集前一天的数据

### 待进一步探索
- [ ] 每个页面的具体导出按钮位置和功能
- [ ] 完整的API端点列表（需要在每个页面启用Network拦截）
- [ ] API请求的认证Token格式和刷新机制
- [ ] 数据导出的格式、字段和时间限制
- [ ] 批量数据采集的频率限制

---

## 8. 文件参考

| 文件 | 说明 |
|------|------|
| `/tmp/qnh-slider.mjs` | CDP滑块验证码处理脚本 |
| `/tmp/qnh-pages.json` | 页面URL和API端点扫描结果 |
| `/tmp/qnh-screenshots/` | 页面截图存档 |
| 本文档 | 数据采集方法论 |
