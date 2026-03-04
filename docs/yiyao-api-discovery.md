# 美团买药商家中心 API 发现

## 平台信息
- URL: https://yiyao.meituan.com
- 登录: https://waimaie.meituan.com/new_fe/login_gw#/login (共用美团外卖商家端登录)
- 认证: Cookie + mtgsig 签名 + H5guard
- POI ID: 30850916 (贝诺臣医疗器械·徐东店)
- region_id: 1000420100
- region_version: 1763630401
- 账号: mt773204p
- 门店类型: single-o2o (单店O2O)

## 已发现 API

### 订单
- `GET /gw/api/unified/r/order/list/count` — 订单统计
- `GET /gw/api/unified/r/order/list/interval` — 订单列表(分时段)

### 商品 (iframe 内)
- 商品列表页: `/page/product/list/single?wmPoiId=30850916&region_id=...&region_version=...`
- 数据: 1,665 商品, 含库存/预占、30天销量、价格、UPC/SKUID

### 通用
- `GET /health/notice/u/gray/query` — 灰度查询
- `GET /api/page/upm/authverify/page/url` — 权限验证
- `GET /api/retail/msg/getPageMsg` — 页面消息
- `GET /msg/b/msg-record/info-bar/list` — 信息条列表
- `GET /msg/b/msg-record/pop-up/list` — 弹窗列表
- `GET /health/notice/u/query` — 通知查询

## 页面结构
- 主框架: `yiyao.meituan.com/main/frame`
- 内容 iframe: `yiyao.meituan.com/page/{module}?wmPoiId=...`
- 微前端架构: qiankun-based

## 菜单模块
- 订单管理: 今日待办、预订单、全部订单、医保订单、评价管理、发票管理
- 经营指导: 经营首页、需求洞察、商品分析、营销分析、流量分析、顾客分析、服务分析、报表下载
- 商品管理: 商品列表、批量管理、商品审核、商品体检、商品违规、医保业务
- 营销活动: 销量机会、美团补贴、活动提报、店铺活动、我的活动、精准营销
- 财务中心: 账单对账、财务统计、订单查询、发票申请、下载专区、账户管理

## 数据质量 (vs QNH)
| 维度 | QNH | 美团买药 |
|------|-----|---------|
| 库存 | ❌ 全0 | ✅ 真实库存+预占 |
| 订单 | ❌ 聚合 | ✅ 完整列表 |
| 销量 | ⚠️ Top50 | ✅ 每商品30天 |
| 价格 | ✅ 零售 | ✅ 原价+活动价 |
| 财务 | ❌ | ✅ 完整 |

## 技术要点
- 需要 nodriver 登录 (滑块验证码+手机验证码)
- API 需 mtgsig 签名, 纯 HTTP 不行
- Cookie 有效期待测试
- 商品列表 API 在 iframe 内, 需要 CDP 抓包或直接在 iframe 内 fetch

## TODO
- [ ] 抓取商品列表具体 API 端点和参数
- [ ] 抓取订单列表具体参数格式
- [ ] 测试 cookie 有效期
- [ ] 写 MeituanAuthManager
- [ ] 写 ProductSync / OrderSync
