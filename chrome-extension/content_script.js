/**
 * content_script.js — 扩展上下文，运行在 yiyao.meituan.com
 * 功能：AI 客服助手 — 拦截客户消息，生成 AI 回复，自动填充
 */
(function () {
  'use strict';

  let enabled = true;
  let mode = 'auto-fill'; // 'auto-fill' | 'auto-send'
  let recentReplies = [];
  const processedMessages = new Set();

  // 注入页面脚本
  function injectScript() {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  }
  injectScript();

  // 监听 WebSocket 消息
  window.addEventListener('__AI_DIANZHANG_WS__', (e) => {
    if (!enabled) return;
    try {
      const data = JSON.parse(e.detail);
      handleWSMessage(data);
    } catch (_) {}
  });

  function handleWSMessage(data) {
    const msg = extractCustomerMessage(data);
    if (msg && !processedMessages.has(msg.id)) {
      processedMessages.add(msg.id);
      if (processedMessages.size > 500) {
        const first = processedMessages.values().next().value;
        processedMessages.delete(first);
      }
      sendToBackend(msg);
    }
  }

  function extractCustomerMessage(data) {
    // Pattern 1: top-level message
    if (data.type === 'message' && data.direction === 'in') {
      return {
        id: data.msgId || data.id || `${Date.now()}`,
        text: data.content || data.text || data.body,
        sessionId: data.sessionId || data.conversationId || '',
        customerInfo: data.customer || data.sender || {},
      };
    }
    // Pattern 2: nested
    const inner = data.data || data.body || {};
    if (inner.msgType !== undefined && inner.fromCustomer !== false) {
      return {
        id: inner.msgId || inner.id || `${Date.now()}`,
        text: inner.content || inner.text || '',
        sessionId: inner.sessionId || inner.conversationId || '',
        customerInfo: inner.customer || inner.sender || {},
      };
    }
    // Pattern 3: chat command
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

  // DOM MutationObserver fallback — 观察聊天消息容器
  function startDOMObserver() {
    const CONTAINER_SELECTORS = [
      '.chat-message-list', '.message-list', '[class*="messageList"]',
      '[class*="chat-content"]', '.im-message-list',
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
      if (!container) { setTimeout(observe, 3000); return; }

      new MutationObserver((mutations) => {
        if (!enabled) return;
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            const bubble = node.matches?.('[class*="customer"], [class*="receive"], [class*="left"]')
              ? node : node.querySelector?.('[class*="customer"], [class*="receive"], [class*="left"]');
            if (bubble) {
              const textEl = bubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text && !processedMessages.has(text)) {
                processedMessages.add(text);
                sendToBackend({ id: `dom-${Date.now()}`, text, sessionId: '', customerInfo: {} });
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observe();
  }
  startDOMObserver();

  // 发送到后台获取 AI 回复
  function sendToBackend(msg) {
    if (!msg.text) return;
    updatePanel('thinking', `处理中: "${msg.text.slice(0, 30)}..."`);
    chrome.runtime.sendMessage(
      { type: 'CUSTOMER_MESSAGE', payload: { message: msg.text, session_id: msg.sessionId, customer_info: msg.customerInfo } },
      (response) => {
        if (chrome.runtime.lastError) { updatePanel('error', '连接后台失败'); return; }
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
    if (mode === 'auto-fill' || mode === 'auto-send') fillReplyInput(reply);
    if (mode === 'auto-send') setTimeout(() => clickSendButton(), 300);
  }

  // 填充回复输入框
  function fillReplyInput(text) {
    const SELECTORS = ['textarea[class*="input"]', 'div[contenteditable="true"]', 'textarea[class*="reply"]', '.chat-input textarea', 'textarea'];
    for (const sel of SELECTORS) {
      const el = document.querySelector(sel);
      if (!el) continue;
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        if (setter) setter.call(el, text); else el.value = text;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        el.focus(); el.innerHTML = '';
        document.execCommand('insertText', false, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      el.focus();
      return true;
    }
    return false;
  }

  function clickSendButton() {
    const SELECTORS = ['button[class*="send"]', '[class*="send-btn"]', '[class*="sendBtn"]', '.chat-input button', 'button[type="submit"]'];
    for (const sel of SELECTORS) {
      try { const btn = document.querySelector(sel); if (btn) { btn.click(); return true; } } catch (_) {}
    }
    const textarea = document.querySelector('textarea, [contenteditable="true"]');
    if (textarea) { textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true })); return true; }
    return false;
  }

  // 悬浮面板
  let panel = null;
  function createPanel() {
    panel = document.createElement('div');
    panel.id = 'ai-dianzhang-panel';
    panel.innerHTML = `
      <div class="aidz-header">
        <span class="aidz-title">🤖 AI客服助手</span>
        <span class="aidz-status" id="aidz-status">●</span>
        <button class="aidz-minimize" id="aidz-minimize">─</button>
      </div>
      <div class="aidz-body" id="aidz-body">
        <div class="aidz-controls">
          <label class="aidz-toggle"><input type="checkbox" id="aidz-enabled" checked><span>启用</span></label>
          <select id="aidz-mode">
            <option value="auto-fill">自动填充</option>
            <option value="auto-send">自动发送</option>
          </select>
        </div>
        <div class="aidz-info" id="aidz-info">就绪</div>
        <div class="aidz-replies" id="aidz-replies"></div>
      </div>`;
    document.body.appendChild(panel);

    // 拖拽
    let isDragging = false, startX, startY, origX, origY;
    const header = panel.querySelector('.aidz-header');
    header.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT') return;
      isDragging = true; startX = e.clientX; startY = e.clientY;
      const rect = panel.getBoundingClientRect(); origX = rect.left; origY = rect.top;
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => { if (!isDragging) return; panel.style.right = 'auto'; panel.style.left = (origX + e.clientX - startX) + 'px'; panel.style.top = (origY + e.clientY - startY) + 'px'; });
    document.addEventListener('mouseup', () => { isDragging = false; });

    document.getElementById('aidz-enabled').addEventListener('change', (e) => {
      enabled = e.target.checked;
      chrome.storage.sync.set({ enabled });
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

    chrome.storage.sync.get(['enabled', 'mode'], (s) => {
      if (s.enabled === false) {
        enabled = false;
        document.getElementById('aidz-enabled').checked = false;
        updatePanel('disabled', '已禁用');
      }
      if (s.mode) {
        mode = s.mode;
        document.getElementById('aidz-mode').value = mode;
      }
    });
  }

  function updatePanel(status, message) {
    if (!panel) return;
    const statusEl = document.getElementById('aidz-status');
    const infoEl = document.getElementById('aidz-info');
    const colors = { connected: '#4caf50', thinking: '#ff9800', error: '#f44336', disabled: '#999' };
    statusEl.style.color = colors[status] || '#4caf50';
    if (message) infoEl.textContent = message;
  }

  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;
    container.innerHTML = recentReplies.slice(0, 5).map((r) => `<div class="aidz-reply"><span class="aidz-time">${r.time}</span> ${r.text.slice(0, 80)}</div>`).join('');
  }

  createPanel();
  console.log('[AI店长] 客服助手已加载');
})();
