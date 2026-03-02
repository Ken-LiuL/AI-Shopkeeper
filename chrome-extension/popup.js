document.addEventListener('DOMContentLoaded', () => {
  // ─── 标签页切换 ───────────────────────────────────────────────────────
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');

      if (tab.dataset.tab === 'sync') refreshSyncStats();
    });
  });

  // ─── 客服助手 Tab ─────────────────────────────────────────────────────
  const csFields = ['enabled', 'mode', 'apiUrl', 'apiKey', 'storeId'];

  chrome.storage.sync.get(csFields, (settings) => {
    document.getElementById('enabled').checked = settings.enabled !== false;
    document.getElementById('mode').value = settings.mode || 'auto-fill';
    document.getElementById('apiUrl').value = settings.apiUrl || '';
    document.getElementById('apiKey').value = settings.apiKey || '';
    document.getElementById('storeId').value = settings.storeId || '';
  });

  document.getElementById('save').addEventListener('click', () => {
    const data = {
      enabled: document.getElementById('enabled').checked,
      mode: document.getElementById('mode').value,
      apiUrl: document.getElementById('apiUrl').value.trim(),
      apiKey: document.getElementById('apiKey').value.trim(),
      storeId: document.getElementById('storeId').value.trim(),
    };

    chrome.storage.sync.set(data, () => {
      showStatus('status', '✅ 已保存');
      chrome.tabs.query({ url: 'https://qnh.meituan.com/*' }, (tabs) => {
        tabs.forEach((tab) => {
          chrome.tabs.sendMessage(tab.id, { type: 'SETTINGS_UPDATED' }).catch(() => {});
        });
      });
    });
  });

  // ─── 数据同步 Tab ─────────────────────────────────────────────────────
  chrome.storage.sync.get(['syncApiBase', 'tenantId'], (settings) => {
    document.getElementById('syncApiBase').value = settings.syncApiBase || 'https://ai-shopkeeper-kk.fly.dev';
    document.getElementById('tenantId').value = settings.tenantId || 'default';
  });

  document.getElementById('saveSyncSettings').addEventListener('click', () => {
    const data = {
      syncApiBase: document.getElementById('syncApiBase').value.trim() || 'https://ai-shopkeeper-kk.fly.dev',
      tenantId: document.getElementById('tenantId').value.trim() || 'default',
    };
    chrome.storage.sync.set(data, () => showStatus('syncStatus', '✅ 已保存'));
  });

  document.getElementById('forceSync').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'FORCE_SYNC' }, () => {
      showStatus('syncStatus', '🔄 节流已清除，下次拦截到数据将立即同步');
    });
  });

  // ─── 刷新同步统计 ─────────────────────────────────────────────────────
  function refreshSyncStats() {
    chrome.storage.local.get(['syncStats', 'lastSentAt'], (result) => {
      const stats = result.syncStats || {};
      const sentAt = result.lastSentAt || {};
      const container = document.getElementById('syncStatusList');

      const typeLabels = {
        orders: '📦 订单',
        products: '🛍️ 商品',
        metrics: '📈 销售数据',
        channels: '📡 渠道',
        merchant: '🏪 商家信息',
        table_query: '📋 通用查询',
        complex_query: '🔍 复杂查询',
      };

      const keys = Object.keys(stats);
      if (keys.length === 0) {
        container.innerHTML = '<div class="sync-empty">尚未同步任何数据<br>请打开牵牛花后台，数据将自动同步</div>';
        return;
      }

      container.innerHTML = keys.map((type) => {
        const label = typeLabels[type] || type;
        const count = stats[type] || 0;
        const lastTs = sentAt[type];
        const lastTime = lastTs ? new Date(lastTs).toLocaleTimeString('zh-CN') : '—';
        return `
          <div class="sync-item">
            <span class="sync-item-name">${label}<span class="sync-badge">${count}</span></span>
            <span class="sync-item-val">上次: ${lastTime}</span>
          </div>
        `;
      }).join('');
    });
  }

  // ─── 工具函数 ─────────────────────────────────────────────────────────
  function showStatus(elId, msg, duration = 2500) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.textContent = msg;
    setTimeout(() => { el.textContent = ''; }, duration);
  }
});
