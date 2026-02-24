/**
 * injected.js — Runs in the PAGE context (not extension context).
 * Overrides WebSocket to intercept incoming chat messages from 牵牛花.
 */
(function () {
  'use strict';

  const CHANNEL = '__AI_DIANZHANG_WS__';
  const OrigWebSocket = window.WebSocket;

  class InterceptedWebSocket extends OrigWebSocket {
    constructor(url, protocols) {
      super(url, protocols);

      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed) {
            window.dispatchEvent(
              new CustomEvent(CHANNEL, { detail: JSON.stringify(parsed) })
            );
          }
        } catch (_) {
          // not JSON, ignore
        }
      });
    }
  }

  // Preserve prototype chain
  InterceptedWebSocket.prototype = OrigWebSocket.prototype;
  Object.defineProperty(window, 'WebSocket', {
    value: InterceptedWebSocket,
    writable: true,
    configurable: true,
  });

  console.log('[AI店长] WebSocket interceptor installed');
})();
