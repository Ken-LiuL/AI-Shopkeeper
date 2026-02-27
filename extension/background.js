/**
 * Background Service Worker - 负责定时同步调度和后端通信
 */

// 导入配置 (Service Worker 不支持 ES6 import)
importScripts('config/data_sources.js');

const ALARM_PREFIX = 'aiStoreManager_';
const BACKEND_TIMEOUT = 30000; // 30秒

let syncStatus = {};
let config = {};

console.log('AI店长 Background Service Worker 已启动');

/**
 * 初始化
 */
chrome.runtime.onStartup.addListener(initialize);
chrome.runtime.onInstalled.addListener(initialize);

async function initialize() {
  console.log('初始化 Background Service Worker');

  // 加载配置
  await loadConfig();

  // 设置定时器
  await setupAlarms();

  // 加载同步状态
  await loadSyncStatus();
}

/**
 * 加载配置
 */
async function loadConfig() {
  try {
    const stored = await chrome.storage.sync.get({
      backendUrl: DEFAULT_CONFIG.backendUrl,
      apiKey: DEFAULT_CONFIG.apiKey,
      enabledSources: Object.keys(DATA_SOURCES).filter(key => DATA_SOURCES[key].enabled)
    });

    config = stored;
    console.log('配置已加载:', config);
  } catch (error) {
    console.error('加载配置失败:', error);
    config = {
      backendUrl: DEFAULT_CONFIG.backendUrl,
      apiKey: '',
      enabledSources: Object.keys(DATA_SOURCES).filter(key => DATA_SOURCES[key].enabled)
    };
  }
}

/**
 * 加载同步状态
 */
async function loadSyncStatus() {
  try {
    const stored = await chrome.storage.local.get('syncStatus');
    syncStatus = stored.syncStatus || {};
    console.log('同步状态已加载:', Object.keys(syncStatus).length, '个数据源');
  } catch (error) {
    console.error('加载同步状态失败:', error);
    syncStatus = {};
  }
}

/**
 * 保存同步状态
 */
async function saveSyncStatus() {
  try {
    await chrome.storage.local.set({ syncStatus });
  } catch (error) {
    console.error('保存同步状态失败:', error);
  }
}

/**
 * 设置定时器
 */
async function setupAlarms() {
  // 清除现有的定时器
  const existingAlarms = await chrome.alarms.getAll();
  for (const alarm of existingAlarms) {
    if (alarm.name.startsWith(ALARM_PREFIX)) {
      chrome.alarms.clear(alarm.name);
    }
  }

  // 为每个启用的数据源设置定时器
  for (const [source, sourceConfig] of Object.entries(DATA_SOURCES)) {
    if (sourceConfig.enabled && config.enabledSources.includes(source)) {
      const alarmName = `${ALARM_PREFIX}${source}`;
      const intervalMinutes = sourceConfig.interval / (1000 * 60);

      chrome.alarms.create(alarmName, {
        delayInMinutes: 1, // 1分钟后开始
        periodInMinutes: Math.max(1, intervalMinutes) // 最小1分钟间隔
      });

      console.log(`设置定时器: ${source} (${intervalMinutes}分钟)`);
    }
  }
}

/**
 * 处理定时器触发
 */
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith(ALARM_PREFIX)) {
    return;
  }

  const source = alarm.name.replace(ALARM_PREFIX, '');
  console.log(`定时器触发: ${source}`);

  await performSync(source, 'auto');
});

/**
 * 执行同步
 */
async function performSync(source, trigger = 'manual') {
  console.log(`开始同步 ${source} (触发: ${trigger})`);

  const startTime = Date.now();
  const sourceConfig = DATA_SOURCES[source];

  if (!sourceConfig) {
    console.error(`未知数据源: ${source}`);
    return { success: false, error: '未知数据源' };
  }

  // 更新同步状态
  syncStatus[source] = {
    ...syncStatus[source],
    lastAttempt: new Date().toISOString(),
    status: 'running',
    trigger
  };
  await saveSyncStatus();

  try {
    // 查找牵牛花标签页
    const qnhTabs = await findQNHTabs();
    if (qnhTabs.length === 0) {
      throw new Error('未找到牵牛花页面，请确保已登录 qnh.meituan.com');
    }

    const tab = qnhTabs[0]; // 使用第一个找到的标签页

    // 向 content script 请求数据
    const response = await sendMessageToTab(tab.id, {
      action: 'syncData',
      source
    });

    if (!response.success) {
      throw new Error(response.error || '数据获取失败');
    }

    // 推送数据到后端
    const pushResult = await pushDataToBackend(source, response.data, {
      tabId: tab.id,
      tabUrl: tab.url,
      trigger,
      syncTime: response.timestamp
    });

    if (!pushResult.success) {
      throw new Error(pushResult.error || '数据推送失败');
    }

    // 更新成功状态
    const duration = Date.now() - startTime;
    syncStatus[source] = {
      ...syncStatus[source],
      status: 'success',
      lastSuccess: new Date().toISOString(),
      lastCount: response.count || 0,
      lastDuration: duration,
      nextSync: calculateNextSyncTime(sourceConfig.interval),
      error: null
    };

    console.log(`${source} 同步成功: ${response.count} 条记录, 耗时 ${duration}ms`);

    await saveSyncStatus();
    return { success: true, count: response.count, duration };

  } catch (error) {
    console.error(`${source} 同步失败:`, error);

    // 更新失败状态
    syncStatus[source] = {
      ...syncStatus[source],
      status: 'error',
      lastError: new Date().toISOString(),
      error: error.message,
      nextSync: calculateNextSyncTime(sourceConfig.interval)
    };

    await saveSyncStatus();
    return { success: false, error: error.message };
  }
}

/**
 * 查找牵牛花标签页
 */
async function findQNHTabs() {
  try {
    const tabs = await chrome.tabs.query({
      url: '*://qnh.meituan.com/*'
    });
    return tabs.filter(tab => tab.url && !tab.url.includes('login'));
  } catch (error) {
    console.error('查找标签页失败:', error);
    return [];
  }
}

/**
 * 向标签页发送消息
 */
function sendMessageToTab(tabId, message, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('消息发送超时'));
    }, timeout);

    chrome.tabs.sendMessage(tabId, message, (response) => {
      clearTimeout(timer);

      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(response || { success: false, error: '无响应' });
      }
    });
  });
}

/**
 * 推送数据到后端
 */
async function pushDataToBackend(source, data, metadata = {}) {
  if (!config.backendUrl) {
    throw new Error('后端 URL 未配置');
  }

  if (!config.apiKey) {
    console.warn('API Key 未配置，将尝试无认证推送');
  }

  const url = `${config.backendUrl}/api/sync/push`;
  const payload = {
    source,
    data: Array.isArray(data) ? data : [data],
    timestamp: new Date().toISOString(),
    metadata: {
      ...metadata,
      extensionVersion: chrome.runtime.getManifest().version,
      userAgent: navigator.userAgent
    }
  };

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(config.apiKey && { 'X-API-Key': config.apiKey })
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT)
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorText || response.statusText}`);
    }

    const result = await response.json();
    console.log(`数据推送成功: ${source}`, result);

    return { success: true, result };

  } catch (error) {
    console.error(`数据推送失败: ${source}`, error);
    throw error;
  }
}

/**
 * 计算下次同步时间
 */
function calculateNextSyncTime(interval) {
  return new Date(Date.now() + interval).toISOString();
}

/**
 * 处理来自其他脚本的消息
 */
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('收到消息:', request.action, 'from', sender.id || 'popup');

  switch (request.action) {
    case 'getStatus':
      handleGetStatus(sendResponse);
      return true;

    case 'manualSync':
      handleManualSync(request, sendResponse);
      return true;

    case 'updateConfig':
      handleUpdateConfig(request, sendResponse);
      return true;

    case 'getConfig':
      handleGetConfig(sendResponse);
      return true;

    case 'contentScriptReady':
      handleContentScriptReady(request, sender);
      return false;

    default:
      console.warn('未知消息类型:', request.action);
      return false;
  }
});

/**
 * 获取状态
 */
async function handleGetStatus(sendResponse) {
  try {
    // 获取后端状态
    const backendStatus = await getBackendStatus();

    sendResponse({
      success: true,
      syncStatus,
      config,
      backendStatus,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    sendResponse({
      success: false,
      error: error.message,
      syncStatus,
      config
    });
  }
}

/**
 * 手动同步
 */
async function handleManualSync(request, sendResponse) {
  const { source } = request;

  if (source === 'all') {
    // 同步所有启用的数据源
    const results = {};
    for (const src of config.enabledSources) {
      results[src] = await performSync(src, 'manual');
    }
    sendResponse({ success: true, results });
  } else {
    // 同步指定数据源
    const result = await performSync(source, 'manual');
    sendResponse(result);
  }
}

/**
 * 更新配置
 */
async function handleUpdateConfig(request, sendResponse) {
  try {
    const newConfig = { ...config, ...request.config };
    await chrome.storage.sync.set(newConfig);
    config = newConfig;

    // 重新设置定时器
    await setupAlarms();

    console.log('配置已更新:', config);
    sendResponse({ success: true, config });
  } catch (error) {
    console.error('配置更新失败:', error);
    sendResponse({ success: false, error: error.message });
  }
}

/**
 * 获取配置
 */
function handleGetConfig(sendResponse) {
  sendResponse({ success: true, config, dataSources: DATA_SOURCES });
}

/**
 * Content Script 就绪通知
 */
function handleContentScriptReady(request, sender) {
  console.log(`Content Script 就绪: ${request.url} (标签页 ${sender.tab?.id})`);
}

/**
 * 获取后端状态
 */
async function getBackendStatus() {
  if (!config.backendUrl) {
    return { available: false, error: '后端 URL 未配置' };
  }

  try {
    const response = await fetch(`${config.backendUrl}/api/sync/status`, {
      method: 'GET',
      headers: {
        ...(config.apiKey && { 'X-API-Key': config.apiKey })
      },
      signal: AbortSignal.timeout(10000) // 10秒超时
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    return { available: true, data };

  } catch (error) {
    return { available: false, error: error.message };
  }
}

// 启动初始化
initialize();
