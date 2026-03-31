/** popup.js — AI店长 Extension Popup v2 */

const DEFAULT_API_BASE = 'http://192.144.227.205:8000';
const LEGACY_API_BASES = new Set([
  'https://ai-shopkeeper-kk.fly.dev',
  'https://ai-shopkeeper-kk.fly.dev/',
]);

const MODE_DESCRIPTIONS = {
  suggest: 'AI 生成建议显示在面板，客服手动决定是否使用',
  'auto-fill': 'AI 生成建议自动填充到输入框，客服检查后手动发送',
  'auto-send': 'AI 生成建议自动填充并自动发送（全自动）',
};

/* ═══════════════════ Utils ═══════════════════ */
function showStatus(id, msg, isError = false, ms = 2500) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'status' + (isError ? ' error' : '');
  if (ms > 0) {
    setTimeout(() => { el.textContent = ''; el.className = 'status'; }, ms);
  }
}

function normalizeBaseUrl(baseUrl) {
  const raw = (baseUrl || '').trim();
  if (!raw || LEGACY_API_BASES.has(raw)) return DEFAULT_API_BASE;
  return raw.replace(/\/+$/, '');
}

function normalizeApiUrl(apiUrl, baseUrl, allowEmpty = false) {
  const raw = (apiUrl || '').trim();
  if (!raw) return allowEmpty ? '' : `${baseUrl}/api/customer-service/chat`;
  if (raw.startsWith('https://ai-shopkeeper-kk.fly.dev')) {
    return raw.replace('https://ai-shopkeeper-kk.fly.dev', baseUrl);
  }
  return raw;
}

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

/* ═══════════════════ Tabs ═══════════════════ */
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'debug') refreshLogs();
    if (tab.dataset.tab === 'stats') refreshStats();
    if (tab.dataset.tab === 'reviews') refreshReviewStatus();
    if (tab.dataset.tab === 'listing') refreshListingImports();
  });
});

/* ═══════════════════ Mode Description ═══════════════════ */
function updateModeDesc() {
  const mode = document.getElementById('mode').value;
  const desc = document.getElementById('modeDesc');
  if (desc) desc.textContent = MODE_DESCRIPTIONS[mode] || '';
}

document.getElementById('mode').addEventListener('change', updateModeDesc);

/* ═══════════════════ Logs ═══════════════════ */
function refreshLogs() {
  chrome.storage.local.get(['debugLogs'], (data) => {
    const logs = data.debugLogs || [];
    const box = document.getElementById('logBox');
    if (logs.length === 0) {
      box.innerHTML = '<div style="color:#555">暂无日志，触发客服消息后会显示</div>';
      return;
    }
    box.innerHTML = logs.map((entry) => {
      const cls = entry.level === 'error' ? 'log-error' : entry.level === 'success' ? 'log-success' : 'log-info';
      return `<div class="log-entry">
        <span class="log-time">${entry.time}</span>
        <span class="${cls}">${entry.msg}</span>
        ${entry.detail ? `<span style="color:#555"> ${entry.detail.slice(0, 80)}</span>` : ''}
      </div>`;
    }).join('');
    box.scrollTop = 0;
  });
}

document.getElementById('clearLogs').addEventListener('click', () => {
  chrome.storage.local.set({ debugLogs: [] }, () => refreshLogs());
});

/* ═══════════════════ Feedback Stats ═══════════════════ */
function refreshStats() {
  chrome.storage.sync.get(['feedbackStats'], (result) => {
    const s = result.feedbackStats || { adopted: 0, edited: 0, ignored: 0, good: 0, bad: 0, total: 0 };

    document.getElementById('statTotal').textContent = s.total || 0;
    document.getElementById('statAdopted').textContent = s.adopted || 0;
    document.getElementById('statEdited').textContent = s.edited || 0;
    document.getElementById('statIgnored').textContent = s.ignored || 0;
    document.getElementById('statGood').textContent = s.good || 0;
    document.getElementById('statBad').textContent = s.bad || 0;

    // Calculate rates
    const actionTotal = (s.adopted || 0) + (s.edited || 0) + (s.ignored || 0);
    if (actionTotal > 0) {
      const adoptPct = ((s.adopted || 0) / actionTotal * 100).toFixed(0);
      const editPct = ((s.edited || 0) / actionTotal * 100).toFixed(0);
      const ignorePct = ((s.ignored || 0) / actionTotal * 100).toFixed(0);

      document.getElementById('statAdoptRate').textContent = adoptPct + '%';
      document.getElementById('statEditRate').textContent = editPct + '%';
      document.getElementById('statIgnoreRate').textContent = ignorePct + '%';

      // Update bar
      const bar = document.getElementById('statBar');
      const segs = bar.querySelectorAll('.stat-bar-seg');
      segs[0].style.width = adoptPct + '%';
      segs[1].style.width = editPct + '%';
      segs[2].style.width = ignorePct + '%';
    } else {
      document.getElementById('statAdoptRate').textContent = '0%';
      document.getElementById('statEditRate').textContent = '0%';
      document.getElementById('statIgnoreRate').textContent = '0%';
    }
  });
}

document.getElementById('resetStats').addEventListener('click', () => {
  chrome.storage.sync.set({
    feedbackStats: { adopted: 0, edited: 0, ignored: 0, good: 0, bad: 0, total: 0 },
  }, () => {
    refreshStats();
    showStatus('csStatus', '统计已重置');
  });
});

/* ═══════════════════ Load Settings ═══════════════════ */
chrome.storage.sync.get(['enabled', 'mode', 'apiUrl', 'apiKey', 'storeId', 'chatApiBase'], (settings) => {
  const chatApiBase = normalizeBaseUrl(settings.chatApiBase);
  const normalizedApiUrl = normalizeApiUrl(settings.apiUrl, chatApiBase, true);
  const defaultApiUrl = `${chatApiBase}/api/customer-service/chat`;
  const apiUrl = normalizedApiUrl === defaultApiUrl ? '' : normalizedApiUrl;

  if ((settings.chatApiBase || '') !== chatApiBase || ((settings.apiUrl || '').trim()) !== apiUrl) {
    chrome.storage.sync.set({ chatApiBase, apiUrl });
  }

  document.getElementById('enabled').checked = settings.enabled !== false;
  const modeVal = settings.mode || 'suggest';
  document.getElementById('mode').value = ['suggest', 'auto-fill', 'auto-send'].includes(modeVal) ? modeVal : 'suggest';
  document.getElementById('apiUrl').value = apiUrl;
  document.getElementById('chatApiBase').value = chatApiBase;
  document.getElementById('storeId').value = settings.storeId || '';
  updateModeDesc();
});

/* ═══════════════════ Save Settings ═══════════════════ */
document.getElementById('save').addEventListener('click', () => {
  const chatApiBase = normalizeBaseUrl(document.getElementById('chatApiBase').value);
  const apiUrl = normalizeApiUrl(document.getElementById('apiUrl').value, chatApiBase, true);
  const data = {
    enabled: document.getElementById('enabled').checked,
    mode: document.getElementById('mode').value,
    apiUrl,
    chatApiBase,
    storeId: document.getElementById('storeId').value.trim(),
  };
  chrome.storage.sync.set(data, () => {
    document.getElementById('apiUrl').value = apiUrl;
    document.getElementById('chatApiBase').value = chatApiBase;
    showStatus('csStatus', '✅ 已保存');
  });
});

/* ═══════════════════ Test Connection ═══════════════════ */
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
    setTimeout(refreshLogs, 300);
  });
});

/* ═══════════════════ Review Sync Status ═══════════════════ */
function refreshReviewStatus() {
  chrome.storage.local.get(['reviewSyncStatus'], (data) => {
    const s = data.reviewSyncStatus;
    const dot = document.getElementById('reviewDot');
    const statusText = document.getElementById('reviewStatusText');
    const lastSync = document.getElementById('reviewLastSync');
    const lastCount = document.getElementById('reviewLastCount');
    if (!s) {
      if (dot) dot.style.background = '#aaa';
      if (statusText) statusText.textContent = '未同步';
      if (lastSync) lastSync.textContent = '—';
      if (lastCount) lastCount.textContent = '—';
      return;
    }
    const ok = s.ok !== false;
    if (dot) dot.style.background = ok ? '#4caf50' : '#e53935';
    if (statusText) statusText.textContent = ok ? '已同步' : '同步失败';
    if (lastSync) lastSync.textContent = s.lastSyncAt ? new Date(s.lastSyncAt).toLocaleString() : '—';
    if (lastCount) lastCount.textContent = s.lastCount != null ? `${s.lastCount} 条评价` : '—';
  });
}

const reviewRefreshBtn = document.getElementById('reviewRefresh');
if (reviewRefreshBtn) {
  reviewRefreshBtn.addEventListener('click', () => {
    refreshReviewStatus();
    showStatus('reviewStatus', '已刷新');
  });
}

/* ═══════════════════ Init ═══════════════════ */
refreshLogs();
refreshStats();
refreshReviewStatus();
chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
  setConnDot(result?.success ?? null);
});

/* ═══════════════════ Listing Import Records ═══════════════════ */
function refreshListingImports() {
  chrome.storage.local.get(['listingImports'], (data) => {
    const records = data.listingImports || [];
    const container = document.getElementById('listingRecords');
    if (!container) return;

    if (records.length === 0) {
      container.innerHTML = '<div class="listing-empty">暂无导入记录<br>在 1688 或拼多多商品页点击「导入AI店长」按钮</div>';
      return;
    }

    container.innerHTML = records.map((rec, idx) => {
      const platform = rec.platform === 'pdd' ? '拼多多' : '1688';
      const platformCls = rec.platform === 'pdd' ? 'pdd' : 'alibaba';
      const statusLabel = rec.status === 'completed' ? '已完成' : rec.status === 'failed' ? '失败' : '处理中';
      const statusCls = rec.status === 'completed' ? 'completed' : rec.status === 'failed' ? 'failed' : 'pending';
      const timeStr = rec.time ? new Date(rec.time).toLocaleString() : '—';
      return `
        <div class="listing-record" data-idx="${idx}" data-url="${encodeURIComponent(rec.url || '')}">
          <div class="listing-record-title">${escapeHtmlPopup(rec.title || '未知商品')}</div>
          <div class="listing-record-meta">
            <span class="listing-badge ${platformCls}">${platform}</span>
            <span class="listing-badge ${statusCls}">${statusLabel}</span>
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${timeStr}</span>
          </div>
        </div>
      `;
    }).join('');

    // 点击跳转到对应商品原页面
    container.querySelectorAll('.listing-record').forEach((el) => {
      el.addEventListener('click', () => {
        const url = decodeURIComponent(el.dataset.url || '');
        if (url) chrome.tabs.create({ url });
      });
    });
  });
}

function escapeHtmlPopup(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

const clearImportsBtn = document.getElementById('clearImports');
if (clearImportsBtn) {
  clearImportsBtn.addEventListener('click', () => {
    chrome.storage.local.set({ listingImports: [] }, () => refreshListingImports());
  });
}
