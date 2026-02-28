# 美团商家后台客服 IM API 发现报告

## 执行时间
- 执行日期：2026-02-28 15:34-15:35
- 发现 API 总数：超过1200个请求，其中IM相关API约50个
- 状态：Phase 1 成功完成，Phase 2 待开发

## 🎯 关键 IM API 发现

### 1. 聊天列表相关 (api.neixin.cn)

#### 1.1 聊天列表获取
- **API**: `https://api.neixin.cn/msg/api/pub/v1/chatlist`
- **作用**: 获取会话列表
- **版本**: v1
- **方法**: GET

#### 1.2 聊天列表信息
- **API**: `https://api.neixin.cn/msg/api/pub/v1/chatlist/info`
- **作用**: 获取聊天列表详细信息
- **版本**: v1

#### 1.3 V3版本聊天列表
- **API**: `https://api.neixin.cn/msg/api/chat/v3/chatlist/appid`
- **作用**: 获取应用关联的聊天列表
- **版本**: v3
- **API**: `https://api.neixin.cn/msg/api/chat/v3/chatlist/info`
- **作用**: V3版本聊天列表信息

### 2. 聊天记录相关 (api.neixin.cn)

#### 2.1 🔥 聊天历史记录 (最重要)
- **API**: `https://api.neixin.cn/msg/api/pub/v3/history/chat/range`
- **作用**: 获取指定范围的聊天历史记录
- **版本**: v3
- **重要性**: ⭐⭐⭐⭐⭐ (核心API，多次调用，这是获取聊天消息的主要端点)

#### 2.2 未读消息
- **API**: `https://api.neixin.cn/pubread/v2/user/chat/getUnread`
- **作用**: 获取未读消息数量
- **版本**: v2

### 3. 其他消息相关 (api.neixin.cn)

#### 3.1 离线数据
- **API**: `https://api.neixin.cn/msg/api/data/v1/offline`
- **作用**: 离线消息数据

#### 3.2 阅读列表
- **API**: `https://api.neixin.cn/read/api/v2/list`
- **作用**: 消息阅读状态列表

#### 3.3 表情包
- **API**: `https://api.neixin.cn/uinfo/api/v1/stickerConf/getPackages`
- **作用**: 获取表情包配置

### 4. 美团工作台对话相关 (qnh.meituan.com)

#### 4.1 对话记录
- **API**: `https://qnh.meituan.com/workbench/b/dialog/chatting/records`
- **作用**: 获取对话聊天记录

#### 4.2 待处理记录
- **API**: `https://qnh.meituan.com/workbench/b/dialog/pending/records`
- **作用**: 获取待处理的对话记录

#### 4.3 客户姓名
- **API**: `https://qnh.meituan.com/workbench/b/dialog/chatting/customerName`
- **作用**: 获取客户姓名信息

#### 4.4 快捷回复
- **API**: `https://qnh.meituan.com/workbench/b/dialog/quick-reply/list`
- **作用**: 获取快捷回复模板

#### 4.5 配置信息
- **API**: `https://qnh.meituan.com/workbench/b/dialog/config/timeout`
- **作用**: 获取对话超时配置

## 🔧 API 特征分析

### 认证机制
所有API都使用复杂的美团签名认证：
- `yodaReady=h5` - H5就绪标识
- `csecplatform=4&csecversion=4.2.0` - 安全平台版本
- `mtgsig={...}` - 美团签名，包含加密参数：
  - `a1`: 版本号 "1.2"
  - `a2`: 时间戳
  - `a3`: 设备标识
  - `a5`: 加密签名
  - `a6`: 更复杂的加密数据
  - `a8`: 校验码
  - `a9`: 平台版本信息
  - `a10`: 其他参数

### Cookie依赖
- 依赖已有的cookie认证
- 需要 `_qnh_account_id` 和 `_qnh_tenant_id` 等关键信息

## 📊 API 调用模式分析

### 页面加载时的API调用序列：
1. 首先调用 `chatlist` 获取会话列表
2. 然后调用 `chatlist/info` 获取详细信息
3. 多次调用 `history/chat/range` 获取具体消息内容
4. 调用 `getUnread` 获取未读数量
5. 调用美团工作台相关API获取补充信息

### 关键发现：
- `history/chat/range` API 被多次调用，是获取消息内容的核心端点
- API 都使用 GET 方法，通过 URL 参数传递查询条件
- 每个API都有独立的签名，防止重放攻击

## 🎯 Phase 2 实施建议

### 优先开发的API：
1. **`api.neixin.cn/msg/api/pub/v1/chatlist`** - 获取会话列表
2. **`api.neixin.cn/msg/api/pub/v3/history/chat/range`** - 获取消息详情 ⭐⭐⭐⭐⭐
3. **`qnh.meituan.com/workbench/b/dialog/chatting/customerName`** - 获取客户信息

### 技术实现要点：
1. 复制现有的cookie和签名机制
2. 实现动态签名生成（基于时间戳）
3. 解析返回的JSON数据结构
4. 处理分页加载（如果存在）
5. 实现错误处理和重试机制

### 数据结构设计：
```json
{
  "scraped_at": "2026-02-28T15:30:00",
  "conversations": [
    {
      "session_id": "从chatlist API获取",
      "customer_name": "从customerName API获取",
      "last_message_time": "最后消息时间",
      "messages": [
        {
          "message_id": "消息ID",
          "role": "customer|agent",
          "content": "消息内容",
          "timestamp": "发送时间",
          "type": "text|image|sticker"
        }
      ]
    }
  ]
}
```

## ⚠️ 注意事项
1. 所有API需要有效的cookie认证
2. 签名机制复杂，需要仔细分析参数生成规则
3. API调用频率需要控制，避免触发反爬机制
4. 需要处理分页，一次可能无法获取所有历史记录
5. 部分API可能有时间范围限制

## 下一步行动
1. 分析 `history/chat/range` API 的参数格式
2. 实现签名生成算法
3. 开发 Phase 2 批量抓取功能
4. 测试完整的数据抓取流程
