/**
 * injected.js — 页面上下文，拦截美团大象 IM SDK (MTDX) 消息
 * 
 * 牵牛花客服工作台不使用原生 WebSocket，而是美团大象 IM SDK。
 * 消息通过 SDK 内部事件分发，日志格式：
 *   [MTDX] 接收到消息: {sessionId, channelId, type, uuid, ...}
 *   [MTDX] IM 接收到消息: ...
 *   [MTDX] 会话更新: ...
 * 
 * 策略：
 * 1. Hook console.log 捕获 [MTDX] 日志中的消息对象
 * 2. Hook WebSocket 作为后备
 * 3. 监听页面全局事件
 */
(function () {
  'use strict';

  const CHANNEL = '__AI_DIANZHANG_WS__';

  // ═══════════════════ 1. Hook console.log 拦截 MTDX 消息 ═══════════════════
  // MTDX SDK 通过 console.log 输出 "[MTDX] 接收到消息:" 等日志
  // 第二个参数就是消息对象
  const origLog = console.log;
  const origWarn = console.warn;
  const origInfo = console.info;

  function interceptConsole(origFn) {
    return function (...args) {
      try {
        if (args.length >= 2 && typeof args[0] === 'string') {
          const tag = args[0];

          // 捕获接收到的消息（客户发的）
          if (tag.includes('[MTDX]') && tag.includes('接收到消息')) {
            const msgObj = args[1];
            if (msgObj && typeof msgObj === 'object') {
              emitMessage('customer_message', msgObj);
            }
          }

          // 捕获会话更新（含 customerInfo 等元数据）
          if (tag.includes('[MTDX]') && tag.includes('会话更新')) {
            const updateObj = args[1];
            if (updateObj && typeof updateObj === 'object') {
              emitMessage('session_update', updateObj);
            }
          }

          // 捕获 session-item（含完整会话信息）
          if (tag.includes('session-item')) {
            const sessionItem = args[1];
            if (sessionItem && typeof sessionItem === 'object') {
              emitMessage('session_item', sessionItem);
            }
          }

          // 捕获大象透传消息
          if (tag.includes('[MTDX]') && tag.includes('大象透传')) {
            const passthrough = args[1];
            if (passthrough && typeof passthrough === 'object') {
              emitMessage('passthrough', passthrough);
            }
          }

          // 捕获发送消息（客服发的）
          if (tag.includes('[MTDX]') && (tag.includes('发送消息') || tag.includes('sendMessage'))) {
            const sentMsg = args[1];
            if (sentMsg && typeof sentMsg === 'object') {
              emitMessage('agent_message', sentMsg);
            }
          }
        }
      } catch (_) {}

      return origFn.apply(this, args);
    };
  }

  console.log = interceptConsole(origLog);
  console.warn = interceptConsole(origWarn);
  console.info = interceptConsole(origInfo);

  // ═══════════════════ 2. Hook WebSocket (后备) ═══════════════════
  const OrigWebSocket = window.WebSocket;
  class InterceptedWebSocket extends OrigWebSocket {
    constructor(url, protocols) {
      super(url, protocols);
      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed) {
            emitMessage('ws_message', parsed);
          }
        } catch (_) {}
      });
    }
  }
  InterceptedWebSocket.prototype = OrigWebSocket.prototype;
  Object.defineProperty(window, 'WebSocket', { value: InterceptedWebSocket, writable: true, configurable: true });

  // ═══════════════════ 3. 全局事件监听 ═══════════════════
  // 某些 SDK 通过 window.postMessage 或自定义事件通信
  window.addEventListener('message', (event) => {
    try {
      if (event.data && typeof event.data === 'object' && event.data.sessionId) {
        emitMessage('window_message', event.data);
      }
    } catch (_) {}
  });

  // ═══════════════════ Emit to content_script ═══════════════════
  function emitMessage(type, data) {
    try {
      // 安全序列化（处理循环引用和 DOM 对象）
      const safe = safeSerialize(data);
      if (safe) {
        window.dispatchEvent(new CustomEvent(CHANNEL, {
          detail: JSON.stringify({ __type: type, ...safe })
        }));
      }
    } catch (_) {}
  }

  function safeSerialize(obj, depth = 0) {
    if (depth > 3) return null;
    if (obj === null || obj === undefined) return obj;
    if (typeof obj !== 'object') return obj;
    if (obj instanceof HTMLElement || obj instanceof Event) return null;

    try {
      // 先试直接序列化
      JSON.stringify(obj);
      // 如果能序列化，提取关键字段
      const result = {};
      const keys = Object.keys(obj).slice(0, 30); // 限制字段数
      for (const key of keys) {
        try {
          const val = obj[key];
          if (val === null || val === undefined || typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
            result[key] = val;
          } else if (typeof val === 'object') {
            result[key] = safeSerialize(val, depth + 1);
          }
        } catch (_) {}
      }
      return result;
    } catch (_) {
      // 循环引用，提取基本字段
      const result = {};
      for (const key of ['sessionId', 'channelId', 'type', 'uuid', 'content', 'text', 'data', 'mid', 'poiId', 'customerInfo', 'dialogStatus']) {
        try {
          if (key in obj && (typeof obj[key] === 'string' || typeof obj[key] === 'number' || typeof obj[key] === 'boolean')) {
            result[key] = obj[key];
          } else if (key in obj && typeof obj[key] === 'object') {
            result[key] = safeSerialize(obj[key], depth + 1);
          }
        } catch (_) {}
      }
      return Object.keys(result).length > 0 ? result : null;
    }
  }

  console.log('[AI店长] MTDX 消息拦截器已安装（console.log hook + WebSocket hook）');
})();
