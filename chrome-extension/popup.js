document.addEventListener('DOMContentLoaded', () => {
  const fields = ['enabled', 'mode', 'apiUrl', 'apiKey', 'storeId'];

  // Load saved settings
  chrome.storage.sync.get(fields, (settings) => {
    document.getElementById('enabled').checked = settings.enabled !== false;
    document.getElementById('mode').value = settings.mode || 'auto-fill';
    document.getElementById('apiUrl').value = settings.apiUrl || '';
    document.getElementById('apiKey').value = settings.apiKey || '';
    document.getElementById('storeId').value = settings.storeId || '';
  });

  // Save
  document.getElementById('save').addEventListener('click', () => {
    const data = {
      enabled: document.getElementById('enabled').checked,
      mode: document.getElementById('mode').value,
      apiUrl: document.getElementById('apiUrl').value.trim(),
      apiKey: document.getElementById('apiKey').value.trim(),
      storeId: document.getElementById('storeId').value.trim(),
    };

    chrome.storage.sync.set(data, () => {
      document.getElementById('status').textContent = '✅ 已保存';
      setTimeout(() => { document.getElementById('status').textContent = ''; }, 2000);

      // Notify content scripts
      chrome.tabs.query({ url: 'https://qnh.meituan.com/*' }, (tabs) => {
        tabs.forEach((tab) => {
          chrome.tabs.sendMessage(tab.id, { type: 'SETTINGS_UPDATED' }).catch(() => {});
        });
      });
    });
  });
});
