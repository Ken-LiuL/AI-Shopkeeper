/**
 * Popup 界面逻辑
 */

document.addEventListener('DOMContentLoaded', async function() {
  console.log('Popup 已加载');

  // 绑定事件监听器
  bindEventListeners();

  // 初始化界面
  await initializeUI();
});

/**
 * 绑定事件监听器
 */
function bindEventListeners() {
  // 保存配置
  document.getElementById('saveConfig').addEventListener('click', saveConfig);

  // 切换 API Key 显示
  document.getElementById('toggleApiKey').addEventListener('click', toggleApiKeyVisibility);

  // 同步所有数据
  document.getElementById('syncAll').addEventListener('click', syncAllData);

  // 测试连接
  document.getElementById('testConnection').addEventListener('click', testConnection);

  // 打开高级设置
  document.getElementById('openOptions').addEventListener('click', openOptions);

  // 关闭消息提示
  document.querySelector('.toast-close').addEventListener('click', hideToast);

  // 配置字段变化时自动保存
  ['backendUrl', 'apiKey'].forEach(id => {
    const element = document.getElementById(id);
    element.addEventListener('blur', autoSaveConfig);
    element.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        autoSaveConfig();
      }
    });
  });
}

/**
 * 初始化界面
 */
async function initializeUI() {
  try {
    showLoading('加载配置...');

    // 获取配置和状态
    const [configResult, statusResult] = await Promise.all([
      sendMessage({ action: 'getConfig' }),
      sendMessage({ action: 'getStatus' })
    ]);

    // 填充配置
    if (configResult.success) {
      populateConfig(configResult.config);
    }

    // 更新状态
    if (statusResult.success) {
      updateConnectionStatus(statusResult.backendStatus);
      updateSourcesGrid(statusResult.syncStatus, configResult.dataSources);
      updateRecentLogs(statusResult.syncStatus);
    }

    hideLoading();
  } catch (error) {
    console.error('初始化失败:', error);
    hideLoading();
    showToast('初始化失败: ' + error.message, 'error');
  }
}

/**
 * 填充配置字段
 */
function populateConfig(config) {
  document.getElementById('backendUrl').value = config.backendUrl || '';
  document.getElementById('apiKey').value = config.apiKey || '';
}

/**
 * 更新连接状态指示器
 */
function updateConnectionStatus(backendStatus) {
  const indicator = document.getElementById('connectionStatus');
  const dot = indicator.querySelector('.dot');
  const text = indicator.querySelector('.text');

  // 清除现有样式
  indicator.className = 'status-indicator';

  if (backendStatus.available) {
    indicator.classList.add('connected');
    text.textContent = '已连接';
  } else {
    indicator.classList.add('error');
    text.textContent = backendStatus.error || '连接失败';
  }
}

/**
 * 更新数据源网格
 */
function updateSourcesGrid(syncStatus, dataSources) {
  const grid = document.getElementById('sourcesGrid');
  grid.innerHTML = '';

  Object.entries(dataSources || {}).forEach(([source, config]) => {
    const status = syncStatus[source] || {};
    const card = createSourceCard(source, config, status);
    grid.appendChild(card);
  });
}

/**
 * 创建数据源卡片
 */
function createSourceCard(source, config, status) {
  const card = document.createElement('div');
  card.className = `source-card status-${status.status || 'unknown'}`;

  const statusText = getStatusText(status);
  const lastSyncText = getLastSyncText(status);

  card.innerHTML = `
    <div class="source-info">
      <div class="source-name">${config.description || source}</div>
      <div class="source-meta">${statusText} · ${lastSyncText}</div>
    </div>
    <div class="source-actions">
      <button type="button" class="btn btn-secondary btn-small" onclick="syncSingleSource('${source}')">
        同步
      </button>
    </div>
  `;

  return card;
}

/**
 * 获取状态文本
 */
function getStatusText(status) {
  switch (status.status) {
    case 'success':
      return `✅ 成功 (${status.lastCount || 0} 条)`;
    case 'error':
      return '❌ 失败';
    case 'running':
      return '⏳ 同步中';
    default:
      return '⚪ 未同步';
  }
}

/**
 * 获取最后同步时间文本
 */
function getLastSyncText(status) {
  if (status.lastSuccess) {
    return formatRelativeTime(status.lastSuccess);
  } else if (status.lastAttempt) {
    return formatRelativeTime(status.lastAttempt) + ' (失败)';
  } else {
    return '从未同步';
  }
}

/**
 * 格式化相对时间
 */
function formatRelativeTime(isoString) {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now - date;

  const minutes = Math.floor(diff / (1000 * 60));
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (minutes < 1) {
    return '刚刚';
  } else if (minutes < 60) {
    return `${minutes} 分钟前`;
  } else if (hours < 24) {
    return `${hours} 小时前`;
  } else {
    return `${days} 天前`;
  }
}

/**
 * 更新最近同步记录
 */
function updateRecentLogs(syncStatus) {
  const logsContainer = document.getElementById('recentLogs');

  // 获取所有同步记录并按时间排序
  const logs = [];
  Object.entries(syncStatus).forEach(([source, status]) => {
    if (status.lastAttempt) {
      logs.push({
        source,
        time: status.lastAttempt,
        success: status.status === 'success',
        count: status.lastCount || 0,
        error: status.error
      });
    }
  });

  logs.sort((a, b) => new Date(b.time) - new Date(a.time));

  if (logs.length === 0) {
    logsContainer.innerHTML = '<div class="log-item placeholder">暂无同步记录</div>';
    return;
  }

  logsContainer.innerHTML = logs.slice(0, 5).map(log => `
    <div class="log-item">
      <div class="log-time">${formatRelativeTime(log.time)}</div>
      <div class="log-status ${log.success ? 'success' : 'error'}">
        ${log.source}: ${log.success ? `成功 (${log.count} 条)` : `失败 - ${log.error}`}
      </div>
    </div>
  `).join('');
}

/**
 * 保存配置
 */
async function saveConfig() {
  try {
    const config = {
      backendUrl: document.getElementById('backendUrl').value.trim(),
      apiKey: document.getElementById('apiKey').value.trim()
    };

    // 验证 URL 格式
    if (config.backendUrl && !isValidUrl(config.backendUrl)) {
      throw new Error('无效的后端 URL 格式');
    }

    showLoading('保存配置...');

    const result = await sendMessage({
      action: 'updateConfig',
      config
    });

    if (result.success) {
      showToast('配置已保存', 'success');
      // 重新检查连接状态
      await refreshStatus();
    } else {
      throw new Error(result.error || '保存失败');
    }

    hideLoading();
  } catch (error) {
    console.error('保存配置失败:', error);
    hideLoading();
    showToast('保存失败: ' + error.message, 'error');
  }
}

/**
 * 自动保存配置
 */
async function autoSaveConfig() {
  // 防抖处理
  clearTimeout(autoSaveConfig.timer);
  autoSaveConfig.timer = setTimeout(saveConfig, 1000);
}

/**
 * 切换 API Key 显示
 */
function toggleApiKeyVisibility() {
  const input = document.getElementById('apiKey');
  const button = document.getElementById('toggleApiKey');

  if (input.type === 'password') {
    input.type = 'text';
    button.textContent = '🙈';
  } else {
    input.type = 'password';
    button.textContent = '👁️';
  }
}

/**
 * 同步所有数据
 */
async function syncAllData() {
  try {
    const button = document.getElementById('syncAll');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<span class="icon">⏳</span>同步中...';

    const result = await sendMessage({
      action: 'manualSync',
      source: 'all'
    });

    if (result.success) {
      const successCount = Object.values(result.results).filter(r => r.success).length;
      const totalCount = Object.keys(result.results).length;
      showToast(`同步完成: ${successCount}/${totalCount} 成功`, 'success');

      // 刷新状态
      await refreshStatus();
    } else {
      throw new Error(result.error || '同步失败');
    }

    button.disabled = false;
    button.innerHTML = originalText;
  } catch (error) {
    console.error('同步失败:', error);
    showToast('同步失败: ' + error.message, 'error');

    const button = document.getElementById('syncAll');
    button.disabled = false;
    button.innerHTML = '<span class="icon">🔄</span>同步所有数据';
  }
}

/**
 * 同步单个数据源
 */
window.syncSingleSource = async function(source) {
  try {
    showLoading(`同步 ${source}...`);

    const result = await sendMessage({
      action: 'manualSync',
      source
    });

    if (result.success) {
      showToast(`${source} 同步成功: ${result.count} 条记录`, 'success');
      await refreshStatus();
    } else {
      throw new Error(result.error || '同步失败');
    }

    hideLoading();
  } catch (error) {
    console.error(`${source} 同步失败:`, error);
    hideLoading();
    showToast(`${source} 同步失败: ${error.message}`, 'error');
  }
};

/**
 * 测试连接
 */
async function testConnection() {
  try {
    const button = document.getElementById('testConnection');
    const originalText = button.innerHTML;

    button.disabled = true;
    button.innerHTML = '<span class="icon">⏳</span>测试中...';

    // 获取最新状态
    const result = await sendMessage({ action: 'getStatus' });

    if (result.success) {
      updateConnectionStatus(result.backendStatus);

      if (result.backendStatus.available) {
        showToast('连接测试成功', 'success');
      } else {
        showToast('连接测试失败: ' + (result.backendStatus.error || '未知错误'), 'error');
      }
    } else {
      throw new Error(result.error || '测试失败');
    }

    button.disabled = false;
    button.innerHTML = originalText;
  } catch (error) {
    console.error('测试连接失败:', error);
    showToast('测试失败: ' + error.message, 'error');

    const button = document.getElementById('testConnection');
    button.disabled = false;
    button.innerHTML = '<span class="icon">🔗</span>测试连接';
  }
}

/**
 * 打开高级设置
 */
function openOptions() {
  chrome.runtime.openOptionsPage();
}

/**
 * 刷新状态
 */
async function refreshStatus() {
  try {
    const result = await sendMessage({ action: 'getStatus' });

    if (result.success) {
      updateConnectionStatus(result.backendStatus);
      updateSourcesGrid(result.syncStatus, result.dataSources);
      updateRecentLogs(result.syncStatus);
    }
  } catch (error) {
    console.error('刷新状态失败:', error);
  }
}

/**
 * 发送消息到 background script
 */
function sendMessage(message, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('消息发送超时'));
    }, timeout);

    chrome.runtime.sendMessage(message, (response) => {
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
 * 显示加载状态
 */
function showLoading(text = '处理中...') {
  const overlay = document.getElementById('loadingOverlay');
  const loadingText = overlay.querySelector('.loading-text');

  loadingText.textContent = text;
  overlay.classList.add('show');
}

/**
 * 隐藏加载状态
 */
function hideLoading() {
  const overlay = document.getElementById('loadingOverlay');
  overlay.classList.remove('show');
}

/**
 * 显示消息提示
 */
function showToast(message, type = 'success') {
  const toast = document.getElementById('toast');
  const messageEl = toast.querySelector('.toast-message');

  // 清除现有样式
  toast.className = 'toast';

  // 设置消息和样式
  messageEl.textContent = message;
  toast.classList.add('show');

  if (type === 'error') {
    toast.classList.add('error');
  } else if (type === 'warning') {
    toast.classList.add('warning');
  }

  // 自动隐藏
  setTimeout(() => {
    hideToast();
  }, type === 'error' ? 5000 : 3000);
}

/**
 * 隐藏消息提示
 */
function hideToast() {
  const toast = document.getElementById('toast');
  toast.classList.remove('show');
}

/**
 * 验证 URL 格式
 */
function isValidUrl(string) {
  try {
    const url = new URL(string);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch (_) {
    return false;
  }
}
