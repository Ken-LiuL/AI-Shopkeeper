/**
 * content_script.js — Runs in extension context on yiyao.meituan.com.
 * Injects page script and forwards captured business data to background worker.
 */
(function () {
  'use strict';

  function injectScript() {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  }

  injectScript();

  window.addEventListener('__AI_DIANZHANG_DATA__', (e) => {
    try {
      const payload = JSON.parse(e.detail);
      console.log('[AI店长] 捕获业务数据:', payload.type, payload.url?.split('/').slice(-2).join('/'));
      chrome.runtime.sendMessage({ type: 'BUSINESS_DATA', payload }, (resp) => {
        chrome.runtime.lastError;
        if (resp?.success && !resp?.skipped) {
          console.log(`[AI店长] 同步成功 [${payload.type}] ${resp.count || '?'} 条`);
        } else if (resp?.skipped) {
          console.log(`[AI店长] 跳过同步 [${payload.type}] (${resp.reason || 'skipped'})`);
        } else if (resp?.error) {
          console.warn(`[AI店长] 同步失败 [${payload.type}]`, resp.error);
        }
      });
    } catch (_) {}
  });
})();
