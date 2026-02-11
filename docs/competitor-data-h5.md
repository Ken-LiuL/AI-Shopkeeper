# 美团 H5 移动端竞品数据采集方案

## 1. 概述

通过美团外卖 H5 移动端页面（`h5.waimai.meituan.com`）搜索附近医疗器械商品和店铺，使用 ActionBook Extension 模式控制已登录的 Chrome 浏览器进行数据采集。

**定位**：光谷（经度 114.43，纬度 30.51）

## 2. 美团 H5 页面分析

### 2.1 搜索 URL 结构

```
# 搜索页（商品维度）
https://h5.waimai.meituan.com/waimai/mindex/search/list?query={keyword}&lat={lat}&lng={lng}

# 店铺页
https://h5.waimai.meituan.com/waimai/mindex/menu?dpShopId={shop_id}&lat={lat}&lng={lng}

# 备选入口（i.meituan.com）
https://i.meituan.com/search?q={keyword}&lat={lat}&lng={lng}
```

### 2.2 关键 API 接口（XHR 拦截）

美团 H5 页面通过以下 API 获取数据：

| 接口 | 说明 | 关键参数 |
|------|------|----------|
| `/api/v7/poi/search` | 搜索商品/店铺 | keyword, lat, lng, page |
| `/api/v7/poi/food` | 店铺菜单/商品列表 | dpShopId |
| `/api/v7/poi/hot_search_words` | 热搜词 | lat, lng |
| `/waimai/ajax/v2/search/entry` | 搜索联想词 | keyword |

### 2.3 返回字段（搜索结果）

```json
{
  "poiId": "店铺ID",
  "name": "店铺名称",
  "pic_url": "店铺图片",
  "wm_poi_score": "评分",
  "month_sale_tip": "月销 xxx",
  "min_price_tip": "¥20起送",
  "delivery_time_tip": "30分钟",
  "distance": "1.2km",
  "shipping_fee_tip": "配送费¥3",
  "food_spu_tags": [
    {
      "spuId": "商品ID",
      "name": "商品名",
      "price": 29.9,
      "month_sale": 150,
      "praise_num": 50
    }
  ]
}
```

## 3. ActionBook 采集流程

### 3.1 前置条件

1. Chrome 已安装 ActionBook 扩展
2. ActionBook Extension Bridge 已启动：`actionbook extension serve`
3. Chrome 已登录美团账号（cookie 有效）

### 3.2 采集流程

```
1. browser_open → 打开搜索页（带经纬度参数）
2. browser_eval → 注入 XHR 拦截器（捕获 API 响应）
3. browser_fill → 输入搜索关键词
4. browser_click → 点击搜索按钮
5. sleep(3-5s) → 等待结果加载
6. browser_eval → 提取拦截到的 API 数据
7. 若无 XHR 数据 → browser_text 降级提取页面文本
8. browser_eval → 滚动加载更多（如需翻页）
9. 解析并返回结构化数据
10. browser_close → 清理
```

### 3.3 XHR 拦截器

```javascript
// 注入到页面，拦截搜索 API 响应
(function() {
  window.__mt_captured = [];
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this._url = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    this.addEventListener('load', function() {
      if (this._url && (this._url.includes('/search') || this._url.includes('/poi'))) {
        try {
          window.__mt_captured.push({
            url: this._url,
            data: JSON.parse(this.responseText)
          });
        } catch(e) {}
      }
    });
    return origSend.apply(this, arguments);
  };
})();
```

## 4. 数据字段映射

### 4.1 CompetitorProduct

| 页面字段 | 模型字段 | 说明 |
|----------|----------|------|
| spuId | product_id | 商品ID |
| name | name | 商品名称 |
| price / min_price | price | 价格 |
| month_sale | monthly_sales | 月销量 |
| poi_name | store_name | 所属店铺 |
| wm_poi_score | rating | 店铺评分 |
| distance | distance_km | 距离 |

### 4.2 CompetitorStore

| 页面字段 | 模型字段 | 说明 |
|----------|----------|------|
| poiId / dpShopId | store_id | 店铺ID |
| name | name | 店铺名称 |
| distance | distance_km | 距离(km) |
| wm_poi_score | rating | 评分 |
| month_sale_tip | monthly_sales | 月销量 |
| food_spu_tags.length | product_count | 商品数 |

## 5. 反爬策略

### 5.1 频率控制
- 每次请求间隔 **2-5 秒**（随机）
- 每小时最多 **30 次**搜索
- 每天最多 **60 次**搜索（分 10:00 和 22:00 两批）

### 5.2 UA / Cookie
- 使用 Extension 模式 → 复用用户真实 Chrome UA 和 cookie
- 无需额外设置 User-Agent
- Cookie 过期时需手动重新登录

### 5.3 定位管理
- 通过 URL 参数 `lat` / `lng` 设定位置
- 备选：`browser_eval` 覆盖 `navigator.geolocation`

### 5.4 风险缓解
- 采集失败静默返回空列表，不重试
- 检测到验证码/登录页 → 跳过本次采集
- 日志记录每次采集状态，便于人工干预

## 6. 数据库存储

参见 `migrations/postgres/005_competitor_tables.sql`：
- `competitor_products` — 竞品商品快照
- `competitor_stores` — 竞品店铺快照
- `competitor_keywords` — 热搜词记录
