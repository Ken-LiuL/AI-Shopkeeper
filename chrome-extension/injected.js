/**
 * injected.js — Hook MTDX SDK messages
 * WS first, console fallback only.
 */
(function () {
  'use strict';

  const CHANNEL = '__AI_DIANZHANG_WS__';
  const original = {
    log: console.log,
    warn: console.warn,
    info: console.info,
  };

  const MAX_RECENT_SIGNATURES = 300;
  const RECENT_SIGNATURE_TTL_MS = 12000;
  const recentSignatures = new Map();
  let wsCaptureHealthy = false;

  function dbg(...args) {
    original.log.apply(console, ['[AI店长-hook]', ...args]);
  }

  function cleanupRecentSignatures(now = Date.now()) {
    for (const [key, ts] of recentSignatures.entries()) {
      if (!ts || (now - ts) > RECENT_SIGNATURE_TTL_MS) {
        recentSignatures.delete(key);
      }
    }
    if (recentSignatures.size <= MAX_RECENT_SIGNATURES) return;
    const overflow = recentSignatures.size - MAX_RECENT_SIGNATURES;
    const iterator = recentSignatures.keys();
    for (let i = 0; i < overflow; i++) {
      const next = iterator.next();
      if (next.done) break;
      recentSignatures.delete(next.value);
    }
  }

  function pickSessionId(obj) {
    if (!obj || typeof obj !== 'object') return '';
    const keys = ['sessionId', 'conversationId', 'session_id', 'conversation_id', 'chatId', 'chat_id'];
    for (const key of keys) {
      const value = obj[key];
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
    const inner = obj.data || obj.payload || obj.body || {};
    if (inner && typeof inner === 'object') {
      for (const key of keys) {
        const value = inner[key];
        if (typeof value === 'string' && value.trim()) return value.trim();
      }
    }
    return '';
  }

  function getMessageIdentity(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return String(obj.uuid || obj.mid || obj.messageId || obj.id || '').trim();
  }

  function getContent(obj) {
    if (!obj || typeof obj !== 'object') return '';
    for (const key of ['content', 'text', 'body', 'msg', 'message', 'summary']) {
      try {
        const val = obj[key];
        if (typeof val === 'string' && val.trim()) return val.trim().slice(0, 300);
      } catch (_) {}
    }

    const nested = obj.data || obj.payload || obj.body;
    if (nested && typeof nested === 'object') {
      for (const key of ['content', 'text', 'msg', 'message', 'summary']) {
        const val = nested[key];
        if (typeof val === 'string' && val.trim()) return val.trim().slice(0, 300);
      }
    }

    return '';
  }

  function isSystemPayloadText(text) {
    if (!text) return false;
    return text.includes('systemEventType')
      || text.includes('eventType":"system')
      || text.includes('用户与客服会话已结束');
  }

  function isAgentMessage(obj) {
    const direction = String(obj?.direction || obj?.dir || '').toLowerCase();
    if (direction === 'out' || direction === 'outbound' || direction === 'send') return true;

    if (obj?.fromMe === true || obj?.isSelf === true) return true;

    const senderType = Number(obj?.senderType || obj?.roleType || obj?.userType || NaN);
    if (senderType === 2) return true;

    const sender = String(obj?.sender || obj?.from || obj?.senderRole || '').toLowerCase();
    if (sender.includes('agent') || sender.includes('kf') || sender.includes('客服') || sender.includes('seller')) {
      return true;
    }

    const identity = getMessageIdentity(obj).toLowerCase();
    if (identity.includes('kf-') || identity.includes('agent')) return true;

    return false;
  }

  function buildSignature(type, payload) {
    const sid = pickSessionId(payload);
    const identity = getMessageIdentity(payload);
    const text = getContent(payload).slice(0, 80);
    const historySize = Array.isArray(payload?.messages) ? String(payload.messages.length) : '';
    let firstMsgIdentity = '';
    if (Array.isArray(payload?.messages) && payload.messages.length > 0) {
      const first = payload.messages[0];
      if (first && typeof first === 'object') {
        firstMsgIdentity = getMessageIdentity(first);
      }
    }
    return [type, sid, identity, text, historySize, firstMsgIdentity].join('|');
  }

  function shouldEmit(type, payload) {
    const sig = buildSignature(type, payload);
    if (!sig.replace(/\|/g, '').trim()) return true;
    cleanupRecentSignatures();
    if (recentSignatures.has(sig)) return false;
    recentSignatures.set(sig, Date.now());
    return true;
  }

  function emitPayload(payload) {
    try {
      window.dispatchEvent(new CustomEvent(CHANNEL, { detail: JSON.stringify(payload) }));
      return true;
    } catch (e) {
      dbg('❌ emit失败:', e.message);
      return false;
    }
  }

  function emitTyped(type, payload, source) {
    if (!payload || typeof payload !== 'object') return false;
    if (!shouldEmit(type, payload)) return false;

    const out = { ...payload, __type: type, __source: source || '' };
    const ok = emitPayload(out);
    if (ok) {
      wsCaptureHealthy = wsCaptureHealthy || source === 'ws';
    }
    return ok;
  }

  function findObjectArg(args, startIdx) {
    for (let i = startIdx; i < args.length; i++) {
      if (args[i] && typeof args[i] === 'object') return args[i];
    }
    return null;
  }

  function extractFields(obj) {
    const result = {};
    const keys = [
      'sessionId', 'channelId', 'type', 'uuid', 'mid', 'appId',
      'content', 'text', 'body', 'data', 'summary', 'msg', 'message',
      'poiId', 'pubId', 'bizChatId', 'dialogStatus',
      'nickname', 'name', 'direction', 'sender', 'senderType',
    ];

    for (const key of keys) {
      try {
        const val = obj[key];
        if (val === null || val === undefined) continue;
        if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') {
          result[key] = val;
        } else if (typeof val === 'object' && key !== 'customerInfo') {
          try { result[key] = JSON.stringify(val).slice(0, 1000); } catch (_) {}
        }
      } catch (_) {}
    }

    try {
      const ci = obj.customerInfo || obj.customer_info || obj.userInfo;
      if (ci && typeof ci === 'object') {
        result.customerInfo = {};
        for (const k of ['nickname', 'name', 'avatar', 'userId', 'customerId', 'uid', 'userName']) {
          try {
            const v = ci[k];
            if (v) result.customerInfo[k] = v;
          } catch (_) {}
        }
      }
    } catch (_) {}

    return result;
  }

  function emitConsoleTyped(type, rawObj) {
    if (!rawObj || typeof rawObj !== 'object') return;
    const payload = extractFields(rawObj);
    emitTyped(type, payload, 'console');
  }

  function emitHistory(sessionId, messages, source) {
    if (!sessionId || !Array.isArray(messages) || messages.length === 0) return;
    const safeMessages = messages.slice(0, 80).map((item) => {
      if (!item || typeof item !== 'object') return null;
      return source === 'ws' ? item : extractFields(item);
    }).filter(Boolean);
    if (safeMessages.length === 0) return;

    emitTyped(
      'history_messages',
      {
        sessionId,
        messages: safeMessages,
      },
      source
    );
  }

  function shouldUseConsoleFallback(kind) {
    if (!wsCaptureHealthy) return true;
    return kind === 'history';
  }

  function interceptConsole(origFn) {
    return function (...args) {
      try {
        for (let i = 0; i < args.length; i++) {
          const arg = args[i];
          if (typeof arg !== 'string') continue;

          if (arg.includes('接收到消息') && shouldUseConsoleFallback('message')) {
            const obj = findObjectArg(args, i + 1);
            if (obj && pickSessionId(obj)) {
              emitConsoleTyped('customer_message', obj);
            }
          }

          if (arg.includes('sendMessage') || arg.includes('发送消息成功')) {
            if (!shouldUseConsoleFallback('message')) continue;
            const obj = findObjectArg(args, i + 1);
            if (obj && pickSessionId(obj)) {
              emitConsoleTyped('agent_message', obj);
            }
          }

          if (arg.includes('session-item') && shouldUseConsoleFallback('message')) {
            const obj = findObjectArg(args, i + 1);
            if (obj && pickSessionId(obj)) {
              emitConsoleTyped('session_item', obj);
            }
          }

          if (arg.includes('单个会话初次历史消息查询结果') && shouldUseConsoleFallback('history')) {
            let histSessionId = '';
            let histMsgs = null;
            for (let j = i + 1; j < args.length; j++) {
              if (Array.isArray(args[j])) histMsgs = args[j];
              if (typeof args[j] === 'string' && args[j].includes('_')) histSessionId = args[j];
            }
            if (histSessionId && histMsgs && histMsgs.length > 0) {
              emitHistory(histSessionId, histMsgs, 'console');
            }
          }
        }
      } catch (_) {}

      return origFn.apply(this, args);
    };
  }

  function safeParseJSON(raw) {
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    if (!trimmed) return null;
    if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return null;
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return null;
    }
  }

  function collectWSCandidates(root) {
    const out = [];
    const queue = [root];
    const visited = new Set();
    const maxCandidates = 80;

    while (queue.length > 0 && out.length < maxCandidates) {
      const node = queue.shift();
      if (node === null || node === undefined) continue;

      if (typeof node === 'string') {
        const parsed = safeParseJSON(node);
        if (parsed) queue.push(parsed);
        continue;
      }

      if (Array.isArray(node)) {
        out.push({ __array: true, items: node });
        for (const item of node.slice(0, 30)) queue.push(item);
        continue;
      }

      if (typeof node !== 'object') continue;
      if (visited.has(node)) continue;
      visited.add(node);
      out.push(node);

      for (const key of ['data', 'payload', 'body', 'message', 'msg', 'content', 'messages', 'list', 'items', 'events']) {
        if (Object.prototype.hasOwnProperty.call(node, key)) {
          queue.push(node[key]);
        }
      }
    }

    return out;
  }

  function maybeEmitFromWSCandidate(candidate) {
    if (!candidate || typeof candidate !== 'object') return false;

    if (candidate.__array === true && Array.isArray(candidate.items)) {
      let hit = false;
      for (const item of candidate.items.slice(0, 30)) {
        hit = maybeEmitFromWSCandidate(item) || hit;
      }
      return hit;
    }

    const sid = pickSessionId(candidate);
    if (!sid) return false;

    if (Array.isArray(candidate.messages) && candidate.messages.length > 0) {
      emitHistory(sid, candidate.messages, 'ws');
      return true;
    }

    const text = getContent(candidate);

    if (text) {
      if (isSystemPayloadText(text)) {
        emitTyped('passthrough', candidate, 'ws');
      } else {
        emitTyped(isAgentMessage(candidate) ? 'agent_message' : 'customer_message', candidate, 'ws');
      }
      return true;
    }

    if (candidate.customerInfo || candidate.dialogStatus || candidate.poiId || candidate.pubId) {
      emitTyped('session_item', candidate, 'ws');
      return true;
    }

    if (shouldEmit('raw', candidate)) {
      emitPayload(candidate);
      wsCaptureHealthy = true;
      return true;
    }

    return false;
  }

  function handleWSData(rawData) {
    const parsed = safeParseJSON(rawData);
    if (!parsed) return;

    const candidates = collectWSCandidates(parsed);
    let emitted = false;
    for (const candidate of candidates) {
      emitted = maybeEmitFromWSCandidate(candidate) || emitted;
    }

    if (!emitted && typeof parsed === 'object' && parsed !== null) {
      const sid = pickSessionId(parsed);
      if (sid && shouldEmit('raw', parsed)) {
        emitPayload(parsed);
        wsCaptureHealthy = true;
      }
    }
  }

  function installWebSocketHook() {
    try {
      const NativeWS = window.WebSocket;
      if (!NativeWS || !NativeWS.prototype) {
        dbg('⚠️ WebSocket 不可用，保持 console fallback');
        return;
      }

      const WrappedWS = function (url, protocols) {
        const ws = protocols !== undefined
          ? new NativeWS(url, protocols)
          : new NativeWS(url);

        try {
          ws.addEventListener('message', (event) => {
            try {
              if (typeof event.data === 'string') {
                handleWSData(event.data);
              }
            } catch (_) {}
          });
        } catch (_) {}

        return ws;
      };

      WrappedWS.prototype = NativeWS.prototype;
      WrappedWS.CONNECTING = NativeWS.CONNECTING;
      WrappedWS.OPEN = NativeWS.OPEN;
      WrappedWS.CLOSING = NativeWS.CLOSING;
      WrappedWS.CLOSED = NativeWS.CLOSED;

      window.WebSocket = WrappedWS;
      dbg('✅ WebSocket hook 已安装（WS 优先）');
    } catch (e) {
      dbg('⚠️ WebSocket hook 安装失败:', e.message);
    }
  }

  dbg('injected.js 开始加载...');

  installWebSocketHook();

  console.log = interceptConsole(original.log);
  console.warn = interceptConsole(original.warn);
  console.info = interceptConsole(original.info);

  dbg('✅ 注入完成（WS first, console fallback）');
})();
