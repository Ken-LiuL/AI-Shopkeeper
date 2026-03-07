/**
 * background.js — AI店长 Chrome Extension Service Worker
 * 1. 处理客服 IM 消息，请求 AI 回复
 * 2. 接收业务数据并同步到后端
 */

const DEFAULT_CHAT_API = 'http://192.144.227.205:8000/api/v1/customer-service/chat';
const DEFAULT_SYNC_API = 'http://192.144.227.205:8000';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;
const THROTTLE_MS = 10_000; // 10s 节流（从 30s 降低）

// 节流状态
const lastSentAt = {};
// 同步统计
const syncStats = {};
const syncErrors = {};
// Debug 日志（最近 50 条）
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

// ─── 消息路由 ─────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CUSTOMER_MESSAGE') {
    handleCustomerMessage(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (message.type === 'BUSINESS_DATA') {
    handleBusinessData(message.payload)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (message.type === 'GET_SYNC_STATS') {
    sendResponse({ success: true, stats: syncStats, errors: syncErrors, lastSentAt, debugLogs });
    return false;
  }

  if (message.type === 'FORCE_SYNC') {
    Object.keys(lastSentAt).forEach((k) => delete lastSentAt[k]);
    addLog('info', '已清除节流，下次数据将立即发送');
    sendResponse({ success: true });
    return false;
  }

  if (message.type === 'TEST_CONNECTION') {
    testConnection().then((result) => sendResponse(result));
    return true;
  }
});

// ─── 连接测试 ────────────────────────────────────────────────────────
async function testConnection() {
  const settings = await chrome.storage.sync.get(['syncApiBase']);
  const baseUrl = settings.syncApiBase || DEFAULT_SYNC_API;
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

// ─── 客服消息处理 ────────────────────────────────────────────────────
async function handleCustomerMessage(payload) {
  const settings = await chrome.storage.sync.get(['apiUrl', 'apiKey', 'storeId']);
  const apiUrl = settings.apiUrl || DEFAULT_CHAT_API;

  const body = {
    message: payload.message,
    session_id: payload.session_id,
    customer_info: payload.customer_info || {},
  };
  if (settings.storeId) body.store_id = settings.storeId;

  const headers = { 'Content-Type': 'application/json' };
  if (settings.apiKey) headers['Authorization'] = `Bearer ${settings.apiKey}`;

  let lastError;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(apiUrl, { method: 'POST', headers, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const reply = data.reply || data.message || data.response || data.data?.reply || '';
      if (!reply) return { success: false, error: '后台返回空回复' };
      return { success: true, reply };
    } catch (err) {
      lastError = err;
      if (attempt < MAX_RETRIES) await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
    }
  }
  return { success: false, error: lastError?.message || '请求失败' };
}

// ─── 业务数据同步 ─────────────────────────────────────────────────────
async function handleBusinessData({ type, url, data }) {
  const now = Date.now();
  const normalType = normalizeType(type);
  const shortUrl = url ? url.split('/').slice(-2).join('/') : '?';

  addLog('info', `捕获 [${normalType}] 来自 ${shortUrl}`);

  // 节流
  if (lastSentAt[type] && now - lastSentAt[type] < THROTTLE_MS) {
    addLog('info', `节流跳过 [${normalType}]，距上次 ${Math.round((now - lastSentAt[type]) / 1000)}s`);
    return { success: true, skipped: true, reason: 'throttled' };
  }

  const settings = await chrome.storage.sync.get(['syncApiBase', 'tenantId']);
  const baseUrl = settings.syncApiBase || DEFAULT_SYNC_API;
  const tenantId = settings.tenantId || 'default';

  const body = {
    source: 'chrome_extension',
    data_type: normalType,
    tenant_id: tenantId,
    raw_data: data,
  };

  try {
    const response = await fetch(`${baseUrl}/api/sync/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status}: ${errText.slice(0, 100)}`);
    }

    lastSentAt[type] = now;
    const count = estimateCount(type, data);
    syncStats[normalType] = (syncStats[normalType] || 0) + count;

    addLog('success', `✅ 同步成功 [${normalType}] ${count} 条`, baseUrl);

    await chrome.storage.local.set({ syncStats, syncErrors, lastSentAt, debugLogs });
    return { success: true, count };
  } catch (err) {
    syncErrors[normalType] = (syncErrors[normalType] || 0) + 1;
    addLog('error', `❌ 同步失败 [${normalType}]: ${err.message}`, baseUrl);
    await chrome.storage.local.set({ syncStats, syncErrors, lastSentAt, debugLogs });
    return { success: false, error: err.message };
  }
}

// ─── 类型规范化 ──────────────────────────────────────────────────────
function normalizeType(type) {
  const map = {
    table_query: 'orders',
    complex_query: 'products',
    merchant: 'merchant',
    channels: 'channels',
    metrics: 'metrics',
    orders: 'orders',
    products: 'products',
    reviews: 'reviews',
    inventory: 'inventory',
    refunds: 'refunds',
    traffic: 'metrics',
  };
  return map[type] || type;
}

// ─── 估算记录数 ──────────────────────────────────────────────────────
function estimateCount(type, data) {
  try {
    const candidates = [
      data?.data?.productList,
      data?.data?.list,
      data?.data?.items,
      data?.data?.orders,
      data?.data?.reviews,
      data?.data,
      data?.list,
      data?.items,
      data?.rows,
      data?.records,
      data?.result,
    ];
    for (const l of candidates) {
      if (Array.isArray(l) && l.length > 0) return l.length;
    }
    if (data?.data?.totalCount) return Number(data.data.totalCount);
    if (data?.data?.total) return Number(data.data.total);
  } catch (_) {}
  return 1;
}
