/**
 * content_script.js — AI店长 Chrome Extension v3
 * 
 * 核心改进：完全数据驱动的多会话管理
 * - WS 消息自带 sessionId → 直接用，不依赖 DOM 猜测
 * - 所有会话并行处理，AI 建议按 session 隔离
 * - 面板显示所有待处理建议，标注会话来源
 * - 聊天记录全量采集（客户 + 客服），后端去重
 */
(function () {
  'use strict';
  if (window.__AI_DIANZHANG_CS_LOADED__) return;
  window.__AI_DIANZHANG_CS_LOADED__ = true;

  /* ═══════════════════ State ═══════════════════ */
  let enabled = true;
  let mode = 'suggest'; // 'suggest' | 'auto-fill' | 'auto-send'
  const processedMessages = new Set();
  const recentMessageFingerprints = new Map();
  const MESSAGE_FP_TTL_MS = 12000;

  // ── 多 Session 管理（纯数据驱动）─────────────────────────────
  // sessionData: { [sessionId]: { replies: [], customerName: '', lastActivity: Date, pendingCount: 0 } }
  const sessionData = {};
  // 所有待处理建议（跨 session 的优先队列）
  const pendingQueue = []; // [{ id, text, time, sessionId, customerName, ... }]
  let activeSessionId = '';
  let panelViewMode = 'active'; // 'active' | 'all'
  let orderPanelCache = { sessionId: '', ts: 0, data: null };
  const LOCAL_STATE_KEY = 'aidz_panel_state_v1';
  const LOCAL_STATE_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
  const LOCAL_STATE_MAX_SESSIONS = 80;
  const LOCAL_STATE_MAX_REPLIES_PER_SESSION = 30;
  let persistStateTimer = null;
  let localStateRestored = false;

  const ORDER_PANEL_FIELD_ALIASES = {
    order_id: ['单号', '订单号'],
    payment_amount: ['顾客支付', '支付金额', '实付金额'],
    delivery_status: ['配送状态', '物流状态'],
    rider: ['骑手', '配送员'],
    order_time: ['下单时间', '下单时'],
    customer: ['顾客', '买家', '收货人'],
    address: ['收货地', '收货地址', '地址'],
    store: ['门店', '店铺'],
  };

  /* ═══════════════════ Session Helpers ═══════════════════ */
  function safeLocalGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function safeLocalSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch (err) {
      console.warn('[AI店长] localStorage 写入失败:', err?.message || err);
      return false;
    }
  }

  function safeLocalRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (_) {}
  }

  function normalizeStoredReply(raw, sid) {
    if (!raw || typeof raw !== 'object') return null;
    const createdAt = Number(raw.createdAt || 0) || Date.now();
    if ((Date.now() - createdAt) > LOCAL_STATE_RETENTION_MS) return null;
    const status = ['pending', 'adopted', 'edited', 'ignored'].includes(raw.status)
      ? raw.status
      : 'pending';
    const text = typeof raw.text === 'string' ? raw.text : '';
    if (!text.trim()) return null;
    return {
      id: typeof raw.id === 'string' && raw.id ? raw.id : `local-${createdAt}-${Math.random().toString(36).slice(2, 7)}`,
      text,
      time: typeof raw.time === 'string' && raw.time ? raw.time : new Date(createdAt).toLocaleTimeString(),
      sessionId: (typeof raw.sessionId === 'string' && raw.sessionId) || sid,
      messageId: typeof raw.messageId === 'string' ? raw.messageId : '',
      aiReplyId: typeof raw.aiReplyId === 'string' ? raw.aiReplyId : '',
      customerName: typeof raw.customerName === 'string' ? raw.customerName : '',
      createdAt,
      status,
      editedText: typeof raw.editedText === 'string' ? raw.editedText : '',
      feedbackRating: raw.feedbackRating === 'good' || raw.feedbackRating === 'bad' ? raw.feedbackRating : '',
      contextTrace: (raw.contextTrace && typeof raw.contextTrace === 'object') ? raw.contextTrace : {},
      needsHuman: Boolean(raw.needsHuman),
    };
  }

  function pruneLocalStateSessions(now = Date.now()) {
    const cutoff = now - LOCAL_STATE_RETENTION_MS;
    for (const sid of Object.keys(sessionData)) {
      const session = sessionData[sid];
      if (!session || typeof session !== 'object') {
        delete sessionData[sid];
        continue;
      }
      const replies = Array.isArray(session.replies) ? session.replies : [];
      const cleanedReplies = replies
        .map((r) => normalizeStoredReply(r, sid))
        .filter(Boolean)
        .filter((r) => (r.createdAt || 0) >= cutoff)
        .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
        .slice(0, LOCAL_STATE_MAX_REPLIES_PER_SESSION);
      session.replies = cleanedReplies;
      session.pendingCount = cleanedReplies.filter((r) => r.status === 'pending').length;
      session.lastActivity = Number(session.lastActivity || 0);
      const latestReplyAt = cleanedReplies[0]?.createdAt || 0;
      if (!session.lastActivity || session.lastActivity < latestReplyAt) {
        session.lastActivity = latestReplyAt || now;
      }
      const hasRecentActivity = (session.lastActivity || 0) >= cutoff;
      if (!hasRecentActivity && session.pendingCount <= 0 && cleanedReplies.length === 0) {
        delete sessionData[sid];
      }
    }
  }

  function rebuildPendingQueueFromSessionData() {
    pendingQueue.length = 0;
    const pendingItems = [];
    for (const [sid, session] of Object.entries(sessionData)) {
      if (!session || !Array.isArray(session.replies)) continue;
      for (const reply of session.replies) {
        if (reply.status === 'pending') {
          pendingItems.push({ ...reply, sessionId: reply.sessionId || sid });
        }
      }
      session.pendingCount = session.replies.filter((r) => r.status === 'pending').length;
    }
    pendingItems
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
      .slice(0, 50)
      .forEach((item) => pendingQueue.push(item));
  }

  function persistLocalStateNow() {
    pruneLocalStateSessions();
    rebuildPendingQueueFromSessionData();

    const sortedSessions = Object.entries(sessionData)
      .sort((a, b) => (b[1]?.lastActivity || 0) - (a[1]?.lastActivity || 0))
      .slice(0, LOCAL_STATE_MAX_SESSIONS);

    const sessionsPayload = {};
    for (const [sid, session] of sortedSessions) {
      sessionsPayload[sid] = {
        customerName: typeof session.customerName === 'string' ? session.customerName : '',
        lastActivity: Number(session.lastActivity || Date.now()),
        replies: (session.replies || []).map((r) => ({
          id: r.id || '',
          text: r.text || '',
          time: r.time || '',
          sessionId: r.sessionId || sid,
          messageId: r.messageId || '',
          aiReplyId: r.aiReplyId || '',
          customerName: r.customerName || '',
          createdAt: Number(r.createdAt || Date.now()),
          status: r.status || 'pending',
          editedText: r.editedText || '',
          feedbackRating: r.feedbackRating || '',
          contextTrace: (r.contextTrace && typeof r.contextTrace === 'object') ? r.contextTrace : {},
          needsHuman: Boolean(r.needsHuman),
        })),
      };
    }

    const payload = {
      version: 1,
      savedAt: Date.now(),
      activeSessionId: activeSessionId || '',
      panelViewMode: panelViewMode === 'all' ? 'all' : 'active',
      sessions: sessionsPayload,
    };

    safeLocalSet(LOCAL_STATE_KEY, JSON.stringify(payload));
  }

  function schedulePersistLocalState(delay = 220) {
    if (persistStateTimer) {
      clearTimeout(persistStateTimer);
    }
    persistStateTimer = setTimeout(() => {
      persistStateTimer = null;
      persistLocalStateNow();
    }, delay);
  }

  function restoreLocalState() {
    if (localStateRestored) return;
    localStateRestored = true;

    const raw = safeLocalGet(LOCAL_STATE_KEY);
    if (!raw) return;

    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') {
        safeLocalRemove(LOCAL_STATE_KEY);
        return;
      }

      const savedAt = Number(parsed.savedAt || 0);
      if (savedAt > 0 && (Date.now() - savedAt) > LOCAL_STATE_RETENTION_MS) {
        safeLocalRemove(LOCAL_STATE_KEY);
        return;
      }

      const sessions = parsed.sessions && typeof parsed.sessions === 'object' ? parsed.sessions : {};
      for (const [sid, rawSession] of Object.entries(sessions)) {
        if (!sid || !rawSession || typeof rawSession !== 'object') continue;
        const replies = Array.isArray(rawSession.replies)
          ? rawSession.replies.map((r) => normalizeStoredReply(r, sid)).filter(Boolean)
          : [];
        sessionData[sid] = {
          customerName: typeof rawSession.customerName === 'string' ? rawSession.customerName : '',
          lastActivity: Number(rawSession.lastActivity || replies[0]?.createdAt || Date.now()),
          replies: replies
            .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
            .slice(0, LOCAL_STATE_MAX_REPLIES_PER_SESSION),
          pendingCount: 0,
        };
      }

      pruneLocalStateSessions();
      rebuildPendingQueueFromSessionData();

      if (typeof parsed.activeSessionId === 'string' && sessionData[parsed.activeSessionId]) {
        activeSessionId = parsed.activeSessionId;
      }
      if (parsed.panelViewMode === 'all' || parsed.panelViewMode === 'active') {
        panelViewMode = parsed.panelViewMode;
      }
    } catch (_) {
      safeLocalRemove(LOCAL_STATE_KEY);
    }
  }

  function getSession(sessionId) {
    let created = false;
    if (!sessionData[sessionId]) {
      sessionData[sessionId] = {
        replies: [],
        customerName: '',
        lastActivity: Date.now(),
        pendingCount: 0,
      };
      created = true;
    }
    sessionData[sessionId].lastActivity = Date.now();
    if (created) schedulePersistLocalState(80);
    return sessionData[sessionId];
  }

  function addReplyToSession(sessionId, replyObj) {
    const session = getSession(sessionId);
    session.replies.unshift(replyObj);
    if (session.replies.length > 20) session.replies.pop();
    if (replyObj.status === 'pending') {
      session.pendingCount++;
      pendingQueue.unshift(replyObj);
      if (pendingQueue.length > 50) pendingQueue.pop();
    }
    // 清理超过 1 小时不活跃的 session
    const cutoff = Date.now() - 3600000;
    for (const sid of Object.keys(sessionData)) {
      if (sessionData[sid].lastActivity < cutoff && sessionData[sid].pendingCount === 0) {
        delete sessionData[sid];
      }
    }
    schedulePersistLocalState();
  }

  function extractSessionId(data) {
    // 从 WS 消息的各种字段名中提取 session ID
    const candidates = [
      data.sessionId, data.conversationId, data.session_id,
      data.conversation_id, data.chatId, data.chat_id,
    ];
    const inner = data.data || data.body || data.payload || {};
    candidates.push(
      inner.sessionId, inner.conversationId, inner.session_id,
      inner.conversation_id, inner.chatId, inner.chat_id,
    );
    for (const c of candidates) {
      if (c && typeof c === 'string' && c.trim() !== '') return c;
    }
    return null;
  }

  function extractCustomerName(data) {
    const sources = [
      data.customer, data.sender, data.user,
      data.data?.customer, data.data?.sender, data.data?.user,
      data.payload?.customer, data.payload?.sender,
    ];
    for (const s of sources) {
      if (!s) continue;
      const name = s.name || s.nickname || s.nick || s.displayName || s.userName;
      if (name && typeof name === 'string') return name;
    }
    return '';
  }

  function normalizeText(raw) {
    if (typeof raw === 'string') return raw.trim();
    if (typeof raw === 'number' || typeof raw === 'boolean') return String(raw);
    if (raw && typeof raw === 'object') {
      for (const key of ['text', 'content', 'msg', 'message', 'plain']) {
        if (typeof raw[key] === 'string' && raw[key].trim()) {
          return raw[key].trim();
        }
      }
      try {
        const serialized = JSON.stringify(raw);
        return typeof serialized === 'string' ? serialized.slice(0, 500) : '';
      } catch (_) {
        return '';
      }
    }
    return '';
  }

  function isNonActionablePlaceholderText(text) {
    const normalized = String(text || '').trim().replace(/\s+/g, '');
    if (!normalized) return false;
    if (['[图片消息]', '[卡片消息]', '[语音消息]', '[系统消息]', '[文件消息]'].includes(normalized)) {
      return true;
    }
    if (normalized.startsWith('[图片消息]')) {
      const tail = normalized.slice('[图片消息]'.length);
      if (!tail || tail === '[图片地址]' || tail.startsWith('[图片地址]http')) {
        return true;
      }
    }
    if (normalized.startsWith('[卡片消息]') && normalized.length <= 10) {
      return true;
    }
    return false;
  }

  function isLikelySystemPayloadText(text) {
    if (!text || typeof text !== 'string') return false;
    const trimmed = text.trim();
    if (!trimmed) return true;
    if (
      trimmed.includes('"systemEventType"')
      || trimmed.includes('systemEventType')
      || trimmed.includes('"eventType":"system"')
      || trimmed.includes('用户与客服会话已结束')
    ) {
      return true;
    }
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      const systemKeys = ['systemEventType', 'eventType', 'dialogStatus', 'sessionStatus'];
      let hit = 0;
      for (const key of systemKeys) {
        if (trimmed.includes(`"${key}"`) || trimmed.includes(`${key}:`)) hit++;
      }
      if (hit >= 1) return true;
    }
    return false;
  }

  function parseObjectMaybe(val) {
    if (!val) return null;
    if (typeof val === 'object') return val;
    if (typeof val === 'string') {
      const trimmed = val.trim();
      if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return null;
      try {
        const parsed = JSON.parse(trimmed);
        return parsed && typeof parsed === 'object' ? parsed : null;
      } catch (_) {
        return null;
      }
    }
    return null;
  }

  function isLikelyAgentEnvelope(data) {
    const stack = [data, parseObjectMaybe(data?.data), parseObjectMaybe(data?.payload), parseObjectMaybe(data?.body)]
      .filter(Boolean);

    for (const obj of stack) {
      const fromCustomer = obj.fromCustomer;
      if (fromCustomer === false || fromCustomer === 'false') return true;

      if (obj.fromMe === true || obj.isSelf === true || obj.mine === true) return true;

      const direction = String(obj.direction || obj.dir || '').toLowerCase();
      if (direction === 'out' || direction === 'outbound' || direction === 'send') return true;

      const senderType = Number(obj.senderType || obj.roleType || obj.userType || obj.fromType || NaN);
      if (senderType === 2 || senderType === 3) return true;

      const roleText = String(
        obj.role
        || obj.senderRole
        || obj.sender
        || obj.from
        || obj.userRole
        || ''
      ).toLowerCase();
      if (
        roleText.includes('agent')
        || roleText.includes('merchant')
        || roleText.includes('seller')
        || roleText.includes('客服')
        || roleText.includes('商家')
        || roleText.includes('kf')
      ) {
        return true;
      }

      const msgId = String(obj.uuid || obj.mid || obj.msgId || '').toLowerCase();
      if (msgId.includes('kf-') || msgId.includes('agent')) return true;
    }

    return false;
  }

  function getPendingTotal() {
    return Object.values(sessionData).reduce((sum, s) => sum + (s.pendingCount || 0), 0);
  }

  function getSessionPending(sessionId) {
    const session = sessionData[sessionId];
    if (!session) return 0;
    return session.replies.filter((r) => r.status === 'pending').length;
  }

  function resolveDisplaySessionId() {
    if (panelViewMode === 'all') return '';
    if (activeSessionId && sessionData[activeSessionId]) return activeSessionId;
    let bestSid = '';
    let bestTs = 0;
    for (const [sid, data] of Object.entries(sessionData)) {
      const ts = data.lastActivity || 0;
      if (ts > bestTs) {
        bestTs = ts;
        bestSid = sid;
      }
    }
    return bestSid;
  }

  function normalizeSessionId(rawSessionId, fallbackSeed = '') {
    const sid = typeof rawSessionId === 'string' ? rawSessionId.trim() : '';
    if (sid) return sid;

    const seed = typeof fallbackSeed === 'string' ? fallbackSeed.trim() : '';
    if (seed) return `mtdx-${hashCode(seed.toLowerCase())}`;

    return `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function buildSessionSeed(...sources) {
    const keys = [
      'customerId',
      'uid',
      'userId',
      'user_id',
      'buyerId',
      'accountId',
      'openId',
      'channelId',
      'channel_id',
      'storeId',
      'shopId',
      'poiId',
      'tenantId',
      'memberId',
      'member_id',
      'imUserId',
      'im_user_id',
      'senderId',
      'sender_id',
      'fromId',
      'from_id',
      'toId',
      'to_id',
      'nickname',
      'name',
      'displayName',
      'userName',
    ];
    const parts = [];
    const seen = new Set();

    function addPart(key, value) {
      const normalized = String(value || '').trim().toLowerCase();
      if (!normalized) return;
      const part = `${key}:${normalized}`;
      if (seen.has(part)) return;
      seen.add(part);
      parts.push(part);
    }

    for (const src of sources) {
      if (!src) continue;
      if (typeof src === 'string' && src.trim()) {
        addPart('raw', src);
        continue;
      }
      if (typeof src === 'object') {
        for (const key of keys) {
          if (typeof src[key] === 'string' && src[key].trim()) {
            addPart(key, src[key]);
          }
          if (typeof src[key] === 'number') {
            addPart(key, src[key]);
          }
        }
      }
    }
    return parts.slice(0, 5).join('|');
  }

  function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  }

  function generateLocalId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function sanitizePanelText(text, maxLen = 1200) {
    if (!text || typeof text !== 'string') return '';
    const normalized = text
      .replace(/\u00a0/g, ' ')
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
    if (!normalized) return '';
    return normalized.slice(0, maxLen);
  }

  function countOrderPanelMarkers(text) {
    const markers = ['顾客支付', '配送状态', '下单时间', '收货地', '单号', '拣货指引'];
    let hit = 0;
    for (const marker of markers) {
      if (text.includes(marker)) hit++;
    }
    return hit;
  }

  function findOrderPanelRoot() {
    const candidates = document.querySelectorAll('aside,section,div');
    let best = null;
    let bestScore = -1;
    let seen = 0;

    for (const el of candidates) {
      seen++;
      if (seen > 1200) break;
      if (!el || !(el instanceof HTMLElement)) continue;
      if (el.offsetParent === null) continue;

      const rect = el.getBoundingClientRect();
      if (rect.width < 200 || rect.height < 140) continue;
      if (rect.right < window.innerWidth * 0.55) continue;

      const text = sanitizePanelText(el.innerText || '', 2000);
      if (text.length < 80 || text.length > 3500) continue;

      const markerScore = countOrderPanelMarkers(text);
      if (markerScore < 2) continue;

      const areaScore = Math.min(rect.width * rect.height, 500000) / 100000;
      const score = markerScore * 10 + areaScore;
      if (score > bestScore) {
        bestScore = score;
        best = el;
      }
    }
    return best;
  }

  function stripLabelPrefix(text, label) {
    if (!text || !label) return '';
    let cleaned = text.trim();
    if (cleaned.startsWith(label)) {
      cleaned = cleaned.slice(label.length).trim();
      cleaned = cleaned.replace(/^[:：]/, '').trim();
    }
    return cleaned;
  }

  function isLikelyFieldValue(value, label) {
    if (!value) return false;
    if (value === label) return false;
    if (value.length > 200) return false;
    return true;
  }

  function extractFieldByAlias(root, aliases) {
    const nodes = root.querySelectorAll('div,span,p,li,td,th,strong,b,label');
    for (const node of nodes) {
      const raw = sanitizePanelText(node.textContent || '', 260);
      if (!raw) continue;
      for (const alias of aliases) {
        if (!raw.includes(alias)) continue;

        const inlineValue = stripLabelPrefix(raw, alias);
        if (isLikelyFieldValue(inlineValue, alias)) return inlineValue;

        const nextText = sanitizePanelText(node.nextElementSibling?.textContent || '', 260);
        if (isLikelyFieldValue(nextText, alias)) return nextText;

        const parentText = sanitizePanelText(node.parentElement?.textContent || '', 260);
        const parentValue = stripLabelPrefix(parentText, alias);
        if (isLikelyFieldValue(parentValue, alias)) return parentValue;
      }
    }
    return '';
  }

  function extractOrderItems(root) {
    const items = [];
    const rows = root.querySelectorAll('tr');
    for (const row of rows) {
      if (items.length >= 6) break;
      const cells = Array.from(row.querySelectorAll('td'))
        .map((cell) => sanitizePanelText(cell.textContent || '', 120))
        .filter(Boolean);
      if (cells.length === 0) continue;
      const name = cells[0];
      if (!name || name.includes('商品') || name.includes('子商品')) continue;
      items.push({
        name,
        spec: cells[1] || '',
        quantity: cells[2] || '',
      });
    }
    return items;
  }

  function collectOrderPanelContext(sessionId) {
    if (!sessionId) return null;
    const now = Date.now();
    if (
      orderPanelCache.data
      && orderPanelCache.sessionId === sessionId
      && now - orderPanelCache.ts < 4000
    ) {
      return orderPanelCache.data;
    }

    const root = findOrderPanelRoot();
    if (!root) return null;

    const rawText = sanitizePanelText(root.innerText || '', 1200);
    if (!rawText) return null;

    const fields = {};
    for (const [field, aliases] of Object.entries(ORDER_PANEL_FIELD_ALIASES)) {
      const value = extractFieldByAlias(root, aliases);
      if (value) fields[field] = value;
    }
    const items = extractOrderItems(root);

    if (Object.keys(fields).length === 0 && items.length === 0 && rawText.length < 160) {
      return null;
    }

    const context = {
      source: 'extension_order_panel',
      collected_at: new Date().toISOString(),
      active_session_id: activeSessionId || '',
      likely_session_match: activeSessionId ? activeSessionId === sessionId : null,
      fields,
      items,
      raw_text: rawText,
    };
    orderPanelCache = { sessionId, ts: now, data: context };
    return context;
  }

  /* ═══════════════════ Inject ═══════════════════ */
  function injectScript() {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  }
  injectScript();

  /* ═══════════════════ WS Listener (主要数据源) ═══════════════════ */
  window.addEventListener('__AI_DIANZHANG_WS__', (e) => {
    if (!enabled) return;
    try {
      const data = JSON.parse(e.detail);
      handleWSMessage(data);
    } catch (_) {}
  });

  function handleWSMessage(data) {
    // ── MTDX 美团大象 IM SDK 消息处理 ──────────────────────────
    const mtdxType = data.__type;
    if (mtdxType) {
      handleMTDXMessage(mtdxType, data);
      return;
    }

    // ── 原始 WebSocket 消息处理（后备）──────────────────────────
    const sessionId = extractSessionId(data);

    const customerMsg = extractCustomerMessage(data, sessionId);
    if (customerMsg && !processedMessages.has(customerMsg.id)) {
      if (shouldSkipDuplicateMessage('customer', customerMsg.sessionId, '', customerMsg.text)) return;
      if (isLikelySystemPayloadText(customerMsg.text)) return;
      processedMessages.add(customerMsg.id);
      trimProcessed();
      const name = extractCustomerName(data);
      if (name && customerMsg.sessionId) {
        getSession(customerMsg.sessionId).customerName = name;
        schedulePersistLocalState();
      }
      logChatMessage({ ...customerMsg, role: 'customer' });
      sendToBackend(customerMsg);
    }

    const agentMsg = extractAgentMessage(data, sessionId);
    if (agentMsg && !processedMessages.has(agentMsg.id)) {
      if (shouldSkipDuplicateMessage('agent', agentMsg.sessionId, '', agentMsg.text)) return;
      processedMessages.add(agentMsg.id);
      trimProcessed();
      logChatMessage(agentMsg);
      const session = sessionData[agentMsg.sessionId];
      if (session) {
        const lastSuggestion = session.replies.find(r => r.status === 'pending');
        if (lastSuggestion && lastSuggestion.text !== agentMsg.text) {
          trackReplyComparison(lastSuggestion, agentMsg.text, agentMsg.sessionId);
        }
      }
    }
  }

  /* ═══════════════════ MTDX 大象 IM 消息处理 ═══════════════════ */
  /**
   * 美团大象 IM SDK 消息格式：
   * - sessionId: '1001-138635781398_3997859410'  (channelId-storeId_customerId)
   * - channelId: 1001
   * - type: 19 (文本消息)
   * - uuid: 'biz-kf-...'
   * - content / text / data: 消息内容
   * - customerInfo: { nickname, ... }
   */
  function handleMTDXMessage(type, data) {
    if (type === 'customer_message') {
      if (isLikelyAgentEnvelope(data)) {
        handleMTDXMessage('agent_message', data);
        return;
      }

      // [MTDX] 接收到消息 — 客户发的
      const fallbackSeed = buildSessionSeed(
        data,
        data.customerInfo,
        data.customer,
        data.sender,
        data.user
      );
      const sid = normalizeSessionId(data.sessionId, fallbackSeed);
      const msgId = data.uuid || data.mid || generateLocalId('mtdx');
      const text = extractMTDXContent(data);

      if (isLikelySystemPayloadText(text)) return;
      if (shouldSkipDuplicateMessage('customer', sid, data.uuid || data.mid || '', text)) return;
      if (!text || processedMessages.has(msgId)) return;
      processedMessages.add(msgId);
      trimProcessed();

      // 记录客户名
      const session = getSession(sid);
      if (data.customerInfo?.nickname) {
        session.customerName = data.customerInfo.nickname;
        schedulePersistLocalState();
      }

      const msg = { id: msgId, text, sessionId: sid, customerInfo: data.customerInfo || {} };
      logChatMessage({ ...msg, role: 'customer' });
      sendToBackend(msg);
    }

    if (type === 'agent_message') {
      // 客服发送的消息
      const fallbackSeed = buildSessionSeed(
        data,
        data.customerInfo,
        data.customer,
        data.sender,
        data.user
      );
      const sid = normalizeSessionId(data.sessionId, fallbackSeed);
      const msgId = data.uuid || data.mid || generateLocalId('mtdx-agent');
      const text = extractMTDXContent(data);

      if (shouldSkipDuplicateMessage('agent', sid, data.uuid || data.mid || '', text)) return;
      if (!text || processedMessages.has(msgId)) return;
      processedMessages.add(msgId);
      trimProcessed();

      logChatMessage({ id: msgId, text, sessionId: sid, role: 'agent' });

      // 对比 AI 建议
      const session = sessionData[sid];
      if (session) {
        const lastSuggestion = session.replies.find(r => r.status === 'pending');
        if (lastSuggestion && lastSuggestion.text !== text) {
          trackReplyComparison(lastSuggestion, text, sid);
        }
      }
    }

    if (type === 'session_item') {
      // session-item 包含 customerInfo
      const sid = data.sessionId || '';
      if (sid) {
        const session = getSession(sid);
        activeSessionId = sid;
        orderPanelCache = { sessionId: '', ts: 0, data: null };
        if (data.customerInfo) {
          const name = data.customerInfo.nickname || data.customerInfo.name || '';
          if (name) session.customerName = name;
        }
        schedulePersistLocalState();
        renderReplies();
      }
    }

    if (type === 'passthrough') {
      // 大象透传消息 — 通知类，无需触发 AI
    }

    if (type === 'history_messages') {
      // 会话历史消息批量采集
      // data.sessionId: 会话ID, data.messages: 历史消息数组
      const sid = data.sessionId || '';
      const msgs = data.messages;
      if (!sid || !Array.isArray(msgs) || msgs.length === 0) return;

      console.log(`[AI店长] 📚 采集历史消息 ${sid}: ${msgs.length} 条`);

      // 逐条上报（后端有 content_hash 去重，重复不会入库）
      let queued = 0;
      for (const msg of msgs) {
        try {
          const text = extractMTDXContent(msg);
          if (!text) continue;

          // role 推断：MTDX 消息 type 奇数=客服/系统，偶数=客户（不准确）
          // 更可靠：看 sender 或 direction 字段
          const isAgent = msg.direction === 'out'
            || msg.sender === 'agent'
            || msg.senderType === 2
            || msg.fromMe === true
            || (msg.uuid && msg.uuid.includes('kf-sys'));
          const role = isAgent ? 'agent' : 'customer';

          const msgId = msg.uuid || msg.mid || msg.id || `hist-${sid}-${queued}`;
          if (processedMessages.has(msgId)) continue;
          processedMessages.add(msgId);

          // 延迟上报，避免页面加载时大量并发请求
          const delay = queued * 80; // 每条间隔 80ms
          queued++;
          setTimeout(() => {
            logChatMessage({
              id: msgId,
              text,
              sessionId: sid,
              role,
              messageId: msgId,
            });
          }, delay);
        } catch (_) {}
      }
      if (queued > 0) {
        console.log(`[AI店长] 📤 排队上报 ${queued} 条历史消息（间隔80ms）`);
      }
    }
  }

  /**
   * 从 MTDX 消息对象中提取文本内容
   * MTDX 消息 content 可能是字符串或 JSON 字符串
   */
  function extractMTDXContent(msg) {
    function pullTextFromObject(obj) {
      if (!obj || typeof obj !== 'object') return '';
      const candidates = [];
      for (const key of ['text', 'content', 'msg', 'plain', 'richText', 'summary']) {
        if (typeof obj[key] === 'string' && obj[key].trim()) {
          candidates.push(obj[key].trim());
        }
      }
      const cardParts = [];
      for (const key of ['title', 'subTitle', 'name', 'goodsName', 'productName', 'description', 'desc', 'skuName']) {
        if (typeof obj[key] === 'string' && obj[key].trim()) {
          cardParts.push(obj[key].trim());
        }
      }
      for (const key of ['price', 'currentPrice', 'salePrice']) {
        if (typeof obj[key] === 'string' && obj[key].trim()) {
          cardParts.push(`价格${obj[key].trim()}`);
        } else if (typeof obj[key] === 'number') {
          cardParts.push(`价格${obj[key]}`);
        }
      }
      for (const key of ['imageUrl', 'imgUrl', 'picUrl', 'thumbUrl', 'url']) {
        if (typeof obj[key] === 'string' && /^https?:\/\//i.test(obj[key].trim())) {
          candidates.push(`[图片地址] ${obj[key].trim().slice(0, 180)}`);
          break;
        }
      }
      // 商品卡片信息优先于泛化文本，避免链接消息被“你好/欢迎语”覆盖。
      if (cardParts.length > 0) return `[商品卡片] ${cardParts.slice(0, 4).join('，')}`;
      if (candidates.length > 0) return candidates[0];

      for (const nestedKey of ['item', 'goods', 'product', 'card', 'payload', 'ext']) {
        if (obj[nestedKey] && typeof obj[nestedKey] === 'object') {
          const nested = pullTextFromObject(obj[nestedKey]);
          if (nested) return nested;
        }
      }
      return '';
    }

    // ── 1. 直接文本字段 ──
    for (const key of ['content', 'text', 'msg', 'message', 'plain']) {
      if (typeof msg[key] === 'string' && msg[key].trim()) {
        const val = msg[key].trim();
        // 检查是否是 JSON 包裹
        try {
          const parsed = JSON.parse(val);
          if (typeof parsed === 'string') return parsed;
          if (parsed.text) return parsed.text;
          if (parsed.content) return parsed.content;
          if (parsed.msg) return parsed.msg;
          const parsedText = pullTextFromObject(parsed);
          if (parsedText) return parsedText;
        } catch (_) {}
        return val;
      }
    }

    // ── 2. body 字段（MTDX 消息的主要内容载体）──
    if (msg.body) {
      let body = msg.body;
      // body 可能被 stringify 过
      if (typeof body === 'string') {
        try { body = JSON.parse(body); } catch (_) {}
      }
      if (typeof body === 'string' && body.trim()) return body.trim();
      if (typeof body === 'object') {
        const bodyText = pullTextFromObject(body);
        if (bodyText) return bodyText;
        // 系统消息（状态变更等）跳过
        if (body.eType || body.type === 'system') return '';
      }
    }

    // ── 3. data 字段 ──
    if (typeof msg.data === 'string' && msg.data.trim()) {
      try {
        const parsed = JSON.parse(msg.data);
        return parsed.content || parsed.text || parsed.msg || parsed.summary || pullTextFromObject(parsed) || '';
      } catch (_) {}
      return msg.data.trim();
    }

    // ── 4. extension 字段 ──
    if (typeof msg.extension === 'string') {
      try {
        const ext = JSON.parse(msg.extension);
        if (ext.text || ext.content) return ext.text || ext.content;
        const extText = pullTextFromObject(ext);
        if (extText) return extText;
      } catch (_) {}
    }

    // ── 5. summary ──
    if (typeof msg.summary === 'string' && msg.summary.trim()) return msg.summary.trim();

    // ── 6. 已知非文本消息类型 ──
    // type 12 = 卡片/系统，尽量抽取摘要；type 3/4 = 图片
    if (msg.type === 12) {
      const cardText = pullTextFromObject(msg);
      if (cardText) return cardText;
      return '[卡片消息]';
    }
    if (msg.type === 3 || msg.type === 4) {
      const imageHint = pullTextFromObject(msg);
      return imageHint ? `[图片消息] ${imageHint}` : '[图片消息]';
    }

    return '';
  }

  function trimProcessed() {
    if (processedMessages.size > 1000) {
      const iter = processedMessages.values();
      for (let i = 0; i < 200; i++) {
        processedMessages.delete(iter.next().value);
      }
    }
  }

  function trimRecentFingerprints(now = Date.now()) {
    for (const [key, ts] of recentMessageFingerprints.entries()) {
      if (!ts || (now - ts) > MESSAGE_FP_TTL_MS) {
        recentMessageFingerprints.delete(key);
      }
    }
    if (recentMessageFingerprints.size <= 1500) return;
    const overflow = recentMessageFingerprints.size - 1500;
    const iter = recentMessageFingerprints.keys();
    for (let i = 0; i < overflow; i++) {
      const next = iter.next();
      if (next.done) break;
      recentMessageFingerprints.delete(next.value);
    }
  }

  function buildMessageFingerprint(kind, sessionId, msgId, text) {
    const sid = (sessionId || '').trim();
    const mid = (msgId || '').trim();
    if (sid && mid) return `${kind}:${sid}:${mid}`;
    const normalized = (text || '')
      .trim()
      .replace(/\s+/g, ' ')
      .toLowerCase()
      .slice(0, 220);
    if (!sid || !normalized) return '';
    return `${kind}:${sid}:${normalized}`;
  }

  function shouldSkipDuplicateMessage(kind, sessionId, msgId, text) {
    const key = buildMessageFingerprint(kind, sessionId, msgId, text);
    if (!key) return false;
    trimRecentFingerprints();
    if (recentMessageFingerprints.has(key)) return true;
    recentMessageFingerprints.set(key, Date.now());
    return false;
  }

  function extractCustomerMessage(data, fallbackSessionId) {
    // Pattern 1: top-level incoming
    if (data.type === 'message' && data.direction === 'in') {
      const customerInfo = data.customer || data.sender || {};
      const text = normalizeText(data.content || data.text || data.body);
      if (!text) return null;
      return {
        id: data.msgId || data.id || generateLocalId('ws-cust'),
        text,
        sessionId: normalizeSessionId(
          extractSessionId(data) || fallbackSessionId || '',
          buildSessionSeed(customerInfo, data)
        ),
        customerInfo,
      };
    }
    // Pattern 2: nested
    const inner = data.data || data.body || {};
    if (inner.msgType !== undefined && inner.fromCustomer !== false && inner.role !== 'merchant' && inner.role !== 'agent') {
      const text = normalizeText(inner.content || inner.text || inner.body || '');
      if (text) {
        const customerInfo = inner.customer || inner.sender || {};
        return {
          id: inner.msgId || inner.id || generateLocalId('ws-cust'),
          text,
          sessionId: normalizeSessionId(
            extractSessionId(data) || fallbackSessionId || '',
            buildSessionSeed(customerInfo, inner, data)
          ),
          customerInfo,
        };
      }
    }
    // Pattern 3: chat command
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      const text = normalizeText(payload.content || payload.text || payload.body || '');
      if (text && payload.role !== 'merchant' && payload.role !== 'agent') {
        const customerInfo = payload.customer || payload.sender || {};
        return {
          id: payload.msgId || payload.id || generateLocalId('ws-cust'),
          text,
          sessionId: normalizeSessionId(
            extractSessionId(data) || fallbackSessionId || '',
            buildSessionSeed(customerInfo, payload, data)
          ),
          customerInfo,
        };
      }
    }
    return null;
  }

  function extractAgentMessage(data, fallbackSessionId) {
    // Pattern 1: outgoing
    if (data.type === 'message' && data.direction === 'out') {
      const text = normalizeText(data.content || data.text || data.body);
      if (!text) return null;
      return {
        id: data.msgId || data.id || generateLocalId('ws-agent'),
        text,
        sessionId: normalizeSessionId(
          extractSessionId(data) || fallbackSessionId || '',
          buildSessionSeed(data.customer, data.sender, data.user, data)
        ),
        role: 'agent',
      };
    }
    // Pattern 2: nested outgoing
    const inner = data.data || data.body || {};
    if (inner.fromCustomer === false || inner.role === 'merchant' || inner.role === 'agent') {
      const text = normalizeText(inner.content || inner.text || inner.body || '');
      if (text) {
        return {
          id: inner.msgId || inner.id || generateLocalId('ws-agent'),
          text,
          sessionId: normalizeSessionId(
            extractSessionId(data) || fallbackSessionId || '',
            buildSessionSeed(inner.customer, inner.sender, inner.user, inner, data)
          ),
          role: 'agent',
        };
      }
    }
    // Pattern 3
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      const text = normalizeText(payload.content || payload.text || payload.body || '');
      if (text && (payload.role === 'merchant' || payload.role === 'agent')) {
        return {
          id: payload.msgId || payload.id || generateLocalId('ws-agent'),
          text,
          sessionId: normalizeSessionId(
            extractSessionId(data) || fallbackSessionId || '',
            buildSessionSeed(payload.customer, payload.sender, payload.user, payload, data)
          ),
          role: 'agent',
        };
      }
    }
    return null;
  }

  /* ═══════════════════ DOM Observer (补充采集) ═══════════════════ */
  // DOM 只作为 WS 的补充（某些消息可能不经过 WS）
  function startDOMObserver() {
    const CONTAINER_SELECTORS = [
      '.chat-message-list', '.message-list', '[class*="messageList"]',
      '[class*="chat-content"]', '.im-message-list',
    ];

    function findContainer() {
      for (const sel of CONTAINER_SELECTORS) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    }

    function getSafeDomSessionId() {
      const active = Object.keys(sessionData);
      if (active.length === 1) return active[0];
      return '';
    }

    function observe() {
      const container = findContainer();
      if (!container) { setTimeout(observe, 3000); return; }

      new MutationObserver((mutations) => {
        if (!enabled) return;
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;

            // 客户消息
            const customerBubble = node.matches?.('[class*="customer"], [class*="receive"], [class*="left"]')
              ? node : node.querySelector?.('[class*="customer"], [class*="receive"], [class*="left"]');
            if (customerBubble) {
              const textEl = customerBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text) {
                // DOM 无法可靠获取 sessionId，用 content hash 去重（后端会处理）
                const dedupKey = `dom-cust-${hashCode(text)}`;
                if (!processedMessages.has(dedupKey)) {
                  processedMessages.add(dedupKey);
                  // 不触发 AI（WS 已触发），只做采集补充
                  logChatMessage({
                    id: `dom-${Date.now()}-${hashCode(text)}`,
                    text,
                    sessionId: getSafeDomSessionId(),
                    role: 'customer',
                  });
                }
              }
            }

            // 客服消息
            const agentBubble = node.matches?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]')
              ? node : node.querySelector?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]');
            if (agentBubble) {
              const textEl = agentBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text) {
                const dedupKey = `dom-agent-${hashCode(text)}`;
                if (!processedMessages.has(dedupKey)) {
                  processedMessages.add(dedupKey);
                  logChatMessage({
                    id: `dom-agent-${Date.now()}-${hashCode(text)}`,
                    text,
                    sessionId: getSafeDomSessionId(),
                    role: 'agent',
                  });
                }
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observe();
  }

  startDOMObserver();

  function trackReplyComparison(suggestion, actual, sessionId) {
    // 产品要求：仅“采纳”和“👍/👎”反馈到后端。
    // 人工回复对比仅用于本地行为标记，不自动上报。
    void suggestion;
    void actual;
    void sessionId;
  }

  /* ═══════════════════ Chat Log Collection ═══════════════════ */
  function logChatMessage(msg) {
    const text = normalizeText(msg.text);
    if (!text) return;
    const sessionId = (msg.sessionId || '').trim();
    if (!sessionId) return;
    chrome.runtime.sendMessage({
      type: 'LOG_CHAT',
      payload: {
        session_id: sessionId,
        message_id: msg.id || '',
        role: msg.role || 'unknown',
        content: text,
        timestamp: new Date().toISOString(),
      },
    });
  }

  /* ═══════════════════ Backend Communication ═══════════════════ */
  function sendToBackend(msg) {
    const text = normalizeText(msg.text);
    if (!text) return;
    const sessionId = (msg.sessionId || '').trim();
    if (!sessionId) {
      updatePanel('error', '未识别会话ID，已跳过该消息');
      return;
    }
    const session = getSession(sessionId);
    const customerLabel = session.customerName || sessionId.slice(0, 10) || '客户';
    if (isNonActionablePlaceholderText(text)) {
      updatePanel('connected', `⏭️ [${customerLabel}] 占位消息，已跳过AI生成`);
      return;
    }
    updatePanel('thinking', `🤔 [${customerLabel}] "${text.slice(0, 20)}..."`);
    const customerInfo = (msg.customerInfo && typeof msg.customerInfo === 'object')
      ? { ...msg.customerInfo }
      : {};
    if (!customerInfo.nickname && session.customerName) {
      customerInfo.nickname = session.customerName;
    }
    const orderContext = collectOrderPanelContext(sessionId);
    const payload = {
      message: text,
      session_id: sessionId,
      message_id: msg.id || '',
      customer_info: customerInfo,
    };
    if (orderContext) {
      payload.order_context = orderContext;
    }

    chrome.runtime.sendMessage(
      {
        type: 'CUSTOMER_MESSAGE',
        payload,
      },
      (response) => {
        if (chrome.runtime.lastError) {
          updatePanel('error', '后台连接中断');
          return;
        }
        if (response?.success && response.reply) {
          const contextTrace = (response.context_trace && typeof response.context_trace === 'object')
            ? response.context_trace
            : {};
          const needsHuman = Boolean(response.needs_human);
          if (contextTrace.direct_logistics_from_extension || contextTrace.has_extension_order_fields) {
            updatePanel('connected', `🧭 [${customerLabel}] 已使用工作台订单信息`);
          } else if (needsHuman) {
            updatePanel('connected', `⚠️ [${customerLabel}] 建议转人工处理`);
          }
          handleAIReply(
            response.reply,
            sessionId,
            msg.id,
            response.ai_reply_id || '',
            contextTrace,
            needsHuman
          );
        } else {
          updatePanel('error', response?.error || '未知错误');
        }
      }
    );
  }

  function sendFeedback(data) {
    chrome.runtime.sendMessage({ type: 'SEND_FEEDBACK', payload: data }, (response) => {
      if (chrome.runtime.lastError) {
        console.error('[AI店长] 反馈发送失败:', chrome.runtime.lastError.message);
        return;
      }
      if (!response?.success) return;
      updateFeedbackStats(
        response.stored?.action || data.action,
        response.stored?.rating || data.rating || data.feedback
      );
    });
  }

  function updateFeedbackStats(action, rating) {
    chrome.storage.sync.get(['feedbackStats'], (result) => {
      const stats = result.feedbackStats || { adopted: 0, edited: 0, ignored: 0, good: 0, bad: 0, total: 0 };
      if (action && ['adopted', 'edited', 'ignored'].includes(action)) {
        stats[action] = (stats[action] || 0) + 1;
      }
      if (rating === 'good') stats.good = (stats.good || 0) + 1;
      if (rating === 'bad') stats.bad = (stats.bad || 0) + 1;
      stats.total = (stats.total || 0) + 1;
      chrome.storage.sync.set({ feedbackStats: stats });
    });
  }

  /* ═══════════════════ AI Reply Handler ═══════════════════ */
  function handleAIReply(
    reply,
    sessionId,
    messageId,
    aiReplyId = '',
    contextTrace = {},
    needsHuman = false
  ) {
    const session = getSession(sessionId);
    const customerLabel = session.customerName || sessionId?.slice(0, 10) || '客户';
    if (messageId) {
      const duplicated = session.replies.find((item) => item.messageId === messageId);
      if (duplicated) {
        updatePanel('connected', `🔁 [${customerLabel}] 已复用同消息建议`);
        return;
      }
    }

    const replyObj = {
      id: `reply-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      text: reply,
      time: new Date().toLocaleTimeString(),
      sessionId: sessionId || '',
      messageId: messageId || '',
      aiReplyId: aiReplyId || '',
      contextTrace: contextTrace && typeof contextTrace === 'object' ? contextTrace : {},
      needsHuman: Boolean(needsHuman),
      customerName: customerLabel,
      createdAt: Date.now(),
      status: 'pending',
      editedText: '',
      feedbackRating: '',
    };

    addReplyToSession(sessionId, replyObj);

    if (mode === 'suggest') {
      updatePanel(
        'connected',
        needsHuman ? `⚠️ [${customerLabel}] 建议转人工` : `✨ [${customerLabel}] 新建议`
      );
      renderReplies();
      flashPanel();
    } else if (mode === 'auto-fill') {
      updatePanel('connected', `✏️ [${customerLabel}] 已填充`);
      renderReplies();
      fillReplyInput(reply);
    } else if (mode === 'auto-send') {
      updatePanel('connected', `🚀 [${customerLabel}] 已发送`);
      replyObj.status = 'adopted';
      renderReplies();
      fillReplyInput(reply);
      setTimeout(() => clickSendButton(), 300);
      sendFeedback({
        session_id: sessionId,
        message_id: messageId,
        ai_reply_id: aiReplyId || '',
        rating: 'good',
        action: 'adopted',
        original_reply: reply,
        edited_reply: '',
        actual_reply: reply,
      });
    }
  }

  /* ═══════════════════ Input / Send ═══════════════════ */
  function fillReplyInput(text) {
    const SELECTORS = [
      'textarea[class*="input"]', 'div[contenteditable="true"]',
      'textarea[class*="reply"]', '.chat-input textarea', 'textarea',
    ];
    for (const sel of SELECTORS) {
      const el = document.querySelector(sel);
      if (!el) continue;
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        if (setter) setter.call(el, text);
        else el.value = text;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        el.focus();
        el.innerHTML = '';
        document.execCommand('insertText', false, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      el.focus();
      return true;
    }
    return false;
  }

  function clickSendButton() {
    const SELECTORS = [
      'button[class*="send"]', '[class*="send-btn"]', '[class*="sendBtn"]',
      '.chat-input button', 'button[type="submit"]',
    ];
    for (const sel of SELECTORS) {
      try {
        const btn = document.querySelector(sel);
        if (btn) { btn.click(); return true; }
      } catch (_) {}
    }
    const textarea = document.querySelector('textarea, [contenteditable="true"]');
    if (textarea) {
      textarea.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true,
      }));
      return true;
    }
    return false;
  }

  /* ═══════════════════ Panel UI ═══════════════════ */
  let panel = null;
  let isMinimized = false;

  function createPanel() {
    const existing = document.getElementById('ai-dianzhang-panel');
    if (existing) {
      panel = existing;
      return;
    }
    panel = document.createElement('div');
    panel.id = 'ai-dianzhang-panel';

    panel.innerHTML = `
      <div class="aidz-header">
        <span class="aidz-title">🤖 AI客服助手</span>
        <span class="aidz-badge" id="aidz-mode-badge">建议</span>
        <span class="aidz-session-count" id="aidz-session-count" title="活跃会话数"></span>
        <span class="aidz-status" id="aidz-status">●</span>
        <button class="aidz-minimize" id="aidz-minimize" title="最小化/展开">─</button>
      </div>
      <div class="aidz-body" id="aidz-body">
        <div class="aidz-controls">
          <label class="aidz-toggle">
            <input type="checkbox" id="aidz-enabled" checked>
            <span>启用</span>
          </label>
          <select id="aidz-mode">
            <option value="suggest">💡 建议模式</option>
            <option value="auto-fill">✏️ 半自动模式</option>
            <option value="auto-send">🚀 全自动模式</option>
          </select>
        </div>
        <div class="aidz-view-controls" id="aidz-view-controls">
          <button id="aidz-view-active" class="aidz-view-btn active" data-view="active">当前会话</button>
          <button id="aidz-view-all" class="aidz-view-btn" data-view="all">全部会话</button>
        </div>
        <div class="aidz-session-tabs" id="aidz-session-tabs"></div>
        <div class="aidz-info" id="aidz-info">就绪 — 等待客户消息</div>
        <div class="aidz-main">
          <div class="aidz-session-rail" id="aidz-session-rail"></div>
          <div class="aidz-replies" id="aidz-replies">
            <div class="aidz-empty">暂无 AI 建议</div>
          </div>
        </div>
      </div>
      <div class="aidz-resize-handle" id="aidz-resize-handle" title="拖拽调整大小"></div>
    `;
    document.body.appendChild(panel);

    /* — Drag — */
    let isDragging = false, startX, startY, origX, origY;
    let isResizing = false;
    let resizeStartX = 0;
    let resizeStartY = 0;
    let resizeStartW = 0;
    let resizeStartBodyH = 0;
    const header = panel.querySelector('.aidz-header');
    const body = document.getElementById('aidz-body');
    const resizeHandle = document.getElementById('aidz-resize-handle');

    function clamp(v, min, max) {
      return Math.max(min, Math.min(max, v));
    }

    function parsePx(value, fallback) {
      if (typeof value !== 'string') return fallback;
      const n = Number.parseFloat(value.replace('px', '').trim());
      return Number.isFinite(n) ? n : fallback;
    }

    function persistPanelSize() {
      const width = parsePx(panel.style.width, panel.getBoundingClientRect().width);
      const bodyMaxH = parsePx(body.style.maxHeight, parsePx(getComputedStyle(body).maxHeight, 560));
      chrome.storage.sync.set({
        panelWidth: Math.round(width),
        panelBodyMaxHeight: Math.round(bodyMaxH),
      });
    }

    header.addEventListener('mousedown', (e) => {
      if (e.target.closest('button') || e.target.closest('select')) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      origX = rect.left;
      origY = rect.top;
      e.preventDefault();
    });
    resizeHandle.addEventListener('mousedown', (e) => {
      isResizing = true;
      resizeStartX = e.clientX;
      resizeStartY = e.clientY;
      const rect = panel.getBoundingClientRect();
      resizeStartW = rect.width;
      resizeStartBodyH = parsePx(body.style.maxHeight, parsePx(getComputedStyle(body).maxHeight, 560));
      panel.classList.add('aidz-resizing');
      e.preventDefault();
      e.stopPropagation();
    });
    document.addEventListener('mousemove', (e) => {
      if (isResizing) {
        const maxW = Math.max(360, window.innerWidth - 12);
        const minW = 320;
        const nextW = clamp(resizeStartW + (e.clientX - resizeStartX), minW, maxW);
        panel.style.width = `${Math.round(nextW)}px`;

        const maxBodyH = Math.max(260, window.innerHeight - 160);
        const minBodyH = 220;
        const nextBodyH = clamp(resizeStartBodyH + (e.clientY - resizeStartY), minBodyH, maxBodyH);
        body.style.maxHeight = `${Math.round(nextBodyH)}px`;
        return;
      }
      if (!isDragging) return;
      panel.style.right = 'auto';
      panel.style.left = (origX + e.clientX - startX) + 'px';
      panel.style.top = (origY + e.clientY - startY) + 'px';
    });
    document.addEventListener('mouseup', () => {
      if (isResizing) {
        isResizing = false;
        panel.classList.remove('aidz-resizing');
        persistPanelSize();
      }
      isDragging = false;
    });

    /* — Controls — */
    document.getElementById('aidz-enabled').addEventListener('change', (e) => {
      enabled = e.target.checked;
      chrome.storage.sync.set({ enabled });
      updatePanel(enabled ? 'connected' : 'disabled', enabled ? '已启用' : '已禁用');
    });

    document.getElementById('aidz-mode').addEventListener('change', (e) => {
      mode = e.target.value;
      chrome.storage.sync.set({ mode });
      updateModeBadge();
    });

    document.getElementById('aidz-view-active').addEventListener('click', () => setPanelViewMode('active'));
    document.getElementById('aidz-view-all').addEventListener('click', () => setPanelViewMode('all'));
    panel.addEventListener('click', handleReplyAction);

    document.getElementById('aidz-minimize').addEventListener('click', () => {
      isMinimized = !isMinimized;
      const body = document.getElementById('aidz-body');
      const btn = document.getElementById('aidz-minimize');
      if (isMinimized) {
        body.style.display = 'none';
        btn.textContent = '□';
        panel.classList.add('aidz-minimized');
      } else {
        body.style.display = 'block';
        btn.textContent = '─';
        panel.classList.remove('aidz-minimized');
      }
    });

    chrome.storage.sync.get(['enabled', 'mode', 'panelWidth', 'panelBodyMaxHeight'], (s) => {
      if (s.enabled === false) {
        enabled = false;
        document.getElementById('aidz-enabled').checked = false;
        updatePanel('disabled', '已禁用');
      }
      if (s.mode && ['suggest', 'auto-fill', 'auto-send'].includes(s.mode)) {
        mode = s.mode;
        document.getElementById('aidz-mode').value = mode;
      }
      if (typeof s.panelWidth === 'number' && Number.isFinite(s.panelWidth)) {
        const maxW = Math.max(360, window.innerWidth - 12);
        const minW = 320;
        panel.style.width = `${Math.round(clamp(s.panelWidth, minW, maxW))}px`;
      }
      if (typeof s.panelBodyMaxHeight === 'number' && Number.isFinite(s.panelBodyMaxHeight)) {
        const maxBodyH = Math.max(260, window.innerHeight - 160);
        const minBodyH = 220;
        body.style.maxHeight = `${Math.round(clamp(s.panelBodyMaxHeight, minBodyH, maxBodyH))}px`;
      }
      setPanelViewMode(panelViewMode);
      updateModeBadge();
    });
  }

  function setPanelViewMode(view) {
    panelViewMode = view === 'active' ? 'active' : 'all';
    const activeBtn = document.getElementById('aidz-view-active');
    const allBtn = document.getElementById('aidz-view-all');
    if (activeBtn) activeBtn.classList.toggle('active', panelViewMode === 'active');
    if (allBtn) allBtn.classList.toggle('active', panelViewMode === 'all');
    schedulePersistLocalState();
    renderReplies();
  }

  function getSessionDisplayLabel(sessionId) {
    const data = sessionData[sessionId];
    const name = (data && data.customerName) || '';
    if (name) return name;
    return sessionId ? sessionId.slice(0, 12) : '未知会话';
  }

  function composePanelInfo() {
    const totalPending = getPendingTotal();
    if (totalPending <= 0) return '就绪 — 暂无待处理建议';
    const sid = resolveDisplaySessionId();
    if (!sid || panelViewMode === 'all') {
      return `当前有 ${totalPending} 条建议，按会话分组展示`;
    }
    const currentPending = getSessionPending(sid);
    const otherPending = Math.max(0, totalPending - currentPending);
    const label = getSessionDisplayLabel(sid);
    if (otherPending > 0) {
      return `[${label}] ${currentPending}条待处理；其他会话 ${otherPending} 条`;
    }
    return `[${label}] ${currentPending}条待处理`;
  }

  function decodeSessionKey(sessionKey) {
    if (!sessionKey || typeof sessionKey !== 'string') return '';
    try {
      return decodeURIComponent(sessionKey);
    } catch (_) {
      return sessionKey;
    }
  }

  function getRenderableSessions() {
    return Object.entries(sessionData)
      .filter(([sid, data]) => {
        if (!data) return false;
        const hasReplies = Array.isArray(data.replies) && data.replies.length > 0;
        const hasPending = getSessionPending(sid) > 0;
        const isActive = sid === activeSessionId;
        return hasReplies || hasPending || isActive;
      })
      .sort((a, b) => {
        const ap = getSessionPending(a[0]);
        const bp = getSessionPending(b[0]);
        if (bp !== ap) return bp - ap;
        return (b[1].lastActivity || 0) - (a[1].lastActivity || 0);
      });
  }

  function getRailSessions() {
    return Object.entries(sessionData)
      .filter(([sid, data]) => {
        if (!data) return false;
        const hasReplies = Array.isArray(data.replies) && data.replies.length > 0;
        const hasPending = getSessionPending(sid) > 0;
        const isActive = sid === activeSessionId;
        const isRecent = (Date.now() - (data.lastActivity || 0)) < 60 * 60 * 1000;
        return hasReplies || hasPending || isActive || isRecent;
      })
      .sort((a, b) => {
        const ap = getSessionPending(a[0]);
        const bp = getSessionPending(b[0]);
        if (bp !== ap) return bp - ap;
        return (b[1].lastActivity || 0) - (a[1].lastActivity || 0);
      });
  }

  function renderSessionTabs() {
    const tabsEl = document.getElementById('aidz-session-tabs');
    if (!tabsEl) return;

    const entries = getRailSessions().slice(0, 8);

    if (entries.length === 0) {
      tabsEl.innerHTML = '';
      return;
    }

    const allBtnClass = panelViewMode === 'all' ? ' active' : '';
    const allCount = getPendingTotal();

    const parts = [
      `
        <button class="aidz-session-chip${allBtnClass}" data-action="show-all" title="全部会话">
          <span class="aidz-session-chip-label">全部</span>
          ${allCount > 0 ? `<span class="aidz-session-chip-count">${allCount}</span>` : ''}
        </button>
      `,
    ];

    entries.forEach(([sid]) => {
      const label = escapeHtml(getSessionDisplayLabel(sid));
      const pending = getSessionPending(sid);
      const activeClass = panelViewMode === 'active' && sid === activeSessionId ? ' active' : '';
      parts.push(`
        <button
          class="aidz-session-chip${activeClass}"
          data-action="switch-session"
          data-session-key="${encodeURIComponent(sid)}"
          title="${escapeHtml(sid)}"
        >
          <span class="aidz-session-chip-label">${label}</span>
          ${pending > 0 ? `<span class="aidz-session-chip-count">${pending}</span>` : ''}
        </button>
      `);
    });

    tabsEl.innerHTML = parts.join('');
  }

  function renderSessionRail(entries) {
    const railEl = document.getElementById('aidz-session-rail');
    if (!railEl) return;

    if (!entries || entries.length === 0) {
      railEl.innerHTML = '<div class="aidz-session-rail-empty">暂无会话</div>';
      return;
    }

    const totalPending = getPendingTotal();
    const allClass = panelViewMode === 'all' ? ' active' : '';
    const items = [
      `
        <button class="aidz-session-rail-item${allClass}" data-action="show-all">
          <span class="aidz-session-rail-name">全部会话</span>
          <span class="aidz-session-rail-count">${totalPending}</span>
        </button>
      `,
    ];

    entries.slice(0, 20).forEach(([sid]) => {
      const pending = getSessionPending(sid);
      const label = escapeHtml(getSessionDisplayLabel(sid));
      const activeClass = panelViewMode === 'active' && sid === activeSessionId ? ' active' : '';
      items.push(`
        <button
          class="aidz-session-rail-item${activeClass}"
          data-action="switch-session"
          data-session-key="${encodeURIComponent(sid)}"
          title="${escapeHtml(sid)}"
        >
          <span class="aidz-session-rail-name">${label}</span>
          <span class="aidz-session-rail-count">${pending}</span>
        </button>
      `);
    });

    railEl.innerHTML = `<div class="aidz-session-rail-list">${items.join('')}</div>`;
  }

  function updateModeBadge() {
    const badge = document.getElementById('aidz-mode-badge');
    if (!badge) return;
    badge.textContent = { suggest: '建议', 'auto-fill': '半自动', 'auto-send': '全自动' }[mode] || mode;
  }

  function updatePanel(status, message) {
    if (!panel) return;
    const statusEl = document.getElementById('aidz-status');
    const infoEl = document.getElementById('aidz-info');
    const countEl = document.getElementById('aidz-session-count');
    const colors = { connected: '#4caf50', thinking: '#ff9800', error: '#f44336', disabled: '#999' };
    if (statusEl) statusEl.style.color = colors[status] || '#4caf50';
    if (message && infoEl) infoEl.textContent = message;
    // 更新活跃会话数
    if (countEl) {
      const activeCount = Object.keys(sessionData).length;
      const pendingTotal = getPendingTotal();
      countEl.textContent = pendingTotal > 0 ? `📋 ${activeCount}会话 · ${pendingTotal}待处理` : `📋 ${activeCount}会话`;
    }
  }

  function flashPanel() {
    if (!panel) return;
    panel.style.transition = 'box-shadow 0.3s';
    panel.style.boxShadow = '0 0 20px rgba(255, 149, 0, 0.6)';
    setTimeout(() => { panel.style.boxShadow = ''; }, 1500);
  }

  /* ═══════════════════ Render Reply Cards (跨 session) ═══════════════════ */
  function renderReplyCard(r) {
    const statusClass = r.status === 'adopted' ? 'aidz-adopted'
      : r.status === 'ignored' ? 'aidz-ignored' : '';
    const isActioned = r.status !== 'pending';
    const statusColors = { adopted: '#4caf50', edited: '#1976d2', ignored: '#999' };
    const label = r.customerName || r.sessionId?.slice(0, 8) || '未知';
    const trace = (r.contextTrace && typeof r.contextTrace === 'object') ? r.contextTrace : {};
    const hasOrderContext = Boolean(trace.has_extension_order_fields || trace.direct_logistics_from_extension);
    const traceBadge = hasOrderContext
      ? '<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#fff3cd;color:#8a6d3b;font-size:12px;margin-bottom:6px;">🧭 已使用订单面板</span>'
      : '';
    const humanBadge = r.needsHuman
      ? '<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#fdecea;color:#b42318;font-size:12px;margin-bottom:6px;">⚠️ 建议转人工</span>'
      : '';
    const feedbackText = r.feedbackRating === 'good'
      ? '👍 已好评'
      : r.feedbackRating === 'bad'
        ? '👎 已差评'
        : '';
    const actionButtons = isActioned
      ? `<span class="aidz-action-btn aidz-btn-disabled" style="cursor: default;">${statusLabel(r.status)}</span>
         <span class="aidz-action-spacer"></span>
         ${feedbackText ? `<span class="aidz-action-btn aidz-btn-disabled" style="cursor: default;">${feedbackText}</span>` : ''}`
      : `<button class="aidz-action-btn aidz-btn-adopt"
                  data-action="adopt" data-id="${r.id}">✅ 采纳</button>
         <button class="aidz-action-btn aidz-btn-edit"
                  data-action="edit" data-id="${r.id}">✏️ 编辑</button>
         <button class="aidz-action-btn aidz-btn-ignore"
                  data-action="ignore" data-id="${r.id}">❌ 忽略</button>
         <span class="aidz-action-spacer"></span>
         <button class="aidz-action-btn aidz-btn-feedback aidz-fb-good"
                  data-action="feedback-good" data-id="${r.id}" title="好评">👍</button>
         <button class="aidz-action-btn aidz-btn-feedback aidz-fb-bad"
                  data-action="feedback-bad" data-id="${r.id}" title="差评">👎</button>`;

    return `
      <div class="aidz-reply-card ${statusClass}" data-reply-id="${r.id}" data-session-id="${r.sessionId}">
        <div class="aidz-reply-session-tag" title="${escapeHtml(r.sessionId || '')}">👤 ${escapeHtml(label)}</div>
        ${traceBadge}
        ${humanBadge}
        <div class="aidz-reply-content">${escapeHtml(r.editedText || r.text)}</div>
        <div class="aidz-reply-meta">
          <span>⏱ ${r.time}</span>
          ${r.status !== 'pending' ? `<span style="color: ${statusColors[r.status] || '#999'}">● ${statusLabel(r.status)}</span>` : ''}
        </div>
        <div class="aidz-reply-actions">
          ${actionButtons}
        </div>
        <div class="aidz-edit-area" id="edit-area-${r.id}">
          <textarea class="aidz-edit-textarea" id="edit-text-${r.id}">${escapeHtml(r.text)}</textarea>
          <div class="aidz-edit-actions">
            <button class="aidz-edit-btn cancel" data-action="edit-cancel" data-id="${r.id}">取消</button>
            <button class="aidz-edit-btn confirm" data-action="edit-confirm" data-id="${r.id}">使用修改版</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;
    const entries = getRenderableSessions();
    const railEntries = getRailSessions();
    renderSessionTabs();
    renderSessionRail(railEntries);

    if (entries.length === 0) {
      container.innerHTML = '<div class="aidz-empty">暂无 AI 建议</div>';
      updatePanel('connected', composePanelInfo());
      return;
    }

    const prevActiveSessionId = activeSessionId;
    if (!activeSessionId || !sessionData[activeSessionId]) {
      activeSessionId = entries[0][0];
    }
    if (activeSessionId !== prevActiveSessionId) {
      schedulePersistLocalState();
    }

    if (panelViewMode === 'active') {
      const sid = activeSessionId;
      const session = sessionData[sid];
      if (!session || !Array.isArray(session.replies)) {
        panelViewMode = 'all';
        renderReplies();
        return;
      }

      const replies = [...session.replies]
        .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
        .slice(0, 20);

      container.innerHTML = `
        <div class="aidz-session-group">
          <div class="aidz-session-group-header">
            <span class="aidz-session-group-title">${escapeHtml(getSessionDisplayLabel(sid))}</span>
            <span class="aidz-session-group-meta">${getSessionPending(sid)} 待处理</span>
            <button class="aidz-link-btn" data-action="show-all">查看全部</button>
          </div>
          <div class="aidz-session-group-cards">
            ${replies.length > 0 ? replies.map(renderReplyCard).join('') : '<div class="aidz-empty">该会话暂无 AI 建议</div>'}
          </div>
        </div>
      `;
    } else {
      const groups = entries.slice(0, 10).map(([sid, data]) => {
        const pending = getSessionPending(sid);
        const replies = [...data.replies]
          .sort((a, b) => {
            const ap = a.status === 'pending' ? 1 : 0;
            const bp = b.status === 'pending' ? 1 : 0;
            if (bp !== ap) return bp - ap;
            return (b.createdAt || 0) - (a.createdAt || 0);
          })
          .slice(0, 4);
        const cardsHtml = replies.length > 0
          ? replies.map(renderReplyCard).join('')
          : '<div class="aidz-empty">暂无 AI 建议</div>';

        return `
          <div class="aidz-session-group">
            <div class="aidz-session-group-header">
              <span class="aidz-session-group-title">${escapeHtml(getSessionDisplayLabel(sid))}</span>
              <span class="aidz-session-group-meta">${pending} 待处理</span>
              <button class="aidz-link-btn" data-action="switch-session" data-session-key="${encodeURIComponent(sid)}">查看会话</button>
            </div>
            <div class="aidz-session-group-cards">
              ${cardsHtml}
            </div>
          </div>
        `;
      }).join('');

      container.innerHTML = groups || '<div class="aidz-empty">暂无 AI 建议</div>';
    }

    updatePanel('connected', composePanelInfo());
  }

  function handleReplyAction(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'show-all') {
      setPanelViewMode('all');
      return;
    }
    if (action === 'switch-session') {
      const sid = decodeSessionKey(btn.dataset.sessionKey || '');
      if (!sid) return;
      activeSessionId = sid;
      setPanelViewMode('active');
      return;
    }

    const id = btn.dataset.id;
    if (!id) return;

    let reply = null;
    for (const sid of Object.keys(sessionData)) {
      reply = sessionData[sid].replies.find((r) => r.id === id);
      if (reply) break;
    }
    if (!reply) return;

    switch (action) {
      case 'adopt': adoptReply(reply); break;
      case 'edit': toggleEditArea(reply); break;
      case 'ignore': ignoreReply(reply); break;
      case 'feedback-good': sendReplyFeedback(reply, 'good', btn); break;
      case 'feedback-bad': sendReplyFeedback(reply, 'bad', btn); break;
      case 'edit-cancel': closeEditArea(reply); break;
      case 'edit-confirm': confirmEdit(reply); break;
    }
  }

  function adoptReply(reply) {
    reply.status = 'adopted';
    reply.feedbackRating = 'good';
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    fillReplyInput(reply.editedText || reply.text);
    if (mode === 'auto-send') setTimeout(() => clickSendButton(), 300);
    schedulePersistLocalState();
    renderReplies();
    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      ai_reply_id: reply.aiReplyId || '',
      rating: 'good', action: 'adopted',
      original_reply: reply.text,
      edited_reply: reply.editedText || '',
      actual_reply: reply.editedText || reply.text,
    });
  }

  function toggleEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) {
      area.classList.toggle('active');
      if (area.classList.contains('active')) {
        const ta = document.getElementById(`edit-text-${reply.id}`);
        if (ta) ta.focus();
      }
    }
  }

  function closeEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) area.classList.remove('active');
  }

  function confirmEdit(reply) {
    const ta = document.getElementById(`edit-text-${reply.id}`);
    if (!ta) return;
    const editedText = ta.value.trim();
    if (!editedText) return;
    reply.editedText = editedText;
    reply.status = 'edited';
    reply.feedbackRating = 'good';
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    fillReplyInput(editedText);
    if (mode === 'auto-send') setTimeout(() => clickSendButton(), 300);
    schedulePersistLocalState();
    renderReplies();
    // 产品要求：编辑不反馈到后端。
  }

  function ignoreReply(reply) {
    reply.status = 'ignored';
    reply.feedbackRating = 'bad';
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    schedulePersistLocalState();
    renderReplies(); // UI 立刻更新，不等 feedback
    // 产品要求：忽略不反馈到后端。
  }

  function sendReplyFeedback(reply, type, btn) {
    reply.feedbackRating = type;
    schedulePersistLocalState();
    btn.classList.add('active');
    btn.disabled = true;
    const card = btn.closest('.aidz-reply-card');
    if (card) {
      const otherType = type === 'good' ? 'bad' : 'good';
      const otherBtn = card.querySelector(`[data-action="feedback-${otherType}"]`);
      if (otherBtn) { otherBtn.disabled = true; otherBtn.classList.add('aidz-btn-disabled'); }
    }
    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      ai_reply_id: reply.aiReplyId || '',
      rating: type,
      action: reply.status === 'pending' ? '' : reply.status,
      original_reply: reply.text,
      edited_reply: reply.editedText || '',
      actual_reply: '',
    });
  }

  function statusLabel(status) {
    return { adopted: '已采纳', edited: '已编辑', ignored: '已忽略' }[status] || status;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* ═══════════════════ Init ═══════════════════ */
  // document_start 时 body 可能还不存在，等 DOM 就绪再创建面板
  function initPanel() {
    restoreLocalState();
    if (document.body) {
      createPanel();
      console.log('[AI店长] v3 已加载 — 数据驱动多会话 + 全量聊天记录采集');
    } else {
      document.addEventListener('DOMContentLoaded', () => {
        createPanel();
        console.log('[AI店长] v3 已加载 — 数据驱动多会话 + 全量聊天记录采集');
      });
    }
  }

  window.addEventListener('beforeunload', () => {
    if (persistStateTimer) {
      clearTimeout(persistStateTimer);
      persistStateTimer = null;
    }
    persistLocalStateNow();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      if (persistStateTimer) {
        clearTimeout(persistStateTimer);
        persistStateTimer = null;
      }
      persistLocalStateNow();
    }
  });

  initPanel();
})();
