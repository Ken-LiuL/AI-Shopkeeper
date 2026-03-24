/**
 * background.js — AI店长 Chrome Extension Service Worker
 * 处理客服消息转发 + 反馈接口
 */

const DEFAULT_API_BASE = 'http://192.144.227.205:8000';
const LEGACY_API_BASES = new Set([
  'https://ai-shopkeeper-kk.fly.dev',
  'https://ai-shopkeeper-kk.fly.dev/',
]);
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1500;
const REQUEST_TIMEOUT_MS = 30000; // 30s 超时
const MESSAGE_DEDUP_TTL_MS = 8000;
const MAX_RECENT_MESSAGE_RESULTS = 200;
const debugLogs = [];
const sessionRequestChains = new Map(); // session_id -> Promise
const inflightMessageRequests = new Map(); // dedup_key -> Promise
const recentMessageResults = new Map(); // dedup_key -> { ts, result }

function addLog(level, msg, detail = '') {
  const entry = { time: new Date().toLocaleTimeString(), level, msg, detail };
  debugLogs.unshift(entry);
  if (debugLogs.length > 50) debugLogs.pop();
  chrome.storage.local.set({ debugLogs });
  if (level === 'error') {
    console.warn(`[AI店长] ${msg}`, detail);
  } else {
    console.log(`[AI店长] ${msg}`, detail);
  }
}

async function getApiSettings() {
  const settings = await chrome.storage.sync.get([
    'chatApiBase',
    'apiUrl',
    'apiKey',
    'storeId',
  ]);
  const rawChatBase = (settings.chatApiBase || '').trim();
  const rawApiUrl = (settings.apiUrl || '').trim();
  const chatBase = !rawChatBase || LEGACY_API_BASES.has(rawChatBase)
    ? DEFAULT_API_BASE
    : rawChatBase.replace(/\/+$/, '');

  let apiUrl = rawApiUrl;
  if (!apiUrl) {
    apiUrl = `${chatBase}/api/customer-service/chat`;
  } else if (apiUrl.startsWith('https://ai-shopkeeper-kk.fly.dev')) {
    apiUrl = apiUrl.replace('https://ai-shopkeeper-kk.fly.dev', chatBase);
  }

  const updates = {};
  if (rawChatBase !== chatBase) {
    updates.chatApiBase = chatBase;
  }
  if (rawApiUrl && rawApiUrl !== apiUrl) {
    // 仅迁移显式配置（如 legacy fly URL），默认空值保持为空以便随 base 动态生效
    updates.apiUrl = apiUrl;
  }
  if (Object.keys(updates).length > 0) {
    chrome.storage.sync.set(updates);
  }

  return {
    chatBase,
    apiUrl,
    apiKey: settings.apiKey || '',
    storeId: settings.storeId || '',
  };
}

/* ═══════════════════ Message Router ═══════════════════ */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CUSTOMER_MESSAGE') {
    handleCustomerMessage(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // async
  }

  if (message.type === 'SEND_FEEDBACK') {
    handleFeedback(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // async
  }

  if (message.type === 'LOG_CHAT') {
    handleLogChat(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (message.type === 'GET_SYNC_STATS') {
    sendResponse({ success: true, stats: {}, errors: {}, debugLogs });
    return false;
  }

  if (message.type === 'TEST_CONNECTION') {
    testConnection().then((result) => sendResponse(result));
    return true;
  }

  return false;
});

function getSessionChainKey(payload) {
  const sid = (payload?.session_id || '').trim();
  return sid || '__default__';
}

function buildMessageDedupKey(payload) {
  const sid = (payload?.session_id || '').trim();
  const messageId = String(payload?.message_id || '').trim();
  if (sid && messageId) return `${sid}#${messageId}`;
  const msg = String(payload?.message || '')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .slice(0, 280);
  if (!sid || !msg) return '';
  return `${sid}::${msg}`;
}

function cleanupRecentMessageResults(now = Date.now()) {
  for (const [key, item] of recentMessageResults.entries()) {
    if (!item || (now - item.ts) > MESSAGE_DEDUP_TTL_MS) {
      recentMessageResults.delete(key);
    }
  }
  if (recentMessageResults.size <= MAX_RECENT_MESSAGE_RESULTS) return;
  const overflow = recentMessageResults.size - MAX_RECENT_MESSAGE_RESULTS;
  const keys = recentMessageResults.keys();
  for (let i = 0; i < overflow; i++) {
    const { value, done } = keys.next();
    if (done) break;
    recentMessageResults.delete(value);
  }
}

async function enqueueBySession(payload, task) {
  const sessionKey = getSessionChainKey(payload);
  const previous = sessionRequestChains.get(sessionKey) || Promise.resolve();

  const current = previous
    .catch(() => null)
    .then(task);

  sessionRequestChains.set(
    sessionKey,
    current.finally(() => {
      if (sessionRequestChains.get(sessionKey) === current) {
        sessionRequestChains.delete(sessionKey);
      }
    })
  );
  return current;
}

/* ═══════════════════ Connection Test ═══════════════════ */
async function testConnection() {
  const settings = await getApiSettings();
  const baseUrl = settings.chatBase;
  try {
    const r = await fetch(`${baseUrl}/health`, { method: 'GET' });
    const ok = r.ok;
    addLog(ok ? 'info' : 'error', `连接测试: ${ok ? '成功' : '失败'} (${r.status})`, baseUrl);
    return { success: ok, status: r.status, url: baseUrl };
  } catch (err) {
    addLog('error', `连接测试失败: ${err.message}`, baseUrl);
    return { success: false, error: err.message, url: baseUrl };
  }
}

/* ═══════════════════ Customer Message → AI Reply ═══════════════════ */
async function handleCustomerMessage(payload) {
  const dedupKey = buildMessageDedupKey(payload);
  const now = Date.now();
  cleanupRecentMessageResults(now);

  if (!dedupKey) {
    return enqueueBySession(payload, () => handleCustomerMessageDirect(payload));
  }

  const cached = recentMessageResults.get(dedupKey);
  if (cached && (now - cached.ts) <= MESSAGE_DEDUP_TTL_MS) {
    addLog('info', '命中消息去重缓存', dedupKey.slice(0, 96));
    return cached.result;
  }

  const inflight = inflightMessageRequests.get(dedupKey);
  if (inflight) {
    addLog('info', '复用进行中的同消息请求', dedupKey.slice(0, 96));
    return inflight;
  }

  const task = enqueueBySession(payload, () => handleCustomerMessageDirect(payload))
    .then((result) => {
      recentMessageResults.set(dedupKey, { ts: Date.now(), result });
      cleanupRecentMessageResults();
      return result;
    })
    .finally(() => {
      if (inflightMessageRequests.get(dedupKey) === task) {
        inflightMessageRequests.delete(dedupKey);
      }
    });

  inflightMessageRequests.set(dedupKey, task);
  return task;
}

async function handleCustomerMessageDirect(payload) {
  const settings = await getApiSettings();
  const body = {
    message: payload.message,
    session_id: payload.session_id,
    message_id: payload.message_id || '',
    customer_info: payload.customer_info || {},
  };
  if (payload.order_context && typeof payload.order_context === 'object') {
    body.order_context = payload.order_context;
  }
  if (settings.storeId) body.store_id = settings.storeId;

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers.Authorization = `Bearer ${settings.apiKey}`;

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const t0 = Date.now();
      const response = await fetch(settings.apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        const httpErr = new Error(`HTTP ${response.status}${errText ? `: ${errText.slice(0, 120)}` : ''}`);
        httpErr.status = response.status;
        if (response.status === 429) {
          httpErr.code = 'SESSION_BUSY';
        }
        throw httpErr;
      }
      const data = await response.json();
      const payload = (data && typeof data.data === 'object' && data.data) ? data.data : data;
      const reply = payload.reply || data.reply || data.message || data.response || '';
      const aiReplyId = payload.ai_reply_id || data.ai_reply_id || '';
      const errorCode = payload.error_code || data.error_code || '';
      const errorDetail = payload.error_detail || data.error_detail || '';
      const contextTrace = (payload.context_trace && typeof payload.context_trace === 'object')
        ? payload.context_trace
        : {};
      const elapsed = Date.now() - t0;

      if (errorCode) {
        addLog(
          'error',
          `客服接口返回错误码: ${errorCode}`,
          typeof errorDetail === 'string' ? errorDetail.slice(0, 120) : ''
        );
        return { success: false, error: `AI服务异常 (${errorCode})` };
      }

      if (!reply) {
        addLog('error', '后台返回空回复');
        return { success: false, error: '后台返回空回复，请稍后重试' };
      }
      addLog('success', `客服回复生成成功 (${elapsed}ms)`, reply.slice(0, 60));
      if (contextTrace.has_extension_order_fields || contextTrace.direct_logistics_from_extension) {
        addLog('info', '本次回复已使用工作台订单上下文', JSON.stringify(contextTrace).slice(0, 160));
      }
      return {
        success: true,
        reply,
        ai_reply_id: aiReplyId || '',
        product_cards: payload.product_cards || [],
        context_trace: contextTrace,
      };
    } catch (err) {
      clearTimeout(timeoutId);
      lastError = err;

      const isTimeout = err.name === 'AbortError';
      const isSessionBusy = err?.code === 'SESSION_BUSY'
        || err?.status === 429
        || (err.message && err.message.includes('Session is busy'));
      const friendlyMsg = isTimeout
        ? `AI思考超时 (尝试 ${attempt + 1}/${MAX_RETRIES + 1})`
        : isSessionBusy
          ? `会话排队中 (尝试 ${attempt + 1}/${MAX_RETRIES + 1})`
          : `请求异常 (尝试 ${attempt + 1}/${MAX_RETRIES + 1})`;
      addLog('error', friendlyMsg, err.message);

      if (attempt < MAX_RETRIES) {
        // 对 session busy 使用短退避，避免 UI 卡住 10s
        const delay = isSessionBusy
          ? Math.min(1200 * (attempt + 1), 3500)
          : RETRY_DELAY_MS * (attempt + 1);
        addLog('info', `等待 ${delay}ms 后重试...`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  addLog('error', '客服回复生成失败', lastError?.message || 'unknown');
  const isTimeout = lastError?.name === 'AbortError';
  const isSessionBusy = lastError?.code === 'SESSION_BUSY'
    || lastError?.status === 429
    || (lastError?.message && lastError.message.includes('Session is busy'));
  return {
    success: false,
    error: isTimeout
      ? 'AI正在思考中，请稍候重试~'
      : isSessionBusy
        ? '当前会话正在处理上一条消息，请稍后 1-2 秒重试'
        : `服务暂时繁忙，请稍后重试 (${lastError?.message || '未知错误'})`,
  };
}

/* ═══════════════════ Chat Log Collection ═══════════════════ */
async function handleLogChat(payload) {
  const settings = await getApiSettings();
  const logUrl = `${settings.chatBase}/api/customer-service/log-chat`;

  const body = {
    session_id: payload.session_id || '',
    message_id: payload.message_id || '',
    role: payload.role || 'agent',
    content: payload.content || '',
    timestamp: payload.timestamp || new Date().toISOString(),
  };

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers.Authorization = `Bearer ${settings.apiKey}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(logUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      // Non-critical: just log
      addLog('error', `聊天记录上报失败: HTTP ${response.status}`);
      return { success: false };
    }
    return { success: true };
  } catch (err) {
    // Silent fail — chat log is best-effort
    addLog('error', `聊天记录上报异常: ${err.message}`);
    return { success: false, error: err.message };
  }
}

/* ═══════════════════ Feedback API ═══════════════════ */
async function handleFeedback(payload) {
  const settings = await getApiSettings();
  const feedbackUrl = `${settings.chatBase}/api/customer-service/feedback`;

  const allowedActions = new Set(['adopted', 'edited', 'ignored']);
  const requestedAction = (payload.action || '').trim();
  const action = allowedActions.has(requestedAction) ? requestedAction : '';

  let rating = (payload.rating || payload.feedback || '').toString().trim().toLowerCase();
  if (!['good', 'bad'].includes(rating)) {
    const actionToRating = { adopted: 'good', edited: 'bad', ignored: 'bad' };
    rating = actionToRating[action] || '';
  }
  if (!['good', 'bad'].includes(rating)) {
    const errMsg = '反馈缺少有效评分（rating: good/bad）';
    addLog('error', errMsg, `session=${payload.session_id || ''}`);
    return { success: false, error: errMsg };
  }

  const body = {
    session_id: payload.session_id || '',
    message_id: payload.message_id || '',
    ai_reply_id: payload.ai_reply_id || '',
    rating,                                // "good" | "bad"
    original_reply: payload.original_reply || '',
    edited_reply: payload.edited_reply || '',
    actual_reply: payload.actual_reply || '',
    timestamp: new Date().toISOString(),
  };
  if (action) {
    body.action = action;                  // "adopted" | "edited" | "ignored"
  }

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers.Authorization = `Bearer ${settings.apiKey}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    const response = await fetch(feedbackUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      const errMsg = `反馈 HTTP ${response.status}${errText ? `: ${errText.slice(0, 80)}` : ''}`;
      addLog('error', errMsg);
      // Non-critical: don't retry feedback, just log
      return { success: false, error: errMsg };
    }

    addLog('info', `反馈已发送: ${body.action || body.rating}`, `session=${body.session_id}`);
    return {
      success: true,
      stored: {
        rating: body.rating,
        action: body.action || '',
      },
    };
  } catch (err) {
    // Feedback failures are non-critical — log but don't block
    addLog('error', `反馈发送失败: ${err.message}`);
    return { success: false, error: err.message };
  }
}
