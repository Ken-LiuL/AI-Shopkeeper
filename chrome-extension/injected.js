/**
 * injected.js — Hook MTDX SDK 消息 (debug v2)
 */
(function () {
  'use strict';

  const CHANNEL = '__AI_DIANZHANG_WS__';
  const origLog = console.log;

  // Debug helper — 用原始 console.log 输出，不会被自己 hook
  function dbg(...args) {
    origLog.apply(console, ['[AI店长-hook]', ...args]);
  }

  dbg('injected.js 开始加载...');

  function interceptConsole(origFn, fnName) {
    return function (...args) {
      try {
        // 遍历所有参数，找包含 sessionId 的对象
        for (let i = 0; i < args.length; i++) {
          const arg = args[i];

          // 字符串参数：检查 MTDX 标签
          if (typeof arg === 'string') {
            if (arg.includes('接收到消息')) {
              // 找后面的对象参数
              const obj = findObjectArg(args, i + 1);
              if (obj && obj.sessionId) {
                dbg('✅ 捕获到[接收消息]', 'sessionId:', obj.sessionId, 'content:', getContent(obj));
                emitMessage('customer_message', obj);
              }
            }
            if (arg.includes('session-item')) {
              const obj = findObjectArg(args, i + 1);
              if (obj) {
                dbg('✅ 捕获到[session-item]', 'poiId:', obj.poiId, 'customerInfo:', obj.customerInfo);
                emitMessage('session_item', obj);
              }
            }
          }

          // 对象参数：直接检查是否有 sessionId（兜底）
          if (arg && typeof arg === 'object' && arg.sessionId && !arg.__emitted) {
            // 标记防重复
            try { arg.__emitted = true; } catch(_) {}
          }
        }
      } catch (e) {
        // 静默
      }

      return origFn.apply(this, args);
    };
  }

  function findObjectArg(args, startIdx) {
    for (let i = startIdx; i < args.length; i++) {
      if (args[i] && typeof args[i] === 'object') return args[i];
    }
    return null;
  }

  function getContent(obj) {
    if (!obj) return '';
    // MTDX 消息的 content 可能在不同位置
    if (typeof obj.content === 'string') return obj.content.substring(0, 50);
    if (typeof obj.text === 'string') return obj.text.substring(0, 50);
    if (typeof obj.body === 'string') return obj.body.substring(0, 50);
    // content 可能是对象
    if (obj.content && typeof obj.content === 'object') {
      return JSON.stringify(obj.content).substring(0, 50);
    }
    return '(no content field)';
  }

  console.log = interceptConsole(origLog, 'log');
  console.warn = interceptConsole(console.warn, 'warn');
  console.info = interceptConsole(console.info, 'info');

  // ═══════════════════ Emit to content_script ═══════════════════
  function emitMessage(type, data) {
    try {
      const payload = extractFields(data);
      payload.__type = type;
      const json = JSON.stringify(payload);
      dbg('📤 发送 CustomEvent:', type, 'payload大小:', json.length);
      window.dispatchEvent(new CustomEvent(CHANNEL, { detail: json }));
    } catch (e) {
      dbg('❌ emitMessage 失败:', e.message);
    }
  }

  /**
   * 从 MTDX SDK 对象中安全提取字段
   * SDK 对象是类实例，可能有 getter/循环引用，所以只取已知字段
   */
  function extractFields(obj) {
    const result = {};
    const keys = [
      'sessionId', 'channelId', 'type', 'uuid', 'mid', 'appId',
      'content', 'text', 'body', 'data',
      'poiId', 'pubId', 'bizChatId', 'dialogStatus',
      'nickname', 'name'
    ];

    for (const key of keys) {
      try {
        if (key in obj) {
          const val = obj[key];
          if (val === null || val === undefined) continue;
          if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
            result[key] = val;
          }
        }
      } catch (_) {}
    }

    // customerInfo 特殊处理
    try {
      if (obj.customerInfo && typeof obj.customerInfo === 'object') {
        result.customerInfo = {};
        for (const k of ['nickname', 'name', 'avatar', 'userId', 'customerId']) {
          try {
            if (k in obj.customerInfo) {
              result.customerInfo[k] = obj.customerInfo[k];
            }
          } catch (_) {}
        }
      }
    } catch (_) {}

    return result;
  }

  // ═══════════════════ WebSocket hook (后备) ═══════════════════
  const OrigWS = window.WebSocket;
  class HookedWS extends OrigWS {
    constructor(url, protocols) {
      super(url, protocols);
      dbg('🔌 WebSocket 连接:', url);
      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed && parsed.sessionId) {
            dbg('📨 WS 消息:', parsed.sessionId);
            emitMessage('ws_message', parsed);
          }
        } catch (_) {}
      });
    }
  }
  HookedWS.prototype = OrigWS.prototype;
  Object.defineProperty(window, 'WebSocket', { value: HookedWS, writable: true, configurable: true });

  dbg('✅ 安装完成 — console.log hook + WebSocket hook');
})();
