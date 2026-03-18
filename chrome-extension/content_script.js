/**
 * content_script.js — AI店长 Chrome Extension
 * 完美客服助手：建议模式 / 半自动模式 / 全自动模式
 * 支持多客户会话、采纳/编辑/忽略反馈、回复对比追踪、聊天记录采集
 */
(function () {
  'use strict';

  /* ═══════════════════ State ═══════════════════ */
  let enabled = true;
  let mode = 'suggest'; // 'suggest' | 'auto-fill' | 'auto-send'
  const processedMessages = new Set();
  let pendingSuggestions = 0;

  // ── 多 Session 管理 ──────────────────────────────────────────────
  // sessionReplies: { [sessionId]: [{ id, text, time, ... }] }
  const sessionReplies = {};
  // 当前活跃 session（从 WS 消息或 DOM 检测）
  let activeSessionId = null;
  // 最近一次 AI 建议（按 session）
  const lastAISuggestions = {}; // { [sessionId]: { text, messageId } }

  /* ═══════════════════ Active Session Detection ═══════════════════ */
  /**
   * 从牵牛花客服工作台 DOM 检测当前选中的客户会话。
   * 逻辑：找到左侧会话列表中高亮/选中的那个，提取用户名或 ID。
   */
  function detectActiveSession() {
    // 牵牛花工作台常见选中态 class
    const ACTIVE_SELECTORS = [
      '.session-item.active', '.session-item.selected',
      '.conversation-item.active', '.conversation-item.selected',
      '[class*="sessionItem"][class*="active"]',
      '[class*="session"][class*="selected"]',
      '[class*="chat-item"][class*="active"]',
      'li.active[class*="session"]',
      '.im-session-list .active',
    ];

    for (const sel of ACTIVE_SELECTORS) {
      const el = document.querySelector(sel);
      if (el) {
        // 从元素属性或内容提取 session 标识
        const dataId = el.dataset?.sessionId || el.dataset?.conversationId
          || el.dataset?.id || el.getAttribute('data-session-id')
          || el.getAttribute('data-conversation-id');
        if (dataId) return `mt-${dataId}`;

        // fallback: 用客户名字做 key
        const nameEl = el.querySelector('[class*="name"], [class*="nick"], [class*="title"]');
        const name = nameEl?.textContent?.trim();
        if (name) return `mt-name-${hashCode(name)}`;
      }
    }

    // 再 fallback: 从聊天窗口标题提取
    const headerSelectors = [
      '.chat-header [class*="name"]', '.im-chat-header [class*="title"]',
      '[class*="chatHeader"] [class*="userName"]',
    ];
    for (const sel of headerSelectors) {
      const el = document.querySelector(sel);
      const name = el?.textContent?.trim();
      if (name && name.length > 0 && name.length < 50) {
        return `mt-header-${hashCode(name)}`;
      }
    }

    return null;
  }

  // 定期检测活跃 session（处理用户切换客户的情况）
  setInterval(() => {
    const detected = detectActiveSession();
    if (detected && detected !== activeSessionId) {
      activeSessionId = detected;
      renderReplies(); // 切换客户时刷新面板
    }
  }, 1000);

  function getCurrentSessionId(extractedId) {
    if (extractedId && extractedId.trim() !== '') return extractedId;
    if (activeSessionId) return activeSessionId;
    // 最终 fallback
    return `ext-fallback-${hashCode(location.origin + location.pathname)}`;
  }

  function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  }

  /* ═══════════════════ Reply Management (per-session) ═══════════════════ */
  function getSessionReplies(sessionId) {
    if (!sessionReplies[sessionId]) sessionReplies[sessionId] = [];
    return sessionReplies[sessionId];
  }

  function addReply(sessionId, replyObj) {
    const replies = getSessionReplies(sessionId);
    replies.unshift(replyObj);
    if (replies.length > 20) replies.pop();
    // 清理旧 session（超过 50 个 session 时清理最老的）
    const keys = Object.keys(sessionReplies);
    if (keys.length > 50) {
      delete sessionReplies[keys[0]];
    }
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
      // 更新活跃 session
      if (msg.sessionId) activeSessionId = msg.sessionId;
      sendToBackend(msg);
    }

    // 采集客服发出的消息（用于学习）
    const agentMsg = extractAgentMessage(data);
    if (agentMsg && !processedMessages.has(agentMsg.id)) {
      processedMessages.add(agentMsg.id);
      logChatMessage(agentMsg);
    }
  }

  function extractCustomerMessage(data) {
    function pickSessionId(...candidates) {
      for (const c of candidates) {
        if (c && typeof c === 'string' && c.trim() !== '') return c;
      }
      return '';
    }

    // Pattern 1: top-level message (incoming from customer)
    if (data.type === 'message' && data.direction === 'in') {
      return {
        id: data.msgId || data.id || `${Date.now()}`,
        text: data.content || data.text || data.body,
        sessionId: getCurrentSessionId(pickSessionId(
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
        sessionId: getCurrentSessionId(pickSessionId(
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
          sessionId: getCurrentSessionId(pickSessionId(
            payload.sessionId, payload.conversationId, payload.session_id, payload.conversation_id, payload.chatId, payload.chat_id
          )),
          customerInfo: payload.customer || {},
        };
      }
    }
    return null;
  }

  /**
   * 提取客服发出的消息（direction=out 或 role=merchant/agent）
   */
  function extractAgentMessage(data) {
    function pickSessionId(...candidates) {
      for (const c of candidates) {
        if (c && typeof c === 'string' && c.trim() !== '') return c;
      }
      return '';
    }

    // Pattern 1: outgoing message
    if (data.type === 'message' && data.direction === 'out') {
      return {
        id: data.msgId || data.id || `agent-${Date.now()}`,
        text: data.content || data.text || data.body,
        sessionId: getCurrentSessionId(pickSessionId(
          data.sessionId, data.conversationId, data.session_id, data.conversation_id
        )),
        role: 'agent',
      };
    }
    // Pattern 2: nested outgoing
    const inner = data.data || data.body || {};
    if (inner.fromCustomer === false || inner.role === 'merchant' || inner.role === 'agent') {
      const text = inner.content || inner.text || '';
      if (text) {
        return {
          id: inner.msgId || inner.id || `agent-${Date.now()}`,
          text,
          sessionId: getCurrentSessionId(pickSessionId(
            inner.sessionId, inner.conversationId, inner.session_id, inner.conversation_id
          )),
          role: 'agent',
        };
      }
    }
    // Pattern 3: chat command from agent
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      if (payload.content && (payload.role === 'merchant' || payload.role === 'agent')) {
        return {
          id: payload.msgId || payload.id || `agent-${Date.now()}`,
          text: payload.content,
          sessionId: getCurrentSessionId(pickSessionId(
            payload.sessionId, payload.conversationId, payload.session_id, payload.conversation_id
          )),
          role: 'agent',
        };
      }
    }
    return null;
  }

  /* ═══════════════════ DOM Observer (fallback for customer messages) ═══════════════════ */
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

            // 客户消息（incoming）
            const customerBubble = node.matches?.('[class*="customer"], [class*="receive"], [class*="left"]')
              ? node : node.querySelector?.('[class*="customer"], [class*="receive"], [class*="left"]');
            if (customerBubble) {
              const textEl = customerBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              const sessionId = getCurrentSessionId(detectActiveSession() || '');
              if (text && !processedMessages.has(`dom-cust-${sessionId}-${text}`)) {
                processedMessages.add(`dom-cust-${sessionId}-${text}`);
                // sendToBackend 内部已调 logChatMessage，无需重复
                sendToBackend({ id: `dom-${Date.now()}`, text, sessionId, customerInfo: {} });
              }
            }

            // 客服消息（outgoing）— 用于学习采集
            const agentBubble = node.matches?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]')
              ? node : node.querySelector?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]');
            if (agentBubble) {
              const textEl = agentBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              const sessionId = getCurrentSessionId(detectActiveSession() || '');
              if (text && !processedMessages.has(`dom-agent-${sessionId}-${text}`)) {
                processedMessages.add(`dom-agent-${sessionId}-${text}`);
                logChatMessage({ id: `dom-agent-${Date.now()}`, text, sessionId, role: 'agent' });
                // 对比 AI 建议
                const suggestion = lastAISuggestions[sessionId];
                if (suggestion && suggestion.text !== text) {
                  trackReplyComparison(suggestion, text, sessionId);
                  delete lastAISuggestions[sessionId];
                }
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observe();
  }
  startDOMObserver();

  function trackReplyComparison(suggestion, actual, sessionId) {
    console.log('[AI店长] 回复对比 — AI建议 vs 实际发送', { ai: suggestion.text, actual, session: sessionId });
    sendFeedback({
      session_id: sessionId || '',
      message_id: suggestion.messageId || '',
      feedback: 'neutral',
      action: 'edited',
      original_reply: suggestion.text,
      edited_reply: '',
      actual_reply: actual,
    });
  }

  /* ═══════════════════ Chat Log Collection (聊天记录采集) ═══════════════════ */
  /**
   * 把聊天消息发到后端，用于学习和对比分析。
   * 后端接口: POST /api/customer-service/log-chat
   * 支持 agent（客服）和 customer（客户）消息。
   * 后端通过 content_hash 去重，所以 WS + DOM 双采集不会重复。
   */
  function logChatMessage(msg) {
    if (!msg.text) return;
    chrome.runtime.sendMessage({
      type: 'LOG_CHAT',
      payload: {
        session_id: msg.sessionId || '',
        message_id: msg.id || '',
        role: msg.role || 'agent',
        content: msg.text,
        timestamp: new Date().toISOString(),
      },
    });
  }

  /* ═══════════════════ Backend Communication ═══════════════════ */
  function sendToBackend(msg) {
    if (!msg.text) return;
    // 记录客户消息到 log-chat（用于完整对话采集）
    logChatMessage({ id: msg.id, text: msg.text, sessionId: msg.sessionId, role: 'customer' });
    updatePanel('thinking', `🤔 AI正在分析: "${msg.text.slice(0, 25)}..."`);
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
          updatePanel('error', '后台连接中断，请检查网络');
          return;
        }
        if (response?.success && response.reply) {
          handleAIReply(response.reply, msg.sessionId, msg.id);
        } else {
          const errMsg = response?.error || '未知错误';
          updatePanel('error', errMsg);
        }
      }
    );
  }

  function sendFeedback(data) {
    chrome.runtime.sendMessage({ type: 'SEND_FEEDBACK', payload: data }, (resp) => {
      if (chrome.runtime.lastError) {
        console.error('[AI店长] 反馈发送失败:', chrome.runtime.lastError.message);
      }
    });
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
      status: 'pending',
      editedText: '',
    };

    addReply(sessionId, replyObj);

    // 记录 AI 建议用于后续对比
    lastAISuggestions[sessionId] = { text: reply, messageId };

    if (mode === 'suggest') {
      pendingSuggestions++;
      updatePanel('connected', `新建议: "${reply.slice(0, 40)}..."`);
      renderReplies();
      expandPanel();
      flashPanel();
    } else if (mode === 'auto-fill') {
      updatePanel('connected', `已填充: "${reply.slice(0, 40)}..."`);
      renderReplies();
      fillReplyInput(reply);
    } else if (mode === 'auto-send') {
      updatePanel('connected', `已发送: "${reply.slice(0, 40)}..."`);
      replyObj.status = 'adopted';
      renderReplies();
      fillReplyInput(reply);
      setTimeout(() => clickSendButton(), 300);
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
        <span class="aidz-session-indicator" id="aidz-session-indicator" title="当前会话"></span>
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
    const sessionEl = document.getElementById('aidz-session-indicator');
    const colors = {
      connected: '#4caf50',
      thinking: '#ff9800',
      error: '#f44336',
      disabled: '#999',
    };
    if (statusEl) statusEl.style.color = colors[status] || '#4caf50';
    if (message && infoEl) infoEl.textContent = message;
    // 更新 session 指示器
    if (sessionEl && activeSessionId) {
      sessionEl.textContent = `📋 ${activeSessionId.slice(0, 12)}...`;
      sessionEl.title = `当前会话: ${activeSessionId}`;
    }
  }

  function updateNotifyBadge() {
    let badge = panel.querySelector('.aidz-notify-badge');
    if (pendingSuggestions > 0 && isMinimized) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'aidz-notify-badge';
        panel.appendChild(badge);
      }
      badge.textContent = pendingSuggestions > 9 ? '9+' : pendingSuggestions;
    } else if (badge) {
      badge.remove();
    }
  }

  function expandPanel() {
    if (isMinimized) {
      updateNotifyBadge();
    }
  }

  function flashPanel() {
    if (!panel) return;
    panel.style.transition = 'box-shadow 0.3s';
    panel.style.boxShadow = '0 0 20px rgba(255, 149, 0, 0.6)';
    setTimeout(() => { panel.style.boxShadow = ''; }, 1500);
  }

  /* ═══════════════════ Render Reply Cards (per-session) ═══════════════════ */
  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;

    // 只显示当前活跃 session 的回复
    const currentReplies = activeSessionId ? (sessionReplies[activeSessionId] || []) : [];

    if (currentReplies.length === 0) {
      container.innerHTML = '<div class="aidz-empty">暂无 AI 建议</div>';
      return;
    }

    container.innerHTML = currentReplies.slice(0, 10).map((r) => {
      const statusClass = r.status === 'adopted' ? 'aidz-adopted'
        : r.status === 'ignored' ? 'aidz-ignored' : '';
      const isActioned = r.status !== 'pending';
      const statusColors = { adopted: '#4caf50', edited: '#1976d2', ignored: '#999' };

      return `
        <div class="aidz-reply-card ${statusClass}" data-reply-id="${r.id}" data-session-id="${r.sessionId}">
          <div class="aidz-reply-content">${escapeHtml(r.editedText || r.text)}</div>
          <div class="aidz-reply-meta">
            <span>⏱ ${r.time}</span>
            ${r.status !== 'pending' ? `<span style="color: ${statusColors[r.status] || '#999'}">● ${statusLabel(r.status)}</span>` : ''}
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
    // 在所有 session 中查找 reply
    let reply = null;
    for (const sid of Object.keys(sessionReplies)) {
      reply = sessionReplies[sid].find((r) => r.id === id);
      if (reply) break;
    }
    if (!reply) return;

    switch (action) {
      case 'adopt': adoptReply(reply); break;
      case 'edit': toggleEditArea(reply); break;
      case 'ignore': ignoreReply(reply); break;
      case 'feedback-good': sendReplyFeedback(reply, 'good', btn); break;
      case 'feedback-bad': sendReplyFeedback(reply, 'bad', btn); break;
      case 'edit-cancel': closeEditArea(reply); break;
      case 'edit-confirm': confirmEdit(reply); break;
    }
  }

  function adoptReply(reply) {
    reply.status = 'adopted';
    const text = reply.editedText || reply.text;
    fillReplyInput(text);
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
    btn.classList.add('active');
    btn.disabled = true;
    const card = btn.closest('.aidz-reply-card');
    if (card) {
      const otherType = type === 'good' ? 'bad' : 'good';
      const otherBtn = card.querySelector(`[data-action="feedback-${otherType}"]`);
      if (otherBtn) { otherBtn.disabled = true; otherBtn.classList.add('aidz-btn-disabled'); }
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
    return { adopted: '已采纳', edited: '已编辑', ignored: '已忽略' }[status] || status;
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* ═══════════════════ Init ═══════════════════ */
  createPanel();
  console.log('[AI店长] 客服助手已加载 — 多会话支持 + 聊天记录采集');