/**
 * content_script.js — AI店长 Chrome Extension
 * 完美客服助手：建议模式 / 半自动模式 / 全自动模式
 * 支持采纳/编辑/忽略反馈，回复对比追踪
 */
(function () {
  'use strict';

  /* ═══════════════════ State ═══════════════════ */
  let enabled = true;
  let mode = 'suggest'; // 'suggest' | 'auto-fill' | 'auto-send'
  let recentReplies = []; // { id, text, time, sessionId, messageId, status, editedText }
  const processedMessages = new Set();
  let pendingSuggestions = 0; // unread count for suggest mode badge
  let lastAISuggestion = null; // for reply comparison tracking

  /* ═══════════════════ Session ID Management ═══════════════════ */
  // 确保每个页面会话有稳定的 session_id，避免 DOM fallback 时丢失上下文
  let _pageSessionId = null;

  function getOrCreateSessionId(extractedId) {
    // 优先用从 WS/DOM 提取到的真实 session_id
    if (extractedId && extractedId !== '') return extractedId;
    // 否则用页面级持久化的 session_id（同一个客服对话页面保持一致）
    if (!_pageSessionId) {
      // 尝试从 URL 提取会话标识
      const urlMatch = location.href.match(/(?:session|conversation|chat)[_-]?(?:id)?[=\/]([a-zA-Z0-9_-]+)/i);
      if (urlMatch) {
        _pageSessionId = `ext-${urlMatch[1]}`;
      } else {
        // 用 tab + URL 生成稳定 ID（同一页面刷新后恢复）
        _pageSessionId = `ext-${hashCode(location.origin + location.pathname)}-${Date.now().toString(36)}`;
      }
      // 持久化到 sessionStorage（页面刷新后恢复，tab 关闭后清除）
      try {
        const stored = sessionStorage.getItem('__aidz_session_id__');
        if (stored) {
          _pageSessionId = stored;
        } else {
          sessionStorage.setItem('__aidz_session_id__', _pageSessionId);
        }
      } catch (_) {}
    }
    return _pageSessionId;
  }

  function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  }

  /* ═══════════════════ Inject ═══════════════════ */
  function injectScript() {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  }
  injectScript();

  /* ═══════════════════ WS Listener ═══════════════════ */
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
    // 辅助：从各种字段名提取 session/conversation ID
    function pickSessionId(...candidates) {
      for (const c of candidates) {
        if (c && typeof c === 'string' && c.trim() !== '') return c;
      }
      return ''; // 空字符串 → getOrCreateSessionId 会兜底
    }

    // Pattern 1: top-level message
    if (data.type === 'message' && data.direction === 'in') {
      return {
        id: data.msgId || data.id || `${Date.now()}`,
        text: data.content || data.text || data.body,
        sessionId: getOrCreateSessionId(pickSessionId(
          data.sessionId, data.conversationId, data.session_id, data.conversation_id, data.chatId, data.chat_id
        )),
        customerInfo: data.customer || data.sender || {},
      };
    }
    // Pattern 2: nested
    const inner = data.data || data.body || {};
    if (inner.msgType !== undefined && inner.fromCustomer !== false) {
      return {
        id: inner.msgId || inner.id || `${Date.now()}`,
        text: inner.content || inner.text || '',
        sessionId: getOrCreateSessionId(pickSessionId(
          inner.sessionId, inner.conversationId, inner.session_id, inner.conversation_id, inner.chatId, inner.chat_id
        )),
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
          sessionId: getOrCreateSessionId(pickSessionId(
            payload.sessionId, payload.conversationId, payload.session_id, payload.conversation_id, payload.chatId, payload.chat_id
          )),
          customerInfo: payload.customer || {},
        };
      }
    }
    return null;
  }

  /* ═══════════════════ DOM Observer (fallback) ═══════════════════ */
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
                sendToBackend({ id: `dom-${Date.now()}`, text, sessionId: getOrCreateSessionId(''), customerInfo: {} });
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observe();
  }
  startDOMObserver();

  /* ═══════════════════ Send-message Observer (reply comparison) ═══════════════════ */
  function startSendObserver() {
    // Watch for outgoing messages in DOM to compare with AI suggestion
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

    function observeSent() {
      const container = findContainer();
      if (!container) { setTimeout(observeSent, 3000); return; }

      new MutationObserver((mutations) => {
        if (mode === 'auto-send') return; // no comparison needed in auto-send
        for (const mutation of mutations) {
          for (const node of mutation.addedNodes) {
            if (node.nodeType !== Node.ELEMENT_NODE) continue;
            // Look for outgoing (agent/merchant) messages
            const bubble = node.matches?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]')
              ? node : node.querySelector?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]');
            if (bubble) {
              const textEl = bubble.querySelector('[class*="text"], [class*="content"], p, span');
              const actualText = textEl?.textContent?.trim();
              if (actualText && lastAISuggestion) {
                trackReplyComparison(lastAISuggestion, actualText);
                lastAISuggestion = null;
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observeSent();
  }
  startSendObserver();

  function trackReplyComparison(suggestion, actual) {
    if (suggestion.text === actual) return; // identical, no need to track
    console.log('[AI店长] 回复对比 — AI建议 vs 实际发送', { ai: suggestion.text, actual });
    sendFeedback({
      session_id: suggestion.sessionId || '',
      message_id: suggestion.messageId || '',
      feedback: 'neutral',
      action: 'edited',
      original_reply: suggestion.text,
      edited_reply: '',
      actual_reply: actual,
    });
  }

  /* ═══════════════════ Backend Communication ═══════════════════ */
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
          console.error('[AI店长] 连接后台失败:', chrome.runtime.lastError.message);
          updatePanel('error', '连接后台失败');
          return;
        }
        if (response?.success && response.reply) {
          handleAIReply(response.reply, msg.sessionId, msg.id);
        } else {
          updatePanel('error', response?.error || '未知错误');
        }
      }
    );
  }

  function sendFeedback(data) {
    chrome.runtime.sendMessage({ type: 'SEND_FEEDBACK', payload: data }, (resp) => {
      if (chrome.runtime.lastError) {
        console.error('[AI店长] 反馈发送失败:', chrome.runtime.lastError.message);
      } else if (resp?.success) {
        console.log('[AI店长] 反馈已记录');
      }
    });
    // Update local stats
    updateFeedbackStats(data.action, data.feedback);
  }

  function updateFeedbackStats(action, feedback) {
    chrome.storage.sync.get(['feedbackStats'], (result) => {
      const stats = result.feedbackStats || { adopted: 0, edited: 0, ignored: 0, good: 0, bad: 0, total: 0 };
      if (action) stats[action] = (stats[action] || 0) + 1;
      if (feedback === 'good') stats.good = (stats.good || 0) + 1;
      if (feedback === 'bad') stats.bad = (stats.bad || 0) + 1;
      stats.total = (stats.total || 0) + 1;
      chrome.storage.sync.set({ feedbackStats: stats });
    });
  }

  /* ═══════════════════ AI Reply Handler ═══════════════════ */
  function handleAIReply(reply, sessionId, messageId) {
    const replyObj = {
      id: `reply-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      text: reply,
      time: new Date().toLocaleTimeString(),
      sessionId: sessionId || '',
      messageId: messageId || '',
      status: 'pending', // pending | adopted | edited | ignored
      editedText: '',
    };

    recentReplies.unshift(replyObj);
    if (recentReplies.length > 20) recentReplies.pop();

    // Store for reply comparison
    lastAISuggestion = { text: reply, sessionId, messageId };

    if (mode === 'suggest') {
      // Suggest mode: just show in panel, highlight
      pendingSuggestions++;
      updatePanel('connected', `新建议: "${reply.slice(0, 40)}..."`);
      renderReplies();
      expandPanel();
      flashPanel();
    } else if (mode === 'auto-fill') {
      // Auto-fill: fill input but don't send
      updatePanel('connected', `已填充: "${reply.slice(0, 40)}..."`);
      renderReplies();
      fillReplyInput(reply);
    } else if (mode === 'auto-send') {
      // Auto-send: fill and send
      updatePanel('connected', `已发送: "${reply.slice(0, 40)}..."`);
      replyObj.status = 'adopted';
      renderReplies();
      fillReplyInput(reply);
      setTimeout(() => clickSendButton(), 300);
      // Auto-feedback for auto-send
      sendFeedback({
        session_id: sessionId || '',
        message_id: messageId || '',
        feedback: 'good',
        action: 'adopted',
        original_reply: reply,
        edited_reply: '',
        actual_reply: reply,
      });
    }
  }

  /* ═══════════════════ Input / Send ═══════════════════ */
  function fillReplyInput(text) {
    const SELECTORS = [
      'textarea[class*="input"]', 'div[contenteditable="true"]',
      'textarea[class*="reply"]', '.chat-input textarea', 'textarea',
    ];
    for (const sel of SELECTORS) {
      const el = document.querySelector(sel);
      if (!el) continue;
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        if (setter) setter.call(el, text);
        else el.value = text;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        el.focus();
        el.innerHTML = '';
        document.execCommand('insertText', false, text);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      el.focus();
      return true;
    }
    return false;
  }

  function clickSendButton() {
    const SELECTORS = [
      'button[class*="send"]', '[class*="send-btn"]', '[class*="sendBtn"]',
      '.chat-input button', 'button[type="submit"]',
    ];
    for (const sel of SELECTORS) {
      try {
        const btn = document.querySelector(sel);
        if (btn) { btn.click(); return true; }
      } catch (_) {}
    }
    const textarea = document.querySelector('textarea, [contenteditable="true"]');
    if (textarea) {
      textarea.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true,
      }));
      return true;
    }
    return false;
  }

  /* ═══════════════════ Panel UI ═══════════════════ */
  let panel = null;
  let isMinimized = false;

  function createPanel() {
    panel = document.createElement('div');
    panel.id = 'ai-dianzhang-panel';

    panel.innerHTML = `
      <div class="aidz-header">
        <span class="aidz-title">🤖 AI客服助手</span>
        <span class="aidz-badge" id="aidz-mode-badge">建议</span>
        <span class="aidz-status" id="aidz-status">●</span>
        <button class="aidz-minimize" id="aidz-minimize" title="最小化/展开">─</button>
      </div>
      <div class="aidz-body" id="aidz-body">
        <div class="aidz-controls">
          <label class="aidz-toggle">
            <input type="checkbox" id="aidz-enabled" checked>
            <span>启用</span>
          </label>
          <select id="aidz-mode">
            <option value="suggest">💡 建议模式</option>
            <option value="auto-fill">✏️ 半自动模式</option>
            <option value="auto-send">🚀 全自动模式</option>
          </select>
        </div>
        <div class="aidz-info" id="aidz-info">就绪 — 等待客户消息</div>
        <div class="aidz-replies" id="aidz-replies">
          <div class="aidz-empty">暂无 AI 建议</div>
        </div>
      </div>
    `;
    document.body.appendChild(panel);

    /* — Drag — */
    let isDragging = false, startX, startY, origX, origY;
    const header = panel.querySelector('.aidz-header');
    header.addEventListener('mousedown', (e) => {
      if (e.target.closest('button') || e.target.closest('select')) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = panel.getBoundingClientRect();
      origX = rect.left;
      origY = rect.top;
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      panel.style.right = 'auto';
      panel.style.left = (origX + e.clientX - startX) + 'px';
      panel.style.top = (origY + e.clientY - startY) + 'px';
    });
    document.addEventListener('mouseup', () => { isDragging = false; });

    /* — Controls — */
    document.getElementById('aidz-enabled').addEventListener('change', (e) => {
      enabled = e.target.checked;
      chrome.storage.sync.set({ enabled });
      updatePanel(enabled ? 'connected' : 'disabled', enabled ? '已启用' : '已禁用');
    });

    document.getElementById('aidz-mode').addEventListener('change', (e) => {
      mode = e.target.value;
      chrome.storage.sync.set({ mode });
      updateModeBadge();
      updatePanelModeStyle();
    });

    document.getElementById('aidz-minimize').addEventListener('click', () => {
      isMinimized = !isMinimized;
      const body = document.getElementById('aidz-body');
      const btn = document.getElementById('aidz-minimize');
      if (isMinimized) {
        body.style.display = 'none';
        btn.textContent = '□';
        panel.classList.add('aidz-minimized');
      } else {
        body.style.display = 'block';
        btn.textContent = '─';
        panel.classList.remove('aidz-minimized');
        pendingSuggestions = 0;
        updateNotifyBadge();
      }
    });

    /* — Load saved state — */
    chrome.storage.sync.get(['enabled', 'mode'], (s) => {
      if (s.enabled === false) {
        enabled = false;
        document.getElementById('aidz-enabled').checked = false;
        updatePanel('disabled', '已禁用');
      }
      if (s.mode && ['suggest', 'auto-fill', 'auto-send'].includes(s.mode)) {
        mode = s.mode;
        document.getElementById('aidz-mode').value = mode;
      }
      updateModeBadge();
      updatePanelModeStyle();
    });
  }

  function updateModeBadge() {
    const badge = document.getElementById('aidz-mode-badge');
    if (!badge) return;
    const labels = { suggest: '建议', 'auto-fill': '半自动', 'auto-send': '全自动' };
    badge.textContent = labels[mode] || mode;
  }

  function updatePanelModeStyle() {
    if (!panel) return;
    if (mode === 'suggest') {
      panel.classList.add('aidz-suggest-mode');
    } else {
      panel.classList.remove('aidz-suggest-mode');
    }
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
    if (statusEl) statusEl.style.color = colors[status] || '#4caf50';
    if (message && infoEl) infoEl.textContent = message;
  }

  function updateNotifyBadge() {
    let badge = panel.querySelector('.aidz-notify-badge');
    if (pendingSuggestions > 0 && isMinimized) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'aidz-notify-badge';
        panel.style.position = 'fixed'; // ensure relative for badge
        panel.appendChild(badge);
      }
      badge.textContent = pendingSuggestions > 9 ? '9+' : pendingSuggestions;
    } else if (badge) {
      badge.remove();
    }
  }

  function expandPanel() {
    if (isMinimized) {
      // Don't auto-expand, but show badge
      updateNotifyBadge();
    }
  }

  function flashPanel() {
    if (!panel) return;
    panel.style.transition = 'box-shadow 0.3s';
    panel.style.boxShadow = '0 0 20px rgba(255, 149, 0, 0.6)';
    setTimeout(() => {
      panel.style.boxShadow = '';
    }, 1500);
  }

  /* ═══════════════════ Render Reply Cards ═══════════════════ */
  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;

    if (recentReplies.length === 0) {
      container.innerHTML = '<div class="aidz-empty">暂无 AI 建议</div>';
      return;
    }

    container.innerHTML = recentReplies.slice(0, 10).map((r) => {
      const statusClass = r.status === 'adopted' ? 'aidz-adopted'
        : r.status === 'ignored' ? 'aidz-ignored' : '';
      const isActioned = r.status !== 'pending';

      return `
        <div class="aidz-reply-card ${statusClass}" data-reply-id="${r.id}">
          <div class="aidz-reply-content">${escapeHtml(r.editedText || r.text)}</div>
          <div class="aidz-reply-meta">
            <span>⏱ ${r.time}</span>
            ${r.status !== 'pending' ? `<span style="color: ${r.status === 'adopted' ? '#4caf50' : r.status === 'edited' ? '#1976d2' : '#999'}">● ${statusLabel(r.status)}</span>` : ''}
          </div>
          <div class="aidz-reply-actions">
            <button class="aidz-action-btn aidz-btn-adopt ${isActioned ? 'aidz-btn-disabled' : ''}"
                    data-action="adopt" data-id="${r.id}" ${isActioned ? 'disabled' : ''}>✅ 采纳</button>
            <button class="aidz-action-btn aidz-btn-edit ${isActioned ? 'aidz-btn-disabled' : ''}"
                    data-action="edit" data-id="${r.id}" ${isActioned ? 'disabled' : ''}>✏️ 编辑</button>
            <button class="aidz-action-btn aidz-btn-ignore ${isActioned ? 'aidz-btn-disabled' : ''}"
                    data-action="ignore" data-id="${r.id}" ${isActioned ? 'disabled' : ''}>❌ 忽略</button>
            <span class="aidz-action-spacer"></span>
            <button class="aidz-action-btn aidz-btn-feedback aidz-fb-good"
                    data-action="feedback-good" data-id="${r.id}" title="好评">👍</button>
            <button class="aidz-action-btn aidz-btn-feedback aidz-fb-bad"
                    data-action="feedback-bad" data-id="${r.id}" title="差评">👎</button>
          </div>
          <div class="aidz-edit-area" id="edit-area-${r.id}">
            <textarea class="aidz-edit-textarea" id="edit-text-${r.id}">${escapeHtml(r.text)}</textarea>
            <div class="aidz-edit-actions">
              <button class="aidz-edit-btn cancel" data-action="edit-cancel" data-id="${r.id}">取消</button>
              <button class="aidz-edit-btn confirm" data-action="edit-confirm" data-id="${r.id}">使用修改版</button>
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Bind events via delegation
    container.onclick = handleReplyAction;
  }

  function handleReplyAction(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const reply = recentReplies.find((r) => r.id === id);
    if (!reply) return;

    switch (action) {
      case 'adopt':
        adoptReply(reply);
        break;
      case 'edit':
        toggleEditArea(reply);
        break;
      case 'ignore':
        ignoreReply(reply);
        break;
      case 'feedback-good':
        sendReplyFeedback(reply, 'good', btn);
        break;
      case 'feedback-bad':
        sendReplyFeedback(reply, 'bad', btn);
        break;
      case 'edit-cancel':
        closeEditArea(reply);
        break;
      case 'edit-confirm':
        confirmEdit(reply);
        break;
    }
  }

  function adoptReply(reply) {
    reply.status = 'adopted';
    const text = reply.editedText || reply.text;

    if (mode === 'suggest' || mode === 'auto-fill') {
      fillReplyInput(text);
    }
    if (mode === 'auto-send' || mode === 'suggest') {
      // In suggest mode, adopt = fill; user sends manually
      // Actually in suggest mode, let's just fill. In auto-send we also send.
    }
    if (mode === 'auto-send') {
      setTimeout(() => clickSendButton(), 300);
    }

    pendingSuggestions = Math.max(0, pendingSuggestions - 1);
    renderReplies();

    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'good',
      action: 'adopted',
      original_reply: reply.text,
      edited_reply: reply.editedText || '',
      actual_reply: text,
    });
  }

  function toggleEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) {
      area.classList.toggle('active');
      if (area.classList.contains('active')) {
        const textarea = document.getElementById(`edit-text-${reply.id}`);
        if (textarea) textarea.focus();
      }
    }
  }

  function closeEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) area.classList.remove('active');
  }

  function confirmEdit(reply) {
    const textarea = document.getElementById(`edit-text-${reply.id}`);
    if (!textarea) return;
    const editedText = textarea.value.trim();
    if (!editedText) return;

    reply.editedText = editedText;
    reply.status = 'edited';

    fillReplyInput(editedText);
    if (mode === 'auto-send') {
      setTimeout(() => clickSendButton(), 300);
    }

    pendingSuggestions = Math.max(0, pendingSuggestions - 1);
    renderReplies();

    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'good',
      action: 'edited',
      original_reply: reply.text,
      edited_reply: editedText,
      actual_reply: editedText,
    });
  }

  function ignoreReply(reply) {
    reply.status = 'ignored';
    pendingSuggestions = Math.max(0, pendingSuggestions - 1);
    renderReplies();

    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'bad',
      action: 'ignored',
      original_reply: reply.text,
      edited_reply: '',
      actual_reply: '',
    });
  }

  function sendReplyFeedback(reply, type, btn) {
    // Visual feedback
    btn.classList.add('active');
    btn.disabled = true;

    // Disable the other feedback button
    const card = btn.closest('.aidz-reply-card');
    if (card) {
      const otherType = type === 'good' ? 'bad' : 'good';
      const otherBtn = card.querySelector(`[data-action="feedback-${otherType}"]`);
      if (otherBtn) {
        otherBtn.disabled = true;
        otherBtn.classList.add('aidz-btn-disabled');
      }
    }

    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: type,
      action: reply.status === 'pending' ? '' : reply.status,
      original_reply: reply.text,
      edited_reply: reply.editedText || '',
      actual_reply: '',
    });
  }

  function statusLabel(status) {
    const labels = { adopted: '已采纳', edited: '已编辑', ignored: '已忽略' };
    return labels[status] || status;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* ═══════════════════ Init ═══════════════════ */
  createPanel();
  console.log('[AI店长] 客服助手已加载 — 支持建议/半自动/全自动模式');
})();
