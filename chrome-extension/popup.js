/** popup.js — AI店长 Extension Popup */

const DEFAULT_API_BASE = 'https://ai-shopkeeper-kk.fly.dev';

function showStatus(id, msg, isError = false, ms = 2500) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'status' + (isError ? ' error' : '');
  if (ms > 0) {
    setTimeout(() => {
      el.textContent = '';
      el.className = 'status';
    }, ms);
  }
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
    if (tab.dataset.tab === 'debug') refreshLogs();
  });
});

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

chrome.storage.sync.get(['enabled', 'mode', 'apiUrl', 'apiKey', 'storeId', 'chatApiBase'], (settings) => {
  document.getElementById('enabled').checked = settings.enabled !== false;
  document.getElementById('mode').value = settings.mode || 'auto-fill';
  document.getElementById('apiUrl').value = settings.apiUrl || '';
  document.getElementById('chatApiBase').value = settings.chatApiBase || DEFAULT_API_BASE;
  document.getElementById('storeId').value = settings.storeId || '';
});

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

refreshLogs();
chrome.runtime.sendMessage({ type: 'TEST_CONNECTION' }, (result) => {
  setConnDot(result?.success ?? null);
});
