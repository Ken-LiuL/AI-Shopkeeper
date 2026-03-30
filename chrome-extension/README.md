# AI店长 Chrome 扩展（客服助手）

本扩展专用于 **美团买药商家后台（yiyao.meituan.com）**，负责客服消息透传：

- 拦截 WebSocket 客户消息
- 调用后端 AI 客服接口生成回复
- 自动填充或自动发送回复

面向非技术同事的详细安装和使用说明见：[Chrome扩展安装使用指南](../docs/Chrome扩展安装使用指南.md)

## 功能

- 自动捕获客户 IM 消息
- 将消息转发到后端 `POST /api/customer-service/chat`
- 支持三种回复模式：**建议**（仅展示）/ **自动填充**（填入输入框）/ **自动发送**（直接发送）
- 弹窗可配置 API 地址、回复模式和连接测试
- 提供调试日志面板

## 安装

1. 打开 `chrome://extensions`
2. 开启右上角「开发者模式」
3. 点击「加载已解压的扩展程序」
4. 选择本项目的 `chrome-extension/` 目录

## 配置

1. 点击扩展图标打开弹窗
2. 在「客服设置」中填写：
   - `客服 API 基础地址`（默认 `http://192.144.227.205:8000`）
   - `回复模式`（建议 / 自动填充 / 自动发送）
   - `店铺 ID`（可选）
3. 点击「测试连接」验证服务可用

## 使用

1. 打开并登录 `https://yiyao.meituan.com`
2. 进入客服聊天页面
3. 扩展自动识别客户消息并调用 AI 生成回复建议
4. 页面右下角悬浮面板显示状态和最近回复记录

## 文件说明

| 文件 | 说明 |
|------|------|
| `manifest.json` | 扩展配置（权限、content script、popup） |
| `background.js` | Service Worker，负责消息转发和 API 调用 |
| `content_script.js` | 注入页面，监听 WebSocket 消息 |
| `injected.js` | 注入页面内部，拦截原生 WebSocket |
| `popup.html` / `popup.js` | 配置弹窗 |
| `panel.css` | 悬浮面板样式 |
