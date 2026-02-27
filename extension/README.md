# AI店长数据同步器 Chrome Extension

美团牵牛花后台数据自动同步到 AI 店长系统的 Chrome 扩展。

## 功能特性

- **自动定时同步** - 根据数据重要性设置不同的同步频率
- **智能 API 路由** - goldengateway 通过页面上下文执行，绕过 mtgsig 签名限制
- **实时状态监控** - 显示各数据源的同步状态和错误信息
- **灵活配置管理** - 支持自定义后端 URL、API Key 和同步频率
- **错误处理机制** - 网络失败、登录过期等异常情况的 graceful 处理

## 数据源

### 高频同步 (5分钟)
- **订单数据** - 实时订单信息

### 中频同步 (15分钟)
- **库存数据** - 商品库存状态
- **客服消息** - IM 即时消息

### 低频同步 (1小时)
- **商品数据** - SPU/SKU 信息、价格、分类
- **经营指标** - 热销排行、渠道分布、消费排行
- **流量数据** - 访问统计、渠道分布
- **客服会话** - 会话列表和详情

### 每日同步 (24小时)
- **财务数据** - 结算、收入统计
- **退款数据** - 退款记录和处理状态

## 技术架构

### Manifest V3
- Service Worker 后台脚本
- Content Script 页面注入
- 安全的跨域通信机制

### API 路由策略
1. **goldengateway API** - 通过页面上下文执行 (需要 mtgsig 签名)
2. **qnh-gw3 API** - 通过页面上下文执行 (需要 h5guard 签名)
3. **基础 API** - 直接 Content Script 调用 (Cookie 认证)
4. **Neixin IM API** - 支持降级到页面上下文

### 数据流程
```
牵牛花页面 → Content Script → Background Service Worker → AI店长后端
```

## 安装使用

### 1. 开发者模式安装
1. 打开 Chrome 浏览器
2. 访问 `chrome://extensions/`
3. 开启"开发者模式"
4. 点击"加载已解压的扩展程序"
5. 选择 `extension` 目录

### 2. 配置后端连接
1. 点击扩展图标打开弹窗
2. 配置后端 URL: `https://ai-shopkeeper-kk.fly.dev`
3. 输入 API Key（可选）
4. 点击"保存配置"

### 3. 登录牵牛花后台
1. 访问 https://qnh.meituan.com
2. 正常登录商户账号
3. 扩展会自动检测登录状态

### 4. 开始同步
- **自动同步** - 扩展会按配置的频率自动同步
- **手动同步** - 点击弹窗中的"同步所有数据"按钮

## 配置说明

### 基本配置
- **后端 URL** - AI 店长后端服务地址
- **API Key** - 后端认证密钥（可选）

### 同步频率
- **订单** - 5分钟（高频）
- **库存、客服消息** - 15分钟（中频）
- **商品、指标、流量** - 1小时（低频）
- **财务、退款** - 24小时（每日）

### 高级选项
- **重试次数** - 失败时的重试次数（默认3次）
- **重试延迟** - 重试间隔时间（默认5秒）
- **批处理大小** - 每批次处理的记录数（默认50）

## 错误处理

### 常见问题
1. **"未找到牵牛花页面"** - 请确保已登录 qnh.meituan.com
2. **"连接失败"** - 检查后端 URL 和网络连接
3. **"API 错误 403"** - 登录状态过期，请重新登录
4. **"数据获取失败"** - API 可能临时不可用，扩展会自动重试

### 日志查看
1. 右键扩展图标 → "选项"
2. 查看"同步日志"部分
3. 或打开开发者工具查看 Console

## 开发调试

### Chrome DevTools
1. 右键扩展图标 → "检查弹出式窗口" - 调试 popup
2. `chrome://extensions/` → 扩展详情 → "检查视图: Service Worker" - 调试 background
3. 页面 F12 → Console - 查看 content script 日志

### 日志输出
扩展在各个组件都有详细的 console.log 输出，便于调试。

### 文件结构
```
extension/
├── manifest.json          # 扩展清单文件
├── background.js          # Service Worker 后台脚本
├── content.js             # Content Script 页面脚本
├── inject.js              # 页面上下文注入脚本
├── popup.html/js/css      # 弹窗界面
├── options.html/js        # 设置页面
├── config/
│   └── data_sources.js    # 数据源配置
├── lib/
│   └── api.js             # API 调用封装
├── icons/                 # 扩展图标
└── README.md              # 说明文档
```

## 后端集成

扩展会向后端发送 POST 请求到 `/api/sync/push` 端点：

```json
{
  "source": "products",
  "data": [...],
  "timestamp": "2026-02-27T14:39:00.000Z",
  "metadata": {
    "extensionVersion": "1.0.0",
    "tabId": 12345,
    "tabUrl": "https://qnh.meituan.com/home.html"
  }
}
```

后端需要返回 JSON 格式的响应：
```json
{
  "ok": true,
  "records": 42,
  "message": "success"
}
```

## License

MIT License - 仅供内部使用
