# 美团即时零售竞品数据获取方案研究报告

> 调研时间：2026-02-11
> 场景：美团即时零售 · 医疗器械类目 · 竞品分析

## 目标数据

| 数据类型 | 具体字段 |
|---------|---------|
| 竞品店铺列表 | 店名、距离、评分、评价数 |
| 竞品商品列表 | 名称、价格、月销量、是否缺货 |
| 热搜/排行 | 热搜关键词、商品排行榜 |

---

## 方案 1：美团商家后台 API

### 调研结果

**美团开放平台 (openapi.meituan.com)**：需联系商务获取接口文档（邮箱：jianglu16@meituan.com 等），**不对外公开注册**。

**美团技术服务合作中心 (developer.waimai.meituan.com)**：定位为品牌商/供应链合作方的技术对接平台，需登录才能查看文档，主要面向 ERP/SaaS 对接订单、商品、库存等**自有店铺数据**。

**美团开店宝 / 美团经营宝 (e.meituan.com)**：商家经营后台，提供：
- **经营参谋 → 竞对分析**：可添加竞品门店，对比浏览量、下单转化率、客单价等维度
- **经营洞察 → 经营分析**：本店流水、商圈排名
- 数据导出功能有限，主要以页面看板呈现

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **部分可行** — 竞对分析功能存在，但仅限已入驻商家登录使用，且数据维度有限（无商品级别详情） |
| 难度 | 低（已有商家账号的前提下） |
| 维护成本 | 低 |
| 限制 | 不提供竞品商品列表和价格；无公开 API；竞对分析数据颗粒度不够细 |

### 结论
可作为**辅助数据源**获取商圈级别的竞争指标，但无法满足商品级别的竞品监控需求。

---

## 方案 2：美团 H5/小程序接口逆向

### 调研结果

**H5 页面**：`h5.waimai.meituan.com` 是美团外卖 H5 入口，SPA 应用，数据通过 XHR 加载。

**关键 API 端点**（基于社区逆向分析）：
- 搜索接口：`/api/v8/poi/food` — 搜索附近商家和商品
- 商家详情：`/api/v8/poi/detail` — 店铺信息、评分
- 商品列表：`/api/v8/poi/food` — 商家菜单/商品列表
- 域名通常为 `i.waimai.meituan.com` 或 `waimai.meituan.com`

**反爬机制（非常强）**：
- **mtgsig 签名**：所有请求必须携带 `mtgsig` 参数，目前已升级到 3.0 版本
- mtgsig 由 Native 层（SO 库）计算，涉及设备指纹、请求体签名
- 需要逆向 `libmtguard.so`，算法包含 WASM/汇编级别混淆
- **waimai_sign**：外卖专属签名参数，需配合 mtgsig 使用
- **Cookie/Token**：需要有效的登录态
- **频率限制 + 设备指纹**：高频请求会触发验证码

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **部分可行但极高风险** |
| 难度 | **极高** — mtgsig 3.0 逆向需要专业安全研究能力 |
| 维护成本 | **极高** — 美团频繁更新签名算法，需持续跟进 |
| 法律风险 | **高** — 违反美团用户协议，可能触犯《反不正当竞争法》 |

### 结论
**不推荐**。技术门槛极高、维护成本极高、法律风险大。除非有专业安全团队，否则不可行。

---

## 方案 3：ActionBook 浏览器自动化

### 调研结果

[ActionBook](https://github.com/actionbook/actionbook) 是一个为 AI Agent 设计的浏览器自动化引擎：
- 提供预计算的 "Action Manual"（操作手册），告诉 AI 如何操作特定网站
- 基于 Rust CLI，使用系统浏览器（Chrome/Edge/Arc）
- 支持的网站取决于社区贡献的 Action Manual

**问题**：
- ActionBook 目前主要覆盖国际主流网站（Airbnb、Google 等），**尚未有美团相关的 Action Manual**
- 可以自定义编写美团的 Action Manual，但本质上还是浏览器自动化
- 优势在于 AI 驱动操作，但对于数据采集场景，和 Playwright 差异不大

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **部分可行** — 需要自行编写美团的 Action Manual |
| 难度 | 中高 |
| 维护成本 | 中 — 美团页面结构变化时需更新 Manual |
| 优势 | AI 驱动，对 UI 变化有一定适应性 |

### 结论
没有现成支持，需自行开发。与方案 4（Playwright）相比没有明显优势，反而增加了一层抽象。**暂不推荐**。

---

## 方案 4：Playwright 浏览器自动化爬取

### 调研结果

这是目前社区中最常见的美团数据采集方案：
- 用 Playwright 打开美团 H5 页面（需要提供定位信息）
- 模拟用户搜索、浏览操作
- 拦截网络请求获取 API 响应数据，或直接解析页面 DOM

**优势**：
- 绕过 mtgsig 签名问题（由真实浏览器环境生成）
- 可以获取完整的商品列表、价格、销量信息
- 技术实现相对直观

**挑战**：
- 需要处理定位授权（模拟经纬度）
- 需要登录态（美团账号）
- 采集速度受限（需模拟真人操作节奏）
- 反爬检测：异常行为检测、验证码
- 需要代理 IP 池分散请求

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **可行** ✅ |
| 难度 | **中** |
| 维护成本 | **中** — 页面结构变化需调整选择器 |
| 法律风险 | **中** — 仅采集公开展示数据，但频率需控制 |

### 实现方案

```typescript
// meituan-scraper.ts — Playwright 竞品数据采集 POC
import { chromium, type Page } from 'playwright';

interface ShopInfo {
  name: string;
  distance: string;
  rating: number;
  reviewCount: number;
  monthSales: number;
}

interface ProductInfo {
  name: string;
  price: number;
  monthSales: number;
  inStock: boolean;
}

// 目标位置经纬度（示例：广州天河区）
const TARGET_LOCATION = {
  latitude: 23.1291,
  longitude: 113.2644,
};

async function scrapeCompetitors() {
  const browser = await chromium.launch({
    headless: false, // 建议先用有头模式调试
  });

  const context = await browser.newContext({
    geolocation: TARGET_LOCATION,
    permissions: ['geolocation'],
    locale: 'zh-CN',
    userAgent:
      'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    viewport: { width: 375, height: 812 },
  });

  const page = await context.newPage();

  // 监听网络请求，拦截 API 响应
  const apiResponses: any[] = [];
  page.on('response', async (response) => {
    const url = response.url();
    if (url.includes('/api/') && response.status() === 200) {
      try {
        const json = await response.json();
        apiResponses.push({ url, data: json });
      } catch {}
    }
  });

  // 1. 打开美团外卖 H5
  await page.goto('https://h5.waimai.meituan.com');
  await page.waitForTimeout(3000);

  // 2. 搜索医疗器械相关关键词
  const keywords = ['血压计', '血糖仪', '体温计', '医疗器械', '创可贴'];

  for (const keyword of keywords) {
    // 点击搜索框
    await page.click('[class*="search"]'); // 选择器需根据实际页面调整
    await page.waitForTimeout(1000);

    // 输入关键词
    await page.fill('input[type="search"], input[placeholder*="搜索"]', keyword);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(3000);

    // 3. 提取搜索结果中的店铺列表
    const shops = await page.evaluate(() => {
      const items = document.querySelectorAll('[class*="shopItem"], [class*="poi-item"]');
      return Array.from(items).map((item) => ({
        name: item.querySelector('[class*="name"]')?.textContent?.trim() || '',
        distance: item.querySelector('[class*="distance"]')?.textContent?.trim() || '',
        rating: item.querySelector('[class*="score"], [class*="rating"]')?.textContent?.trim() || '',
        sales: item.querySelector('[class*="sales"], [class*="month"]')?.textContent?.trim() || '',
      }));
    });

    console.log(`[${keyword}] 找到 ${shops.length} 家店铺:`, shops);

    // 4. 进入每个店铺获取商品列表
    for (let i = 0; i < Math.min(shops.length, 5); i++) {
      const shopLinks = await page.$$('[class*="shopItem"], [class*="poi-item"]');
      if (shopLinks[i]) {
        await shopLinks[i].click();
        await page.waitForTimeout(3000);

        // 提取商品信息
        const products = await page.evaluate(() => {
          const items = document.querySelectorAll('[class*="product"], [class*="food-item"]');
          return Array.from(items).map((item) => ({
            name: item.querySelector('[class*="name"]')?.textContent?.trim() || '',
            price: item.querySelector('[class*="price"]')?.textContent?.trim() || '',
            sales: item.querySelector('[class*="sales"], [class*="month"]')?.textContent?.trim() || '',
          }));
        });

        console.log(`  店铺[${shops[i].name}] 商品:`, products);

        await page.goBack();
        await page.waitForTimeout(2000);
      }
    }

    // 返回搜索页
    await page.goBack();
    await page.waitForTimeout(1000);
  }

  // 5. 输出拦截到的 API 响应（结构化数据，比 DOM 解析更可靠）
  console.log('\n=== 拦截到的 API 响应 ===');
  for (const resp of apiResponses) {
    console.log(`URL: ${resp.url}`);
    console.log(`Data keys: ${Object.keys(resp.data)}`);
  }

  await browser.close();
}

scrapeCompetitors().catch(console.error);
```

**使用方式**：
```bash
# 安装依赖
npm init -y
npm install playwright
npx playwright install chromium

# 运行
npx tsx meituan-scraper.ts
```

**关键优化点**：
1. **优先拦截 API 响应**而非解析 DOM — API 返回的 JSON 数据更结构化、更稳定
2. **控制采集频率** — 每次请求间隔 3-5 秒，模拟真人
3. **使用多个美团账号轮换** — 降低单账号风险
4. **定期更新选择器** — CSS 选择器可能随版本变化

---

## 方案 5：第三方数据服务

### 调研结果

搜索了多个第三方数据工具，结果如下：

| 工具/平台 | 类型 | 覆盖范围 | 适用性 |
|-----------|------|---------|--------|
| **美团数据采集软件**（知乎推荐） | 桌面采集工具 | 商家列表 + 商品明细 | ⚠️ 灰色地带 |
| **QuestMobile** | 行业报告 | 即时零售行业宏观数据 | ❌ 不提供店铺级数据 |
| **月狐数据 (MoonFox)** | 行业分析 | 即时零售 APP 用户行为 | ❌ 宏观数据 |
| **艾媒咨询 (iiMedia)** | 行业报告 | 市场规模、用户画像 | ❌ 宏观数据 |
| **八爪鱼/后羿采集器** | 通用网页采集 | 可配置美团模板 | ⚠️ 需应对反爬 |

**关键发现**：
- **没有**类似蝉妈妈（抖音）/ 生意参谋（淘宝）的美团即时零售专用数据平台
- 美团数据生态相对封闭，第三方工具主要是爬虫类
- 行业分析平台（QuestMobile 等）仅提供宏观数据，不提供店铺/商品级别

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **不可行**（没有合规的第三方服务提供店铺级竞品数据） |
| 替代方案 | 八爪鱼等采集工具可用，但本质是爬虫，与方案4等价 |

---

## 方案 6：商家后台数据导出

### 调研结果

美团商家后台（美团开店宝 / 美团经营宝）支持的数据导出：
- **订单数据**：可导出 Excel（订单明细、收入统计）
- **商品数据**：可查看/编辑自有商品，部分支持导出
- **经营数据**：经营报告、流水数据可导出
- **竞品数据**：竞对分析功能以页面看板呈现，**不支持导出**

**自动化导出思路**：
- 用 Playwright 登录商家后台 → 触发导出 → 下载文件
- 但仅限**自有店铺数据**，无法导出竞品数据

### 可行性评估

| 维度 | 评估 |
|------|------|
| 可行性 | **部分可行** — 仅适用于自有店铺数据导出自动化 |
| 难度 | 低 |
| 竞品数据 | ❌ 不支持 |

---

## 综合评估总览

| 方案 | 可行性 | 难度 | 维护成本 | 法律风险 | 推荐度 |
|------|--------|------|---------|---------|--------|
| 1. 商家后台 API | 部分可行 | 低 | 低 | 无 | ⭐⭐⭐ |
| 2. H5 接口逆向 | 部分可行 | 极高 | 极高 | 高 | ⭐ |
| 3. ActionBook | 部分可行 | 中高 | 中 | 中 | ⭐⭐ |
| **4. Playwright 爬取** | **可行** | **中** | **中** | **中** | **⭐⭐⭐⭐** |
| 5. 第三方数据服务 | 不可行 | — | — | — | ⭐ |
| 6. 数据导出 | 部分可行 | 低 | 低 | 无 | ⭐⭐ |

---

## 推荐最终方案：组合策略

### 🏆 核心方案：Playwright 浏览器自动化（方案 4）

**用于**：获取竞品店铺列表、商品列表、价格、销量数据

**实现架构**：
```
定时调度(每日1次)
  → Playwright 打开美团 H5 页面
  → 模拟定位到目标区域
  → 搜索医疗器械关键词
  → 拦截 API 响应获取结构化数据
  → 存入数据库
  → 生成竞品分析报告
```

### 📊 辅助方案：商家后台竞对分析（方案 1）

**用于**：获取商圈级竞争指标（浏览量对比、转化率对比、客单价趋势）

**实现**：定期手动查看或用 Playwright 自动截图

### 📦 自有数据：商家后台导出自动化（方案 6）

**用于**：自有店铺的订单数据、商品数据自动化导出和分析

---

## 下一步行动

1. **验证 Playwright POC** — 用上面的代码实际测试美团 H5 页面，确认：
   - 页面是否需要登录才能搜索
   - API 响应中包含哪些字段
   - CSS 选择器是否正确
   - 反爬检测的严格程度

2. **准备基础设施**：
   - 2-3 个美团账号（手机号注册）
   - 代理 IP 服务（推荐按量付费的住宅代理）
   - 数据库设计（竞品店铺表、商品表、价格历史表）

3. **建立合规边界**：
   - 仅采集公开展示数据
   - 控制频率（每日 1-2 次全量采集）
   - 不存储用户个人信息
   - 数据仅用于内部经营分析

4. **商家后台 API 申请** — 联系美团商务（jianglu16@meituan.com）了解是否有竞品分析相关的开放接口

---

## 风险提示

⚠️ **法律风险**：大规模爬取美团数据可能违反《反不正当竞争法》和美团用户协议。建议：
- 控制采集频率和规模
- 仅用于自身经营决策
- 不转售数据
- 优先探索官方合作渠道

⚠️ **技术风险**：美团反爬机制持续升级，需要持续投入维护成本。
