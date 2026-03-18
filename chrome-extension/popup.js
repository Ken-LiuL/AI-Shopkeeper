/** popup.js — AI店长 Extension Popup v2 */

const DEFAULT_API_BASE = 'http://192.144.227.205:8000';

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
  document.getElementById('enabled').checked = settings.enabled !== false;
  const modeVal = settings.mode || 'suggest';
  document.getElementById('mode').value = ['suggest', 'auto-fill', 'auto-send'].includes(modeVal) ? modeVal : 'suggest';
  document.getElementById('apiUrl').value = settings.apiUrl || '';
  document.getElementById('chatApiBase').value = settings.chatApiBase || DEFAULT_API_BASE;
  document.getElementById('storeId').value = settings.storeId || '';
  updateModeDesc();
});

/* ═══════════════════ Save Settings ═══════════════════ */
document.getElementById('save').addEventListener('click', () => {
  const data = {
    enabled: document.getElementById('enabled').checked,
    mode: document.getElementById('mode').value,
    apiUrl: document.getElementById('apiUrl').value.trim(),
    chatApiBase: document.getElementById('chatApiBase').value.trim() || DEFAULT_API_BASE,
    storeId: document.getElementById('storeId').value.trim(),
  };
  chrome.storage.sync.set(data, () => {
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

/* ═══════════════════ Init ═══════════════════ */
refreshLogs();
refreshStats();
chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
  setConnDot(result?.success ?? null);
});
