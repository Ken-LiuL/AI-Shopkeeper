/**
 * background.js — AI店长 Chrome Extension Service Worker
 * 处理客服消息转发 + 反馈接口
 */

const DEFAULT_API_BASE = 'https://ai-shopkeeper-kk.fly.dev';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;
const debugLogs = [];

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
  const chatBase = settings.chatApiBase || DEFAULT_API_BASE;
  const apiUrl = settings.apiUrl || `${chatBase}/api/customer-service/chat`;
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
  const settings = await getApiSettings();
  const body = {
    message: payload.message,
    session_id: payload.session_id,
    customer_info: payload.customer_info || {},
  };
  if (settings.storeId) body.store_id = settings.storeId;

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers.Authorization = `Bearer ${settings.apiKey}`;

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(settings.apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(`HTTP ${response.status}${errText ? `: ${errText.slice(0, 120)}` : ''}`);
      }
      const data = await response.json();
      const reply = data.reply || data.message || data.response || data.data?.reply || '';
      if (!reply) {
        addLog('error', '后台返回空回复');
        return { success: false, error: '后台返回空回复' };
      }
      addLog('success', '客服回复生成成功', reply.slice(0, 60));
      return { success: true, reply };
    } catch (err) {
      lastError = err;
      addLog('error', `请求失败 (尝试 ${attempt + 1}/${MAX_RETRIES + 1})`, err.message);
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
      }
    }
  }

  addLog('error', '客服回复生成失败', lastError?.message || 'unknown');
  return { success: false, error: lastError?.message || '请求失败' };
}

/* ═══════════════════ Feedback API ═══════════════════ */
async function handleFeedback(payload) {
  const settings = await getApiSettings();
  const feedbackUrl = `${settings.chatBase}/api/customer-service/feedback`;

  const body = {
    session_id: payload.session_id || '',
    message_id: payload.message_id || '',
    feedback: payload.feedback || '',      // "good" | "bad" | "neutral"
    action: payload.action || '',          // "adopted" | "edited" | "ignored"
    original_reply: payload.original_reply || '',
    edited_reply: payload.edited_reply || '',
    actual_reply: payload.actual_reply || '',
    timestamp: new Date().toISOString(),
  };

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers.Authorization = `Bearer ${settings.apiKey}`;

  try {
    const response = await fetch(feedbackUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      const errMsg = `反馈 HTTP ${response.status}${errText ? `: ${errText.slice(0, 80)}` : ''}`;
      addLog('error', errMsg);
      // Non-critical: don't retry feedback, just log
      return { success: false, error: errMsg };
    }

    addLog('info', `反馈已发送: ${body.action || body.feedback}`, `session=${body.session_id}`);
    return { success: true };
  } catch (err) {
    // Feedback failures are non-critical — log but don't block
    addLog('error', `反馈发送失败: ${err.message}`);
    return { success: false, error: err.message };
  }
}
