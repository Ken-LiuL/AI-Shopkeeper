/**
 * background.js — Service worker for AI店长 Chrome Extension.
 * 1. 处理客服 IM 消息，请求 AI 回复
 * 2. 接收业务数据并同步到后端（节流 30 秒/类型）
 */

const DEFAULT_CHAT_API = 'https://ai-shopkeeper-1dl4.onrender.com/api/v1/customer-service/chat';
const DEFAULT_SYNC_API = 'https://ai-shopkeeper-kk.fly.dev';
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;
const THROTTLE_MS = 30_000; // 同类型数据 30 秒内只发一次

// 节流状态：{ [type]: lastSentTimestamp }
const lastSentAt = {};
// 同步统计：{ [type]: count }
const syncStats = {};

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
    sendResponse({ success: true, stats: syncStats, lastSentAt });
    return false;
  }

  if (message.type === 'FORCE_SYNC') {
    // 清除节流限制，允许立即发送
    Object.keys(lastSentAt).forEach((k) => delete lastSentAt[k]);
    sendResponse({ success: true });
    return false;
  }
});

// ─── 客服消息处理（原有逻辑） ────────────────────────────────────────
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
      const response = await fetch(apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        throw new Error(`HTTP ${response.status}: ${errText.slice(0, 200)}`);
      }

      const data = await response.json();
      const reply = data.reply || data.message || data.response || data.data?.reply || '';
      if (!reply) return { success: false, error: '后台返回空回复' };
      return { success: true, reply };
    } catch (err) {
      lastError = err;
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
      }
    }
  }
  return { success: false, error: lastError?.message || '请求失败' };
}

// ─── 业务数据同步 ─────────────────────────────────────────────────────
async function handleBusinessData({ type, url, data }) {
  const now = Date.now();

  // 节流：同类型 30 秒内只发一次
  if (lastSentAt[type] && now - lastSentAt[type] < THROTTLE_MS) {
    return { success: true, skipped: true, reason: 'throttled' };
  }

  const settings = await chrome.storage.sync.get(['syncApiBase', 'tenantId']);
  const baseUrl = settings.syncApiBase || DEFAULT_SYNC_API;
  const tenantId = settings.tenantId || 'default';

  const body = {
    source: 'chrome_extension',
    data_type: normalizeType(type),
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

    // 更新节流时间和统计
    lastSentAt[type] = now;
    const count = estimateCount(type, data);
    syncStats[type] = (syncStats[type] || 0) + count;

    // 持久化统计到 storage（供 popup 读取）
    await chrome.storage.local.set({
      syncStats,
      lastSentAt,
    });

    console.log(`[AI店长] 已同步 ${type} 数据，共 ${count} 条`);
    return { success: true, count };
  } catch (err) {
    // 静默失败，不影响正常使用
    console.warn(`[AI店长] 同步 ${type} 失败（静默）:`, err.message);
    return { success: false, error: err.message };
  }
}

/**
 * 将内部类型名规范化为后端期望的 data_type
 */
function normalizeType(type) {
  const map = {
    table_query: 'orders',
    complex_query: 'products',
    merchant: 'merchant',
    channels: 'channels',
    metrics: 'metrics',
    orders: 'orders',
    products: 'products',
  };
  return map[type] || type;
}

/**
 * 从响应数据中估算记录数
 */
function estimateCount(type, data) {
  try {
    // 常见列表结构
    const lists = [data.data, data.list, data.items, data.rows, data.records, data.result];
    for (const l of lists) {
      if (Array.isArray(l)) return l.length;
    }
    // 嵌套
    if (data.data?.list) return data.data.list.length || 1;
    if (data.data?.total) return data.data.total;
  } catch (_) {}
  return 1;
}
