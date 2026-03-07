/** popup.js — AI店长 Extension Popup */

const DEFAULT_SYNC_API = 'http://192.144.227.205:8000';

function showStatus(id, msg, isError = false, ms = 2500) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'status' + (isError ? ' error' : '');
  if (ms > 0) setTimeout(() => { el.textContent = ''; el.className = 'status'; }, ms);
}

// ─── 标签页切换 ──────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'sync') refreshSyncStats();
    if (tab.dataset.tab === 'debug') refreshLogs();
  });
});

// ─── 连接状态 ────────────────────────────────────────────────────────
function setConnDot(ok) {
  const dot = document.getElementById('connDot');
  const label = document.getElementById('connStatus');
  if (ok === null) {
    dot.className = 'conn-dot conn-unknown';
    label.textContent = '未检测';
  } else if (ok) {
    dot.className = 'conn-dot conn-ok';
    label.textContent = '已连接';
  } else {
    dot.className = 'conn-dot conn-err';
    label.textContent = '连接失败';
  }
}

// ─── 同步统计 ─────────────────────────────────────────────────────────
function refreshSyncStats() {
  chrome.runtime.sendMessage({ type: 'GET_SYNC_STATS' }, (resp) => {
    if (chrome.runtime.lastError || !resp) return;
    const { stats = {}, errors = {}, lastSentAt = {} } = resp;
    const container = document.getElementById('syncStatsList');
    const types = new Set([...Object.keys(stats), ...Object.keys(errors)]);

    if (types.size === 0) {
      container.innerHTML = '<div style="color:#aaa;font-size:12px;text-align:center;padding:8px">尚无同步记录<br>打开美团页面浏览数据即可自动捕获</div>';
      return;
    }

    const typeLabels = {
      orders: '订单', products: '商品', reviews: '评价',
      metrics: '销售统计', inventory: '库存', refunds: '退款',
      channels: '渠道', merchant: '门店信息',
    };

    container.innerHTML = [...types].map((t) => {
      const label = typeLabels[t] || t;
      const ok = stats[t] || 0;
      const err = errors[t] || 0;
      const lastTime = lastSentAt[t] ? new Date(lastSentAt[t]).toLocaleTimeString() : '—';
      return `<div class="stat-row">
        <span class="stat-name">${label}</span>
        <span>
          <span class="stat-ok">+${ok} 条</span>
          ${err > 0 ? `<span class="stat-err"> ${err}错</span>` : ''}
          <span style="color:#bbb;font-size:10px;margin-left:4px">${lastTime}</span>
        </span>
      </div>`;
    }).join('');
  });
}

// ─── 调试日志 ─────────────────────────────────────────────────────────
function refreshLogs() {
  chrome.storage.local.get(['debugLogs'], (data) => {
    const logs = data.debugLogs || [];
    const box = document.getElementById('logBox');
    if (logs.length === 0) {
      box.innerHTML = '<div style="color:#555">暂无日志，打开美团商家页面后会自动出现</div>';
      return;
    }
    box.innerHTML = logs.map((entry) => {
      const cls = entry.level === 'error' ? 'log-error'
        : entry.level === 'success' ? 'log-success' : 'log-info';
      return `<div class="log-entry">
        <span class="log-time">${entry.time}</span>
        <span class="${cls}">${entry.msg}</span>
        ${entry.detail ? `<span style="color:#555"> ${entry.detail.slice(0, 40)}</span>` : ''}
      </div>`;
    }).join('');
    box.scrollTop = 0;
  });
}

document.getElementById('clearLogs').addEventListener('click', () => {
  chrome.storage.local.set({ debugLogs: [] }, () => refreshLogs());
});

// ─── 连接测试 ─────────────────────────────────────────────────────────
document.getElementById('testConn').addEventListener('click', () => {
  showStatus('testConnStatus', '测试中...', false, 0);
  chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
    if (chrome.runtime.lastError) {
      showStatus('testConnStatus', '插件错误: ' + chrome.runtime.lastError.message, true);
      setConnDot(false);
      return;
    }
    if (result.success) {
      showStatus('testConnStatus', `✅ 连接成功 (${result.url})`);
      setConnDot(true);
    } else {
      showStatus('testConnStatus', `❌ ${result.error || '连接失败'}`, true);
      setConnDot(false);
    }
    setTimeout(refreshLogs, 500);
  });
});

// ─── 数据同步设置 ─────────────────────────────────────────────────────
chrome.storage.sync.get(['syncApiBase', 'tenantId'], (settings) => {
  document.getElementById('syncApiBase').value = settings.syncApiBase || DEFAULT_SYNC_API;
  document.getElementById('tenantId').value = settings.tenantId || 'default';
});

document.getElementById('saveSyncSettings').addEventListener('click', () => {
  const syncApiBase = document.getElementById('syncApiBase').value.trim() || DEFAULT_SYNC_API;
  const tenantId = document.getElementById('tenantId').value.trim() || 'default';

  chrome.storage.sync.set({ syncApiBase, tenantId }, () => {
    showStatus('syncSaveStatus', '保存成功，测试连接中...', false, 0);
    chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
      if (result?.success) {
        showStatus('syncSaveStatus', '✅ 已保存，服务器连接正常');
        setConnDot(true);
      } else {
        showStatus('syncSaveStatus', `⚠️ 已保存，但连接失败: ${result?.error || ''}`, true);
        setConnDot(false);
      }
      setTimeout(refreshLogs, 500);
    });
  });
});

document.getElementById('forceSync').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'FORCE_SYNC' }, () => {
    showStatus('forceSyncStatus', '✅ 已清除节流，下次浏览数据将立即同步');
  });
});

// ─── 客服设置 Tab ─────────────────────────────────────────────────────
chrome.storage.sync.get(['enabled', 'mode', 'apiUrl', 'apiKey', 'storeId'], (settings) => {
  document.getElementById('enabled').checked = settings.enabled !== false;
  document.getElementById('mode').value = settings.mode || 'auto-fill';
  document.getElementById('apiUrl').value = settings.apiUrl || '';
  document.getElementById('storeId').value = settings.storeId || '';
});

document.getElementById('save').addEventListener('click', () => {
  const data = {
    enabled: document.getElementById('enabled').checked,
    mode: document.getElementById('mode').value,
    apiUrl: document.getElementById('apiUrl').value.trim(),
    storeId: document.getElementById('storeId').value.trim(),
  };
  chrome.storage.sync.set(data, () => {
    showStatus('csStatus', '✅ 已保存');
    // 通知所有美团页面更新设置
    chrome.tabs.query({ url: ['https://yiyao.meituan.com/*', 'https://qnh.meituan.com/*'] }, (tabs) => {
      tabs.forEach((tab) => {
        chrome.tabs.sendMessage(tab.id, { type: 'SETTINGS_UPDATED' }).catch(() => {});
      });
    });
  });
});

// ─── 启动时测试连接 + 刷新统计 ──────────────────────────────────────
refreshSyncStats();
chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
  setConnDot(result?.success ?? null);
});
