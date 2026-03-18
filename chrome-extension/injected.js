/**
 * injected.js — Hook MTDX SDK 消息 (v3 — 修复 prototype 错误 + 时序问题)
 */
(function () {
  'use strict';

  const CHANNEL = '__AI_DIANZHANG_WS__';
  const origLog = console.log;

  function dbg(...args) {
    origLog.apply(console, ['[AI店长-hook]', ...args]);
  }

  dbg('injected.js 开始加载...');

  // ═══════════════════ Console Hook ═══════════════════
  function interceptConsole(origFn) {
    return function (...args) {
      try {
        for (let i = 0; i < args.length; i++) {
          const arg = args[i];
          if (typeof arg === 'string') {
            if (arg.includes('接收到消息')) {
              const obj = findObjectArg(args, i + 1);
              if (obj && obj.sessionId) {
                dbg('✅ 捕获[接收消息]', obj.sessionId, getContent(obj));
                emitMessage('customer_message', obj);
              }
            }
            if (arg.includes('session-item')) {
              const obj = findObjectArg(args, i + 1);
              if (obj) {
                dbg('✅ 捕获[session-item]', obj.poiId);
                emitMessage('session_item', obj);
              }
            }
            // 捕获客服发送
            if (arg.includes('sendMessage') || arg.includes('发送消息成功')) {
              const obj = findObjectArg(args, i + 1);
              if (obj && obj.sessionId) {
                dbg('✅ 捕获[发送消息]', obj.sessionId, getContent(obj));
                emitMessage('agent_message', obj);
              }
            }
            // ─── 历史消息采集 ───────────────────────────────────────────
            // "[dev] 单个会话初次历史消息查询结果 {lastMsgId} [{...}×N] {sessionId}"
            // args: [tag, lastMsgId, arrayOfMessages, sessionId]
            if (arg.includes('单个会话初次历史消息查询结果')) {
              // 找 sessionId（最后一个字符串参数）
              let histSessionId = '';
              let histMsgs = null;
              for (let j = i + 1; j < args.length; j++) {
                if (Array.isArray(args[j])) histMsgs = args[j];
                if (typeof args[j] === 'string' && args[j].includes('_')) histSessionId = args[j];
              }
              if (histSessionId && histMsgs && histMsgs.length > 0) {
                dbg('📚 历史消息', histSessionId, histMsgs.length, '条');
                // 序列化每条历史消息
                const safeMessages = histMsgs.slice(0, 50).map(m => {
                  try { return extractFields(m); } catch (_) { return null; }
                }).filter(Boolean);
                window.dispatchEvent(new CustomEvent(CHANNEL, {
                  detail: JSON.stringify({
                    __type: 'history_messages',
                    sessionId: histSessionId,
                    messages: safeMessages
                  })
                }));
              }
            }
          }
        }
      } catch (_) {}
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
    if (typeof obj.content === 'string' && obj.content.trim()) return obj.content.substring(0, 50);
    if (typeof obj.text === 'string' && obj.text.trim()) return obj.text.substring(0, 50);
    if (typeof obj.body === 'string' && obj.body.trim()) return obj.body.substring(0, 50);
    if (obj.content && typeof obj.content === 'object') {
      return JSON.stringify(obj.content).substring(0, 50);
    }
    // 卡片消息：从 data 字段尝试
    if (typeof obj.data === 'string') {
      try {
        const d = JSON.parse(obj.data);
        return (d.summary || d.content || d.text || JSON.stringify(d)).substring(0, 50);
      } catch (_) {}
      return obj.data.substring(0, 50);
    }
    return `(type:${obj.type||'?'})`;
  }

  console.log = interceptConsole(origLog);
  console.warn = interceptConsole(console.warn);
  console.info = interceptConsole(console.info);

  // ═══════════════════ Emit ═══════════════════
  function emitMessage(type, data) {
    try {
      const payload = extractFields(data);
      payload.__type = type;
      const json = JSON.stringify(payload);
      dbg('📤 CustomEvent:', type, json.length, 'bytes');
      window.dispatchEvent(new CustomEvent(CHANNEL, { detail: json }));
    } catch (e) {
      dbg('❌ emit失败:', e.message);
    }
  }

  function extractFields(obj) {
    const result = {};
    const keys = [
      'sessionId', 'channelId', 'type', 'uuid', 'mid', 'appId',
      'content', 'text', 'body', 'data', 'summary',
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
    try {
      if (obj.customerInfo && typeof obj.customerInfo === 'object') {
        result.customerInfo = {};
        for (const k of ['nickname', 'name', 'avatar', 'userId', 'customerId', 'uid']) {
          try { if (k in obj.customerInfo) result.customerInfo[k] = obj.customerInfo[k]; } catch (_) {}
        }
      }
    } catch (_) {}
    return result;
  }

  // ═══════════════════ WebSocket hook (安全版) ═══════════════════
  try {
    const OrigWS = window.WebSocket;
    const origAddEventListener = OrigWS.prototype.addEventListener;

    // 不替换 WebSocket 类，只 patch prototype.addEventListener
    const origSend = OrigWS.prototype.send;
    OrigWS.prototype.send = function (data) {
      // 可选：捕获发送的消息
      return origSend.call(this, data);
    };

    // 用 MutationObserver-style 的方式 hook 新创建的 WS
    const origWSConstructor = window.WebSocket;
    window.WebSocket = function (url, protocols) {
      dbg('🔌 WS连接:', typeof url === 'string' ? url.substring(0, 80) : url);
      const ws = protocols !== undefined
        ? new origWSConstructor(url, protocols)
        : new origWSConstructor(url);
      try {
        ws.addEventListener('message', function (event) {
          try {
            if (typeof event.data === 'string') {
              const parsed = JSON.parse(event.data);
              if (parsed && parsed.sessionId) {
                emitMessage('ws_message', parsed);
              }
            }
          } catch (_) {}
        });
      } catch (_) {}
      return ws;
    };
    window.WebSocket.prototype = origWSConstructor.prototype;
    window.WebSocket.CONNECTING = origWSConstructor.CONNECTING;
    window.WebSocket.OPEN = origWSConstructor.OPEN;
    window.WebSocket.CLOSING = origWSConstructor.CLOSING;
    window.WebSocket.CLOSED = origWSConstructor.CLOSED;
  } catch (e) {
    dbg('⚠️ WebSocket hook 跳过:', e.message);
  }

  dbg('✅ 安装完成');
})();
