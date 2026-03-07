/**
 * content_script.js — Runs in the EXTENSION context on qnh.meituan.com.
 * 1. Injects the WebSocket interceptor into the page
 * 2. Listens for intercepted WS messages
 * 3. Falls back to DOM MutationObserver
 * 4. Creates the floating control panel
 * 5. Communicates with the background service worker
 */
(function () {
  'use strict';

  // ─── State ───────────────────────────────────────────────────────────
  let enabled = true;
  let mode = 'auto-fill'; // 'auto-fill' | 'auto-send'
  let recentReplies = [];
  const processedMessages = new Set();

  // ─── Inject page-level WebSocket interceptor ─────────────────────────
  function injectScript() {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  }
  injectScript();

  // ─── 监听业务数据事件（injected.js 派发） ────────────────────────────
  window.addEventListener('__AI_DIANZHANG_DATA__', (e) => {
    try {
      const payload = JSON.parse(e.detail);
      console.log('[AI店长] 捕获到数据:', payload.type, payload.url?.split('/').slice(-2).join('/'));
      chrome.runtime.sendMessage(
        { type: 'BUSINESS_DATA', payload },
        (resp) => {
          chrome.runtime.lastError; // 消耗错误
          if (resp?.success && !resp?.skipped) {
            console.log(`[AI店长] ✅ 同步成功 [${payload.type}] ${resp.count || '?'} 条`);
          } else if (resp?.skipped) {
            console.log(`[AI店长] ⏭ 节流跳过 [${payload.type}]`);
          } else if (resp?.error) {
            console.warn(`[AI店长] ❌ 同步失败 [${payload.type}]:`, resp.error);
          }
        }
      );
    } catch (_) {}
  });

  // ─── 页面加载时主动触发一次数据采集 ─────────────────────────────────
  function triggerInitialCapture() {
    // 向 injected.js 发送信号，让其立即读取页面已有数据（可选）
    // 这里通过 CustomEvent 通知 injected 侧的监听者
    window.dispatchEvent(new CustomEvent('__AI_DIANZHANG_CAPTURE__'));
  }
  setTimeout(triggerInitialCapture, 2000);

  // ─── Listen for intercepted WS messages ──────────────────────────────
  window.addEventListener('__AI_DIANZHANG_WS__', (e) => {
    if (!enabled) return;
    try {
      const data = JSON.parse(e.detail);
      handleWSMessage(data);
    } catch (_) {}
  });

  function handleWSMessage(data) {
    // 牵牛花 WS message structures vary; common patterns:
    // Look for incoming customer messages — adjust selectors as the
    // actual protocol is discovered through testing.
    const msg = extractCustomerMessage(data);
    if (msg && !processedMessages.has(msg.id)) {
      processedMessages.add(msg.id);
      // Keep set bounded
      if (processedMessages.size > 500) {
        const first = processedMessages.values().next().value;
        processedMessages.delete(first);
      }
      sendToBackend(msg);
    }
  }

  /**
   * Attempt to extract a customer message from a WS payload.
   * This is a best-effort heuristic — adjust field names after
   * inspecting real 牵牛花 WebSocket traffic.
   */
  function extractCustomerMessage(data) {
    // Pattern 1: top-level message object
    if (data.type === 'message' && data.direction === 'in') {
      return {
        id: data.msgId || data.id || `${Date.now()}`,
        text: data.content || data.text || data.body,
        sessionId: data.sessionId || data.conversationId || '',
        customerInfo: data.customer || data.sender || {},
      };
    }

    // Pattern 2: nested under data/body
    const inner = data.data || data.body || {};
    if (inner.msgType !== undefined && inner.fromCustomer !== false) {
      return {
        id: inner.msgId || inner.id || `${Date.now()}`,
        text: inner.content || inner.text || '',
        sessionId: inner.sessionId || inner.conversationId || '',
        customerInfo: inner.customer || inner.sender || {},
      };
    }

    // Pattern 3: check for common chat message indicators
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      if (payload.content && payload.role !== 'merchant' && payload.role !== 'agent') {
        return {
          id: payload.msgId || payload.id || `${Date.now()}`,
          text: payload.content,
          sessionId: payload.sessionId || payload.conversationId || '',
          customerInfo: payload.customer || {},
        };
      }
    }

    return null;
  }

  // ─── DOM MutationObserver fallback ───────────────────────────────────
  let domObserver = null;

  function startDOMObserver() {
    // Common selectors for chat message containers in 牵牛花
    const CONTAINER_SELECTORS = [
      '.chat-message-list',
      '.message-list',
      '[class*="messageList"]',
      '[class*="chat-content"]',
      '.im-message-list',
    ];

    function findContainer() {
      for (const sel of CONTAINER_SELECTORS) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    }

    function observe() {
      const container = findContainer();
      if (!container) {
        setTimeout(observe, 2000);
        return;
      }

      domObserver = new MutationObserver((mutations) => {
        if (!enabled) return;
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            // Look for customer message bubbles (not merchant/agent)
            const bubble =
              node.matches?.('[class*="customer"], [class*="receive"], [class*="left"]') ? node
              : node.querySelector?.('[class*="customer"], [class*="receive"], [class*="left"]');
            if (bubble) {
              const textEl = bubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text && !processedMessages.has(text)) {
                processedMessages.add(text);
                sendToBackend({
                  id: `dom-${Date.now()}`,
                  text,
                  sessionId: extractSessionIdFromDOM(),
                  customerInfo: {},
                });
              }
            }
          }
        }
      });

      domObserver.observe(container, { childList: true, subtree: true });
      console.log('[AI店长] DOM observer attached');
    }

    observe();
  }

  function extractSessionIdFromDOM() {
    // Try to get session/conversation ID from URL or active chat element
    const urlMatch = location.href.match(/[?&](?:session|conversation|chat)(?:Id|_id)=([^&]+)/);
    if (urlMatch) return urlMatch[1];
    const activeChat = document.querySelector('[class*="active"][class*="session"], [class*="active"][class*="conversation"]');
    return activeChat?.dataset?.id || activeChat?.getAttribute('data-session-id') || 'unknown';
  }

  startDOMObserver();

  // ─── Communication with background ───────────────────────────────────
  function sendToBackend(msg) {
    if (!msg.text) return;
    updatePanel('thinking', `处理中: "${msg.text.slice(0, 30)}..."`);

    chrome.runtime.sendMessage(
      {
        type: 'CUSTOMER_MESSAGE',
        payload: {
          message: msg.text,
          session_id: msg.sessionId,
          customer_info: msg.customerInfo,
        },
      },
      (response) => {
        if (chrome.runtime.lastError) {
          console.error('[AI店长] Background error:', chrome.runtime.lastError.message);
          updatePanel('error', '连接后台失败');
          return;
        }
        if (response?.success && response.reply) {
          handleAIReply(response.reply);
        } else {
          updatePanel('error', response?.error || '未知错误');
        }
      }
    );
  }

  function handleAIReply(reply) {
    recentReplies.unshift({ text: reply, time: new Date().toLocaleTimeString() });
    if (recentReplies.length > 10) recentReplies.pop();
    updatePanel('connected', `回复: "${reply.slice(0, 40)}..."`);
    renderReplies();

    if (mode === 'auto-fill' || mode === 'auto-send') {
      fillReplyInput(reply);
    }
    if (mode === 'auto-send') {
      setTimeout(() => clickSendButton(), 300);
    }
  }

  // ─── Input filling & sending ─────────────────────────────────────────
  function fillReplyInput(text) {
    const INPUT_SELECTORS = [
      'textarea[class*="input"]',
      'div[contenteditable="true"]',
      'textarea[class*="reply"]',
      '.chat-input textarea',
      '[class*="editor"] [contenteditable]',
      '.ql-editor',
      'textarea',
    ];

    for (const sel of INPUT_SELECTORS) {
      const el = document.querySelector(sel);
      if (!el) continue;

      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        // Use native input setter to trigger React/Vue change detection
        const nativeSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype, 'value'
        )?.set || Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value'
        )?.set;
        if (nativeSetter) {
          nativeSetter.call(el, text);
        } else {
          el.value = text;
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        // contenteditable
        el.focus();
        el.innerHTML = '';
        document.execCommand('insertText', false, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }

      el.focus();
      console.log('[AI店长] Reply filled');
      return true;
    }

    console.warn('[AI店长] Could not find input element');
    return false;
  }

  function clickSendButton() {
    const BTN_SELECTORS = [
      'button[class*="send"]',
      '[class*="send-btn"]',
      '[class*="sendBtn"]',
      'button:has(span:contains("发送"))',
      '.chat-input button',
      'button[type="submit"]',
    ];

    for (const sel of BTN_SELECTORS) {
      try {
        const btn = document.querySelector(sel);
        if (btn) {
          btn.click();
          console.log('[AI店长] Send button clicked');
          return true;
        }
      } catch (_) {}
    }

    // Fallback: press Enter in the input
    const textarea = document.querySelector('textarea, [contenteditable="true"]');
    if (textarea) {
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
      return true;
    }

    console.warn('[AI店长] Could not find send button');
    return false;
  }

  // ─── Floating Panel ──────────────────────────────────────────────────
  let panel = null;

  function createPanel() {
    panel = document.createElement('div');
    panel.id = 'ai-dianzhang-panel';
    panel.innerHTML = `
      <div class="aidz-header">
        <span class="aidz-title">🤖 AI店长</span>
        <span class="aidz-status" id="aidz-status">●</span>
        <button class="aidz-minimize" id="aidz-minimize">─</button>
      </div>
      <div class="aidz-body" id="aidz-body">
        <div class="aidz-controls">
          <label class="aidz-toggle">
            <input type="checkbox" id="aidz-enabled" checked>
            <span>启用</span>
          </label>
          <select id="aidz-mode">
            <option value="auto-fill">自动填充</option>
            <option value="auto-send">自动发送</option>
          </select>
        </div>
        <div class="aidz-info" id="aidz-info">就绪</div>
        <div class="aidz-replies" id="aidz-replies"></div>
      </div>
    `;
    document.body.appendChild(panel);

    // Make draggable
    let isDragging = false, startX, startY, origX, origY;
    const header = panel.querySelector('.aidz-header');
    header.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT') return;
      isDragging = true;
      startX = e.clientX; startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      origX = rect.left; origY = rect.top;
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      panel.style.right = 'auto';
      panel.style.left = (origX + e.clientX - startX) + 'px';
      panel.style.top = (origY + e.clientY - startY) + 'px';
    });
    document.addEventListener('mouseup', () => { isDragging = false; });

    // Controls
    document.getElementById('aidz-enabled').addEventListener('change', (e) => {
      enabled = e.target.checked;
      updatePanel(enabled ? 'connected' : 'disabled', enabled ? '已启用' : '已禁用');
    });

    document.getElementById('aidz-mode').addEventListener('change', (e) => {
      mode = e.target.value;
      chrome.storage.sync.set({ mode });
    });

    document.getElementById('aidz-minimize').addEventListener('click', () => {
      const body = document.getElementById('aidz-body');
      body.style.display = body.style.display === 'none' ? 'block' : 'none';
    });

    // Load saved settings
    chrome.storage.sync.get(['enabled', 'mode'], (settings) => {
      if (settings.enabled === false) {
        enabled = false;
        document.getElementById('aidz-enabled').checked = false;
        updatePanel('disabled', '已禁用');
      }
      if (settings.mode) {
        mode = settings.mode;
        document.getElementById('aidz-mode').value = mode;
      }
    });
  }

  function updatePanel(status, message) {
    if (!panel) return;
    const statusEl = document.getElementById('aidz-status');
    const infoEl = document.getElementById('aidz-info');

    const colors = {
      connected: '#4caf50',
      thinking: '#ff9800',
      error: '#f44336',
      disabled: '#999',
    };
    statusEl.style.color = colors[status] || '#4caf50';
    if (message) infoEl.textContent = message;
  }

  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;
    container.innerHTML = recentReplies
      .slice(0, 5)
      .map((r) => `<div class="aidz-reply"><span class="aidz-time">${r.time}</span> ${escapeHtml(r.text.slice(0, 80))}</div>`)
      .join('');
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ─── Listen for settings changes from popup ──────────────────────────
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'SETTINGS_UPDATED') {
      chrome.storage.sync.get(['enabled', 'mode'], (s) => {
        enabled = s.enabled !== false;
        mode = s.mode || 'auto-fill';
        if (panel) {
          document.getElementById('aidz-enabled').checked = enabled;
          document.getElementById('aidz-mode').value = mode;
          updatePanel(enabled ? 'connected' : 'disabled', enabled ? '已启用' : '已禁用');
        }
      });
    }
  });

  // ─── Init ────────────────────────────────────────────────────────────
  createPanel();
  console.log('[AI店长] Content script loaded');
})();
