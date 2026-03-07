/**
 * injected.js — 页面上下文，拦截 WebSocket 捕获客服消息
 */
(function () {
  'use strict';

  const WS_CHANNEL = '__AI_DIANZHANG_WS__';

  // WebSocket 拦截 — 捕获客服 IM 消息
  const OrigWebSocket = window.WebSocket;
  class InterceptedWebSocket extends OrigWebSocket {
    constructor(url, protocols) {
      super(url, protocols);
      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed) {
            window.dispatchEvent(new CustomEvent(WS_CHANNEL, { detail: JSON.stringify(parsed) }));
          }
        } catch (_) {}
      });
    }
  }
  InterceptedWebSocket.prototype = OrigWebSocket.prototype;
  Object.defineProperty(window, 'WebSocket', { value: InterceptedWebSocket, writable: true, configurable: true });

  console.log('[AI店长] 客服消息拦截器已安装');
})();
