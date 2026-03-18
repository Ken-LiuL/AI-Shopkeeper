/**
 * content_script.js — AI店长 Chrome Extension v3
 * 
 * 核心改进：完全数据驱动的多会话管理
 * - WS 消息自带 sessionId → 直接用，不依赖 DOM 猜测
 * - 所有会话并行处理，AI 建议按 session 隔离
 * - 面板显示所有待处理建议，标注会话来源
 * - 聊天记录全量采集（客户 + 客服），后端去重
 */
(function () {
  'use strict';

  /* ═══════════════════ State ═══════════════════ */
  let enabled = true;
  let mode = 'suggest'; // 'suggest' | 'auto-fill' | 'auto-send'
  const processedMessages = new Set();

  // ── 多 Session 管理（纯数据驱动）─────────────────────────────
  // sessionData: { [sessionId]: { replies: [], customerName: '', lastActivity: Date, pendingCount: 0 } }
  const sessionData = {};
  // 所有待处理建议（跨 session 的优先队列）
  const pendingQueue = []; // [{ id, text, time, sessionId, customerName, ... }]

  /* ═══════════════════ Session Helpers ═══════════════════ */
  function getSession(sessionId) {
    if (!sessionData[sessionId]) {
      sessionData[sessionId] = {
        replies: [],
        customerName: '',
        lastActivity: Date.now(),
        pendingCount: 0,
      };
    }
    sessionData[sessionId].lastActivity = Date.now();
    return sessionData[sessionId];
  }

  function addReplyToSession(sessionId, replyObj) {
    const session = getSession(sessionId);
    session.replies.unshift(replyObj);
    if (session.replies.length > 20) session.replies.pop();
    if (replyObj.status === 'pending') {
      session.pendingCount++;
      pendingQueue.unshift(replyObj);
      if (pendingQueue.length > 50) pendingQueue.pop();
    }
    // 清理超过 1 小时不活跃的 session
    const cutoff = Date.now() - 3600000;
    for (const sid of Object.keys(sessionData)) {
      if (sessionData[sid].lastActivity < cutoff && sessionData[sid].pendingCount === 0) {
        delete sessionData[sid];
      }
    }
  }

  function extractSessionId(data) {
    // 从 WS 消息的各种字段名中提取 session ID
    const candidates = [
      data.sessionId, data.conversationId, data.session_id,
      data.conversation_id, data.chatId, data.chat_id,
    ];
    const inner = data.data || data.body || data.payload || {};
    candidates.push(
      inner.sessionId, inner.conversationId, inner.session_id,
      inner.conversation_id, inner.chatId, inner.chat_id,
    );
    for (const c of candidates) {
      if (c && typeof c === 'string' && c.trim() !== '') return c;
    }
    return null;
  }

  function extractCustomerName(data) {
    const sources = [
      data.customer, data.sender, data.user,
      data.data?.customer, data.data?.sender, data.data?.user,
      data.payload?.customer, data.payload?.sender,
    ];
    for (const s of sources) {
      if (!s) continue;
      const name = s.name || s.nickname || s.nick || s.displayName || s.userName;
      if (name && typeof name === 'string') return name;
    }
    return '';
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

  /* ═══════════════════ WS Listener (主要数据源) ═══════════════════ */
  window.addEventListener('__AI_DIANZHANG_WS__', (e) => {
    if (!enabled) return;
    try {
      const data = JSON.parse(e.detail);
      handleWSMessage(data);
    } catch (_) {}
  });

  function handleWSMessage(data) {
    const sessionId = extractSessionId(data);

    // 客户消息 → 触发 AI + 采集
    const customerMsg = extractCustomerMessage(data, sessionId);
    if (customerMsg && !processedMessages.has(customerMsg.id)) {
      processedMessages.add(customerMsg.id);
      trimProcessed();
      // 记录客户名字
      const name = extractCustomerName(data);
      if (name && customerMsg.sessionId) {
        getSession(customerMsg.sessionId).customerName = name;
      }
      // 采集客户消息
      logChatMessage({ ...customerMsg, role: 'customer' });
      // 触发 AI 建议
      sendToBackend(customerMsg);
    }

    // 客服消息 → 仅采集
    const agentMsg = extractAgentMessage(data, sessionId);
    if (agentMsg && !processedMessages.has(agentMsg.id)) {
      processedMessages.add(agentMsg.id);
      trimProcessed();
      logChatMessage(agentMsg);
      // 对比 AI 建议
      const session = sessionData[agentMsg.sessionId];
      if (session) {
        const lastSuggestion = session.replies.find(r => r.status === 'pending');
        if (lastSuggestion && lastSuggestion.text !== agentMsg.text) {
          trackReplyComparison(lastSuggestion, agentMsg.text, agentMsg.sessionId);
        }
      }
    }
  }

  function trimProcessed() {
    if (processedMessages.size > 1000) {
      const iter = processedMessages.values();
      for (let i = 0; i < 200; i++) {
        processedMessages.delete(iter.next().value);
      }
    }
  }

  function extractCustomerMessage(data, fallbackSessionId) {
    // Pattern 1: top-level incoming
    if (data.type === 'message' && data.direction === 'in') {
      return {
        id: data.msgId || data.id || `ws-cust-${Date.now()}`,
        text: data.content || data.text || data.body || '',
        sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
        customerInfo: data.customer || data.sender || {},
      };
    }
    // Pattern 2: nested
    const inner = data.data || data.body || {};
    if (inner.msgType !== undefined && inner.fromCustomer !== false && inner.role !== 'merchant' && inner.role !== 'agent') {
      const text = inner.content || inner.text || '';
      if (text) {
        return {
          id: inner.msgId || inner.id || `ws-cust-${Date.now()}`,
          text,
          sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
          customerInfo: inner.customer || inner.sender || {},
        };
      }
    }
    // Pattern 3: chat command
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      if (payload.content && payload.role !== 'merchant' && payload.role !== 'agent') {
        return {
          id: payload.msgId || payload.id || `ws-cust-${Date.now()}`,
          text: payload.content,
          sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
          customerInfo: payload.customer || {},
        };
      }
    }
    return null;
  }

  function extractAgentMessage(data, fallbackSessionId) {
    // Pattern 1: outgoing
    if (data.type === 'message' && data.direction === 'out') {
      return {
        id: data.msgId || data.id || `ws-agent-${Date.now()}`,
        text: data.content || data.text || data.body || '',
        sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
        role: 'agent',
      };
    }
    // Pattern 2: nested outgoing
    const inner = data.data || data.body || {};
    if (inner.fromCustomer === false || inner.role === 'merchant' || inner.role === 'agent') {
      const text = inner.content || inner.text || '';
      if (text) {
        return {
          id: inner.msgId || inner.id || `ws-agent-${Date.now()}`,
          text,
          sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
          role: 'agent',
        };
      }
    }
    // Pattern 3
    if (data.cmd === 'chat' || data.action === 'newMessage') {
      const payload = data.payload || data.data || data;
      if (payload.content && (payload.role === 'merchant' || payload.role === 'agent')) {
        return {
          id: payload.msgId || payload.id || `ws-agent-${Date.now()}`,
          text: payload.content,
          sessionId: extractSessionId(data) || fallbackSessionId || `unknown-${Date.now()}`,
          role: 'agent',
        };
      }
    }
    return null;
  }

  /* ═══════════════════ DOM Observer (补充采集) ═══════════════════ */
  // DOM 只作为 WS 的补充（某些消息可能不经过 WS）
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

            // 客户消息
            const customerBubble = node.matches?.('[class*="customer"], [class*="receive"], [class*="left"]')
              ? node : node.querySelector?.('[class*="customer"], [class*="receive"], [class*="left"]');
            if (customerBubble) {
              const textEl = customerBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text) {
                // DOM 无法可靠获取 sessionId，用 content hash 去重（后端会处理）
                const dedupKey = `dom-cust-${hashCode(text)}`;
                if (!processedMessages.has(dedupKey)) {
                  processedMessages.add(dedupKey);
                  // 不触发 AI（WS 已触发），只做采集补充
                  logChatMessage({
                    id: `dom-${Date.now()}-${hashCode(text)}`,
                    text,
                    sessionId: findMostRecentActiveSession() || `dom-fallback-${Date.now()}`,
                    role: 'customer',
                  });
                }
              }
            }

            // 客服消息
            const agentBubble = node.matches?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]')
              ? node : node.querySelector?.('[class*="merchant"], [class*="send"], [class*="right"], [class*="agent"]');
            if (agentBubble) {
              const textEl = agentBubble.querySelector('[class*="text"], [class*="content"], p, span');
              const text = textEl?.textContent?.trim();
              if (text) {
                const dedupKey = `dom-agent-${hashCode(text)}`;
                if (!processedMessages.has(dedupKey)) {
                  processedMessages.add(dedupKey);
                  logChatMessage({
                    id: `dom-agent-${Date.now()}-${hashCode(text)}`,
                    text,
                    sessionId: findMostRecentActiveSession() || `dom-fallback-${Date.now()}`,
                    role: 'agent',
                  });
                }
              }
            }
          }
        }
      }).observe(container, { childList: true, subtree: true });
    }
    observe();
  }

  function findMostRecentActiveSession() {
    // 找最近有活动的 session（WS 数据驱动）
    let latest = null;
    let latestTime = 0;
    for (const [sid, data] of Object.entries(sessionData)) {
      if (data.lastActivity > latestTime) {
        latestTime = data.lastActivity;
        latest = sid;
      }
    }
    return latest;
  }

  startDOMObserver();

  function trackReplyComparison(suggestion, actual, sessionId) {
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

  /* ═══════════════════ Chat Log Collection ═══════════════════ */
  function logChatMessage(msg) {
    if (!msg.text) return;
    chrome.runtime.sendMessage({
      type: 'LOG_CHAT',
      payload: {
        session_id: msg.sessionId || '',
        message_id: msg.id || '',
        role: msg.role || 'unknown',
        content: msg.text,
        timestamp: new Date().toISOString(),
      },
    });
  }

  /* ═══════════════════ Backend Communication ═══════════════════ */
  function sendToBackend(msg) {
    if (!msg.text) return;
    const session = getSession(msg.sessionId);
    const customerLabel = session.customerName || msg.sessionId?.slice(0, 10) || '客户';
    updatePanel('thinking', `🤔 [${customerLabel}] "${msg.text.slice(0, 20)}..."`);

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
          updatePanel('error', '后台连接中断');
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
    chrome.runtime.sendMessage({ type: 'SEND_FEEDBACK', payload: data }, () => {
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
    const session = getSession(sessionId);
    const customerLabel = session.customerName || sessionId?.slice(0, 10) || '客户';

    const replyObj = {
      id: `reply-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      text: reply,
      time: new Date().toLocaleTimeString(),
      sessionId: sessionId || '',
      messageId: messageId || '',
      customerName: customerLabel,
      status: 'pending',
      editedText: '',
    };

    addReplyToSession(sessionId, replyObj);

    if (mode === 'suggest') {
      updatePanel('connected', `✨ [${customerLabel}] 新建议`);
      renderReplies();
      flashPanel();
    } else if (mode === 'auto-fill') {
      updatePanel('connected', `✏️ [${customerLabel}] 已填充`);
      renderReplies();
      fillReplyInput(reply);
    } else if (mode === 'auto-send') {
      updatePanel('connected', `🚀 [${customerLabel}] 已发送`);
      replyObj.status = 'adopted';
      renderReplies();
      fillReplyInput(reply);
      setTimeout(() => clickSendButton(), 300);
      sendFeedback({
        session_id: sessionId,
        message_id: messageId,
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
        <span class="aidz-session-count" id="aidz-session-count" title="活跃会话数"></span>
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
      }
    });

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
    });
  }

  function updateModeBadge() {
    const badge = document.getElementById('aidz-mode-badge');
    if (!badge) return;
    badge.textContent = { suggest: '建议', 'auto-fill': '半自动', 'auto-send': '全自动' }[mode] || mode;
  }

  function updatePanel(status, message) {
    if (!panel) return;
    const statusEl = document.getElementById('aidz-status');
    const infoEl = document.getElementById('aidz-info');
    const countEl = document.getElementById('aidz-session-count');
    const colors = { connected: '#4caf50', thinking: '#ff9800', error: '#f44336', disabled: '#999' };
    if (statusEl) statusEl.style.color = colors[status] || '#4caf50';
    if (message && infoEl) infoEl.textContent = message;
    // 更新活跃会话数
    if (countEl) {
      const activeCount = Object.keys(sessionData).length;
      const pendingTotal = Object.values(sessionData).reduce((sum, s) => sum + s.pendingCount, 0);
      countEl.textContent = pendingTotal > 0 ? `📋 ${activeCount}会话 · ${pendingTotal}待处理` : `📋 ${activeCount}会话`;
    }
  }

  function flashPanel() {
    if (!panel) return;
    panel.style.transition = 'box-shadow 0.3s';
    panel.style.boxShadow = '0 0 20px rgba(255, 149, 0, 0.6)';
    setTimeout(() => { panel.style.boxShadow = ''; }, 1500);
  }

  /* ═══════════════════ Render Reply Cards (跨 session) ═══════════════════ */
  function renderReplies() {
    const container = document.getElementById('aidz-replies');
    if (!container) return;

    // 收集所有 session 的待处理 + 最近回复，按时间排序
    const allReplies = [];
    for (const [sid, data] of Object.entries(sessionData)) {
      for (const r of data.replies.slice(0, 5)) {
        allReplies.push(r);
      }
    }
    // 按时间倒序（最新的在上面）
    allReplies.sort((a, b) => {
      const ta = new Date(`1970-01-01T${a.time}`).getTime() || 0;
      const tb = new Date(`1970-01-01T${b.time}`).getTime() || 0;
      return tb - ta;
    });

    const display = allReplies.slice(0, 10);

    if (display.length === 0) {
      container.innerHTML = '<div class="aidz-empty">暂无 AI 建议</div>';
      return;
    }

    container.innerHTML = display.map((r) => {
      const statusClass = r.status === 'adopted' ? 'aidz-adopted'
        : r.status === 'ignored' ? 'aidz-ignored' : '';
      const isActioned = r.status !== 'pending';
      const statusColors = { adopted: '#4caf50', edited: '#1976d2', ignored: '#999' };
      const label = r.customerName || r.sessionId?.slice(0, 8) || '未知';

      return `
        <div class="aidz-reply-card ${statusClass}" data-reply-id="${r.id}" data-session-id="${r.sessionId}">
          <div class="aidz-reply-session-tag" title="${r.sessionId}">👤 ${escapeHtml(label)}</div>
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

    container.onclick = handleReplyAction;
    updatePanel('connected', '');
  }

  function handleReplyAction(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    let reply = null;
    for (const sid of Object.keys(sessionData)) {
      reply = sessionData[sid].replies.find((r) => r.id === id);
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
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    fillReplyInput(reply.editedText || reply.text);
    if (mode === 'auto-send') setTimeout(() => clickSendButton(), 300);
    renderReplies();
    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'good', action: 'adopted',
      original_reply: reply.text,
      edited_reply: reply.editedText || '',
      actual_reply: reply.editedText || reply.text,
    });
  }

  function toggleEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) {
      area.classList.toggle('active');
      if (area.classList.contains('active')) {
        const ta = document.getElementById(`edit-text-${reply.id}`);
        if (ta) ta.focus();
      }
    }
  }

  function closeEditArea(reply) {
    const area = document.getElementById(`edit-area-${reply.id}`);
    if (area) area.classList.remove('active');
  }

  function confirmEdit(reply) {
    const ta = document.getElementById(`edit-text-${reply.id}`);
    if (!ta) return;
    const editedText = ta.value.trim();
    if (!editedText) return;
    reply.editedText = editedText;
    reply.status = 'edited';
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    fillReplyInput(editedText);
    if (mode === 'auto-send') setTimeout(() => clickSendButton(), 300);
    renderReplies();
    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'good', action: 'edited',
      original_reply: reply.text,
      edited_reply: editedText,
      actual_reply: editedText,
    });
  }

  function ignoreReply(reply) {
    reply.status = 'ignored';
    const session = sessionData[reply.sessionId];
    if (session) session.pendingCount = Math.max(0, session.pendingCount - 1);
    renderReplies();
    sendFeedback({
      session_id: reply.sessionId,
      message_id: reply.messageId,
      feedback: 'bad', action: 'ignored',
      original_reply: reply.text,
      edited_reply: '', actual_reply: '',
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
  console.log('[AI店长] v3 已加载 — 数据驱动多会话 + 全量聊天记录采集');
})();