/**
 * background.js — AI店长 Chrome Extension Service Worker
 * 1. 处理客服消息，请求 AI 回复
 * 2. 接收业务数据并同步到后端
 */

const DEFAULT_API_BASE = 'https://ai-shopkeeper-kk.fly.dev';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;
const THROTTLE_MS = 10_000; // 10s 节流

const lastSentAt = {};
const syncStats = {};
const syncErrors = {};
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
    'syncApiBase',
    'chatApiBase',
    'apiUrl',
    'apiKey',
    'storeId',
    'tenantId',
  ]);
  const syncBase = settings.syncApiBase || DEFAULT_API_BASE;
  const chatBase = settings.chatApiBase || DEFAULT_API_BASE;
  const chatApiUrl = settings.apiUrl || `${chatBase}/api/customer-service/chat`;
  return { ...settings, syncBase, chatBase, chatApiUrl };
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
  const settings = await getApiSettings();
  const baseUrl = settings.syncBase;
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
  const settings = await getApiSettings();
  const apiUrl = settings.chatApiUrl;
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

// ─── 从 API 响应中提取业务数据列表 ───────────────────────────────────
/**
 * API 响应结构各异，需要从嵌套中找到实际的记录列表
 * 支持：{ data: { productList: [] } } / { data: { list: [] } } / { list: [] } 等格式
 */
function extractDataList(type, responseData) {
  if (!responseData || typeof responseData !== 'object') return [];

  // 优先尝试 data 层
  const d = responseData.data || responseData;

  // 已知的列表字段名（按类型优先）
  const listKeys = {
    products: ['productList', 'list', 'items', 'spuList', 'skuList', 'goods'],
    orders: ['list', 'items', 'orders', 'orderList', 'data'],
    reviews: ['list', 'items', 'reviews', 'commentList', 'evaluateList'],
    inventory: ['list', 'items', 'stockList', 'inventoryList'],
    refunds: ['list', 'items', 'refundList', 'afterSaleList'],
    metrics: ['list', 'items', 'statList', 'reportList'],
  };

  const keys = listKeys[type] || ['list', 'items', 'data'];
  for (const key of keys) {
    if (Array.isArray(d[key]) && d[key].length > 0) return d[key];
  }

  // 如果 d 本身是数组
  if (Array.isArray(d) && d.length > 0) return d;

  // 最后兜底：把整个响应包成单条
  if (typeof d === 'object' && Object.keys(d).length > 0) return [d];

  return [];
}

// ─── 业务数据同步 ─────────────────────────────────────────────────────
async function handleBusinessData({ type, url, data }) {
  const now = Date.now();
  const normalType = normalizeType(type);
  const shortUrl = url ? url.split('/').slice(-2).join('/') : '?';

  addLog('info', `捕获 [${normalType}] 来自 /${shortUrl}`);

  // 节流
  if (lastSentAt[type] && now - lastSentAt[type] < THROTTLE_MS) {
    addLog('info', `节流跳过 [${normalType}]，距上次 ${Math.round((now - lastSentAt[type]) / 1000)}s`);
    return { success: true, skipped: true, reason: 'throttled' };
  }

  // ── 提取实际数据列表（关键：必须是 list[dict]）──
  const extractedList = extractDataList(normalType, data);
  if (extractedList.length === 0) {
    addLog('info', `跳过 [${normalType}]：响应中未发现有效列表数据`);
    return { success: true, skipped: true, reason: 'no_data' };
  }

  const settings = await getApiSettings();
  const baseUrl = settings.syncBase;

  // ── 按后端 IngestRequest 格式发送 ──
  // source 必须是 SOURCE_TABLE_MAP 的 key: products/orders/reviews/...
  const body = {
    source: normalType,
    data: extractedList,
    synced_at: new Date().toISOString(),
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
    const count = extractedList.length;
    syncStats[normalType] = (syncStats[normalType] || 0) + count;

    addLog('success', `✅ 同步成功 [${normalType}] ${count} 条`);
    await chrome.storage.local.set({ syncStats, syncErrors, lastSentAt, debugLogs });
    return { success: true, count };
  } catch (err) {
    syncErrors[normalType] = (syncErrors[normalType] || 0) + 1;
    addLog('error', `❌ 同步失败 [${normalType}]: ${err.message}`);
    await chrome.storage.local.set({ syncStats, syncErrors, lastSentAt, debugLogs });
    return { success: false, error: err.message };
  }
}

// ─── 类型规范化 ──────────────────────────────────────────────────────
function normalizeType(type) {
  const map = {
    merchant: 'channels',
    channels: 'channels',
    metrics: 'metrics',
    orders: 'orders',
    products: 'products',
    reviews: 'reviews',
    inventory: 'inventory',
    refunds: 'refunds',
    traffic: 'traffic',
  };
  return map[type] || type;
}
