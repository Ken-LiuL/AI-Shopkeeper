# 牵牛花（美团商家后台）数据采集研究报告

**日期**: 2026-02-12
**工具**: ActionBook CLI (CDP 模式)

---

## 1. 登录流程分析

### 登录入口
- **URL**: `https://e.waimai.meituan.com` → 自动跳转到 `https://e.waimai.meituan.com/new_fe/login_gw#/login`
- **页面标题**: 美团外卖商家版

### 登录表单结构
| 元素 | 选择器 | 说明 |
|------|--------|------|
| 账号输入框 | `#login` | `<input type="text" placeholder="输入账号">` |
| 密码输入框 | `#password` | `<input type="password" placeholder="输入密码">` |
| 隐私协议勾选 | `#checkbox` | 必须勾选才能登录 |
| 登录按钮 | `button` (页面唯一) | 黄色大按钮 |

### 登录步骤（三步验证）
1. **填写账号密码** — 注意：页面是 React/Vue SPA，标准 `fill` 无效，需要用 `nativeInputValueSetter` + `dispatchEvent` 方式
2. **滑块验证码** — Yoda CAPTCHA (`#yodaBox`)，需模拟鼠标拖拽约 215px
3. **⚠️ 短信验证码** — 手机号 132****849，需要真实手机接收验证码

### ⚠️ 关键阻碍：短信验证
- 每次登录都需要短信验证码（二次验证）
- **无法纯自动化绕过**
- 需要解决方案（见下方建议）

---

## 2. ActionBook 操作步骤

### 2.1 打开登录页
```bash
actionbook browser open "https://e.waimai.meituan.com"
```

### 2.2 填写表单（React 兼容方式）
标准 `actionbook browser fill` 对此页面无效（值不会被 React state 捕获）。需要用 `eval`：

```bash
# 填写账号
actionbook browser eval "(function(){const el=document.querySelector('#login');const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,'YOUR_ACCOUNT');el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));})()"

# 填写密码
actionbook browser eval "(function(){const el=document.querySelector('#password');const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,'YOUR_PASSWORD');el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));})()"

# 勾选协议 & 点击登录
actionbook browser eval "document.querySelector('#checkbox').click()"
actionbook browser eval "document.querySelector('button').click()"
```

### 2.3 滑块验证码
```bash
# 拖拽滑块（#yodaBox → 向右约 215px）
actionbook browser eval "(function(){
  const box=document.querySelector('#yodaBox');
  const rect=box.getBoundingClientRect();
  const startX=rect.left+rect.width/2, startY=rect.top+rect.height/2;
  box.dispatchEvent(new MouseEvent('mousedown',{clientX:startX,clientY:startY,bubbles:true}));
  for(let i=1;i<=30;i++){
    document.dispatchEvent(new MouseEvent('mousemove',{clientX:startX+(215*i/30),clientY:startY,bubbles:true}));
  }
  document.dispatchEvent(new MouseEvent('mouseup',{clientX:startX+215,clientY:startY,bubbles:true}));
})()"
```

### 2.4 短信验证码（需人工介入）
```bash
# 点击获取验证码
actionbook browser click "获取验证码按钮选择器"
# 等待人工输入验证码...
actionbook browser fill "验证码输入框选择器" "XXXXXX"
actionbook browser click "验证按钮"
```

---

## 3. 预期可获取的数据（登录后）

基于美团外卖商家后台的通用功能模块，登录后预计可以采集：

### 3.1 商品管理
- **商品列表**: 品类、名称、价格、规格、上下架状态
- **分类管理**: 商品分类树
- **SKU 详情**: 规格、库存、图片

### 3.2 经营数据
- **营业概况**: 日/周/月营业额、订单量
- **流量数据**: 曝光量、进店率、下单转化率
- **商品销量排行**
- **顾客评价统计**

### 3.3 客服/FAQ
- **自动回复设置**: 常见问题模板
- **评价管理**: 差评、好评分类
- **客服话术库**

### 3.4 店铺信息
- 店铺名称、地址、营业时间
- 配送范围、起送价
- 活动/优惠信息

---

## 4. 建议的采集方案

### 方案 A：Extension 模式（推荐）
1. 在本地 Chrome 手动登录牵牛花（完成短信验证）
2. 安装 ActionBook Chrome Extension
3. 使用 `actionbook browser --extension` 模式控制已登录的浏览器
4. 直接采集各页面数据

**优点**: 绕过登录/验证码问题，利用已有 session
**适用**: 日常数据采集

### 方案 B：Cookie 复用
1. 手动登录一次，导出 Cookie
2. 用 CDP 模式启动时注入 Cookie
3. 直接访问后台页面

```bash
# 登录后导出 cookie
actionbook browser eval "document.cookie"
# 下次启动时注入
actionbook browser eval "document.cookie='key=value; domain=.meituan.com'"
```

### 方案 C：Profile 持久化
1. 使用 ActionBook 的 profile 功能保存浏览器状态
2. 首次手动登录 → 保存 profile
3. 后续使用同一 profile 自动恢复 session

```bash
actionbook browser open "https://e.waimai.meituan.com" -P meituan
# 手动登录后，profile 会保存 cookie/localStorage
# 下次直接用同一 profile
actionbook browser open "https://e.waimai.meituan.com" -P meituan
```

---

## 5. 下一步行动

1. **[ ] 获取短信验证码** — 需要有人拿到手机验证码完成首次登录
2. **[ ] 使用 Extension 模式或 Profile 模式** — 保持登录态
3. **[ ] 登录后截图各模块页面** — 获取真实的 DOM 结构和选择器
4. **[ ] 编写数据采集脚本** — 针对每个数据模块写 ActionBook 自动化流程
5. **[ ] 研究是否有开放 API** — 美团开放平台可能提供部分数据接口

---

## 6. 技术备注

- 页面是 SPA (Single Page Application)，使用 React/Vue 框架
- 标准 `fill` 命令对 React 受控组件无效，需用 `nativeInputValueSetter` hack
- 滑块验证码 (Yoda CAPTCHA) 可通过模拟鼠标事件解决
- 短信验证码是**硬性阻碍**，无法自动化绕过
- ActionBook 的 `snapshot` 命令在此页面返回信息较少，`screenshot` + `eval` 更可靠
