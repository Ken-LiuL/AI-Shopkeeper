/**
 * Options 页面逻辑
 */

let currentConfig = {};
let dataSources = {};

document.addEventListener('DOMContentLoaded', async function() {
  console.log('Options 页面已加载');

  // 绑定事件监听器
  bindEventListeners();

  // 初始化界面
  await initializeUI();

  // 定期刷新状态
  setInterval(refreshStatus, 30000); // 每30秒刷新
});

/**
 * 绑定事件监听器
 */
function bindEventListeners() {
  // 保存配置
  document.getElementById('saveBasicConfig').addEventListener('click', saveBasicConfig);
  document.getElementById('saveDataSourceConfig').addEventListener('click', saveDataSourceConfig);

  // 状态操作
  document.getElementById('refreshStatus').addEventListener('click', refreshStatus);
  document.getElementById('clearLogs').addEventListener('click', clearLogs);

  // 高级选项
  document.getElementById('resetConfig').addEventListener('click', resetConfig);
  document.getElementById('exportConfig').addEventListener('click', exportConfig);
  document.getElementById('importConfig').addEventListener('click', () => {
    document.getElementById('importFile').click();
  });
  document.getElementById('importFile').addEventListener('change', importConfig);

  // 关闭消息提示
  document.querySelector('.toast-close').addEventListener('click', hideToast);
}

/**
 * 初始化界面
 */
async function initializeUI() {
  try {
    // 获取配置和状态
    const [configResult, statusResult] = await Promise.all([
      sendMessage({ action: 'getConfig' }),
      sendMessage({ action: 'getStatus' })
    ]);

    if (configResult.success) {
      currentConfig = configResult.config;
      dataSources = configResult.dataSources || {};

      populateBasicConfig(currentConfig);
      populateDataSourcesGrid(dataSources);
    }

    if (statusResult.success) {
      updateConnectionStatus(statusResult.backendStatus);
      updateStatusTable(statusResult.syncStatus);
    }

    // 加载日志
    await loadLogs();

  } catch (error) {
    console.error('初始化失败:', error);
    showToast('初始化失败: ' + error.message, 'error');
  }
}

/**
 * 填充基本配置
 */
function populateBasicConfig(config) {
  document.getElementById('backendUrl').value = config.backendUrl || '';
  document.getElementById('apiKey').value = config.apiKey || '';
  document.getElementById('retryAttempts').value = config.retryAttempts || 3;
  document.getElementById('retryDelay').value = config.retryDelay || 5;
  document.getElementById('batchSize').value = config.batchSize || 50;
  document.getElementById('maxConcurrent').value = config.maxConcurrent || 3;
}

/**
 * 生成数据源配置网格
 */
function populateDataSourcesGrid(sources) {
  const grid = document.getElementById('dataSourcesGrid');
  grid.innerHTML = '';

  Object.entries(sources).forEach(([source, config]) => {
    const sourceDiv = document.createElement('div');
    sourceDiv.className = 'source-config';

    const intervalMinutes = Math.floor(config.interval / (1000 * 60));
    const isEnabled = currentConfig.enabledSources?.includes(source) ?? config.enabled;

    sourceDiv.innerHTML = `
      <h4>${config.description || source}</h4>
      <div>
        <label class="switch">
          <input type="checkbox" id="enable-${source}" ${isEnabled ? 'checked' : ''}>
          <span class="slider"></span>
        </label>
        <span>启用同步</span>
      </div>
      <div class="interval-input">
        <label for="interval-${source}">间隔:</label>
        <input type="number" id="interval-${source}" min="1" max="1440" value="${intervalMinutes}">
        <span>分钟</span>
      </div>
      <div style="margin-top: 8px; font-size: 12px; color: #6c757d;">
        优先级: ${config.priority}
      </div>
    `;

    grid.appendChild(sourceDiv);
  });
}

/**
 * 更新连接状态
 */
function updateConnectionStatus(backendStatus) {
  const indicator = document.getElementById('connectionStatus');
  const dot = indicator.querySelector('.dot');
  const text = indicator.querySelector('.text');

  // 清除现有样式
  indicator.className = 'status-indicator';

  if (backendStatus.available) {
    indicator.classList.add('connected');
    text.textContent = '后端已连接';
  } else {
    indicator.classList.add('error');
    text.textContent = backendStatus.error || '后端连接失败';
  }
}

/**
 * 更新状态表格
 */
function updateStatusTable(syncStatus) {
  const container = document.getElementById('statusTable');

  if (!syncStatus || Object.keys(syncStatus).length === 0) {
    container.innerHTML = '<p style="color: #6c757d; font-style: italic;">暂无同步状态数据</p>';
    return;
  }

  const table = document.createElement('table');
  table.style.width = '100%';
  table.style.borderCollapse = 'collapse';

  table.innerHTML = `
    <thead>
      <tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;">
        <th style="padding: 12px; text-align: left;">数据源</th>
        <th style="padding: 12px; text-align: left;">状态</th>
        <th style="padding: 12px; text-align: left;">最后同步</th>
        <th style="padding: 12px; text-align: left;">记录数</th>
        <th style="padding: 12px; text-align: left;">下次同步</th>
        <th style="padding: 12px; text-align: left;">错误信息</th>
      </tr>
    </thead>
    <tbody>
      ${Object.entries(syncStatus).map(([source, status]) => {
        const statusClass = status.status === 'success' ? 'success' :
                           status.status === 'error' ? 'error' :
                           status.status === 'running' ? 'warning' : '';

        return `
          <tr style="border-bottom: 1px solid #dee2e6;">
            <td style="padding: 8px; font-weight: 500;">${dataSources[source]?.description || source}</td>
            <td style="padding: 8px;">
              <span class="log-status ${statusClass}">${getStatusText(status)}</span>
            </td>
            <td style="padding: 8px; font-size: 12px;">
              ${status.lastSuccess ? formatDateTime(status.lastSuccess) : '从未成功'}
            </td>
            <td style="padding: 8px;">${status.lastCount || 0}</td>
            <td style="padding: 8px; font-size: 12px;">
              ${status.nextSync ? formatDateTime(status.nextSync) : '-'}
            </td>
            <td style="padding: 8px; font-size: 12px; color: #dc3545;">
              ${status.error || '-'}
            </td>
          </tr>
        `;
      }).join('')}
    </tbody>
  `;

  container.innerHTML = '';
  container.appendChild(table);
}

/**
 * 获取状态文本
 */
function getStatusText(status) {
  switch (status.status) {
    case 'success':
      return '✅ 成功';
    case 'error':
      return '❌ 失败';
    case 'running':
      return '⏳ 运行中';
    default:
      return '⚪ 未运行';
  }
}

/**
 * 格式化日期时间
 */
function formatDateTime(isoString) {
  const date = new Date(isoString);
  return date.toLocaleString('zh-CN');
}

/**
 * 加载日志
 */
async function loadLogs() {
  const container = document.getElementById('logsContainer');

  try {
    // 从本地存储获取日志
    const result = await chrome.storage.local.get('syncLogs');
    const logs = result.syncLogs || [];

    if (logs.length === 0) {
      container.innerHTML = '<div class="log-entry">暂无同步日志</div>';
      return;
    }

    // 显示最近的 100 条日志
    const recentLogs = logs.slice(-100).reverse();

    container.innerHTML = recentLogs.map(log => {
      const logClass = log.level || 'info';
      return `<div class="log-entry ${logClass}">[${formatDateTime(log.timestamp)}] ${log.message}</div>`;
    }).join('');

  } catch (error) {
    console.error('加载日志失败:', error);
    container.innerHTML = '<div class="log-entry error">日志加载失败: ' + error.message + '</div>';
  }
}

/**
 * 保存基本配置
 */
async function saveBasicConfig() {
  try {
    const config = {
      backendUrl: document.getElementById('backendUrl').value.trim(),
      apiKey: document.getElementById('apiKey').value.trim(),
      retryAttempts: parseInt(document.getElementById('retryAttempts').value) || 3,
      retryDelay: parseInt(document.getElementById('retryDelay').value) || 5,
      batchSize: parseInt(document.getElementById('batchSize').value) || 50,
      maxConcurrent: parseInt(document.getElementById('maxConcurrent').value) || 3
    };

    // 验证配置
    if (config.backendUrl && !isValidUrl(config.backendUrl)) {
      throw new Error('无效的后端 URL 格式');
    }

    const result = await sendMessage({
      action: 'updateConfig',
      config: { ...currentConfig, ...config }
    });

    if (result.success) {
      currentConfig = { ...currentConfig, ...config };
      showToast('基本配置已保存', 'success');
    } else {
      throw new Error(result.error || '保存失败');
    }

  } catch (error) {
    console.error('保存基本配置失败:', error);
    showToast('保存失败: ' + error.message, 'error');
  }
}

/**
 * 保存数据源配置
 */
async function saveDataSourceConfig() {
  try {
    const enabledSources = [];
    const sourceIntervals = {};

    Object.keys(dataSources).forEach(source => {
      const enableCheckbox = document.getElementById(`enable-${source}`);
      const intervalInput = document.getElementById(`interval-${source}`);

      if (enableCheckbox && enableCheckbox.checked) {
        enabledSources.push(source);
      }

      if (intervalInput) {
        const minutes = parseInt(intervalInput.value) || 60;
        sourceIntervals[source] = minutes * 60 * 1000; // 转换为毫秒
      }
    });

    const config = {
      ...currentConfig,
      enabledSources,
      sourceIntervals
    };

    const result = await sendMessage({
      action: 'updateConfig',
      config
    });

    if (result.success) {
      currentConfig = config;
      showToast('数据源配置已保存', 'success');
    } else {
      throw new Error(result.error || '保存失败');
    }

  } catch (error) {
    console.error('保存数据源配置失败:', error);
    showToast('保存失败: ' + error.message, 'error');
  }
}

/**
 * 刷新状态
 */
async function refreshStatus() {
  try {
    const result = await sendMessage({ action: 'getStatus' });

    if (result.success) {
      updateConnectionStatus(result.backendStatus);
      updateStatusTable(result.syncStatus);
      showToast('状态已刷新', 'success');
    } else {
      throw new Error(result.error || '刷新失败');
    }

  } catch (error) {
    console.error('刷新状态失败:', error);
    showToast('刷新失败: ' + error.message, 'error');
  }
}

/**
 * 清除日志
 */
async function clearLogs() {
  try {
    if (!confirm('确定要清除所有同步日志吗？此操作不可撤销。')) {
      return;
    }

    await chrome.storage.local.remove('syncLogs');

    const container = document.getElementById('logsContainer');
    container.innerHTML = '<div class="log-entry">日志已清除</div>';

    showToast('日志已清除', 'success');

  } catch (error) {
    console.error('清除日志失败:', error);
    showToast('清除失败: ' + error.message, 'error');
  }
}

/**
 * 重置配置
 */
async function resetConfig() {
  try {
    if (!confirm('确定要重置所有配置吗？此操作不可撤销。')) {
      return;
    }

    // 清除存储的配置
    await chrome.storage.sync.clear();
    await chrome.storage.local.clear();

    // 重新加载页面
    location.reload();

  } catch (error) {
    console.error('重置配置失败:', error);
    showToast('重置失败: ' + error.message, 'error');
  }
}

/**
 * 导出配置
 */
async function exportConfig() {
  try {
    const allData = {
      sync: await chrome.storage.sync.get(),
      local: await chrome.storage.local.get()
    };

    const blob = new Blob([JSON.stringify(allData, null, 2)], {
      type: 'application/json'
    });

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ai-store-manager-config-${new Date().getTime()}.json`;
    a.click();

    URL.revokeObjectURL(url);
    showToast('配置已导出', 'success');

  } catch (error) {
    console.error('导出配置失败:', error);
    showToast('导出失败: ' + error.message, 'error');
  }
}

/**
 * 导入配置
 */
async function importConfig(event) {
  try {
    const file = event.target.files[0];
    if (!file) return;

    const text = await file.text();
    const data = JSON.parse(text);

    if (!data.sync && !data.local) {
      throw new Error('无效的配置文件格式');
    }

    if (!confirm('确定要导入配置吗？这将覆盖当前所有配置。')) {
      return;
    }

    // 导入配置
    if (data.sync) {
      await chrome.storage.sync.clear();
      await chrome.storage.sync.set(data.sync);
    }

    if (data.local) {
      await chrome.storage.local.clear();
      await chrome.storage.local.set(data.local);
    }

    // 重新加载页面
    location.reload();

  } catch (error) {
    console.error('导入配置失败:', error);
    showToast('导入失败: ' + error.message, 'error');
  } finally {
    // 重置文件输入
    event.target.value = '';
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
