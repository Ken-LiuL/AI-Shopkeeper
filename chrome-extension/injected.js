/**
 * injected.js — Runs in the PAGE context (not extension context).
 * 1. 拦截 WebSocket 消息（客服 IM）
 * 2. 拦截 XHR / fetch 业务数据接口（订单、商品、销售等）
 */
(function () {
  'use strict';

  const WS_CHANNEL = '__AI_DIANZHANG_WS__';
  const DATA_CHANNEL = '__AI_DIANZHANG_DATA__';

  // ─── WebSocket 拦截（保持原有逻辑）──────────────────────────────────
  const OrigWebSocket = window.WebSocket;

  class InterceptedWebSocket extends OrigWebSocket {
    constructor(url, protocols) {
      super(url, protocols);

      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed) {
            window.dispatchEvent(
              new CustomEvent(WS_CHANNEL, { detail: JSON.stringify(parsed) })
            );
          }
        } catch (_) {
          // not JSON, ignore
        }
      });
    }
  }

  InterceptedWebSocket.prototype = OrigWebSocket.prototype;
  Object.defineProperty(window, 'WebSocket', {
    value: InterceptedWebSocket,
    writable: true,
    configurable: true,
  });

  // ─── 业务数据接口识别 ─────────────────────────────────────────────────
  /**
   * 判断 URL 是否是需要拦截的牵牛花业务接口
   * 返回数据类型，或 null（不拦截）
   */
  function getDataType(url) {
    if (!url) return null;
    try {
      const u = new URL(url, location.href);
      const p = u.pathname;

      if (p.includes('/empower/generic/table/query')) return 'table_query';
      if (p.includes('/empower/complexModule/query')) return 'complex_query';
      if (p.includes('/workbench/b/dashboard')) return 'metrics';
      if (p.includes('/api/v1/merchant/')) return 'merchant';
      if (p.includes('/api/v1/tenant/')) return 'channels';
      // 常见订单/商品路径关键词
      if (p.includes('order')) return 'orders';
      if (p.includes('product') || p.includes('goods') || p.includes('sku')) return 'products';
      if (p.includes('stat') || p.includes('report') || p.includes('analytics')) return 'metrics';
    } catch (_) {}
    return null;
  }

  /**
   * 从响应体中判断是否包含有价值的业务数据，并精炼数据类型
   */
  function shouldCapture(url, responseData) {
    const rawType = getDataType(url);
    if (!rawType) return null;

    // 必须是 object 类型响应
    if (!responseData || typeof responseData !== 'object') return null;

    // 通用查询接口：根据响应内容推断业务类型
    if (rawType === 'table_query' || rawType === 'complex_query') {
      const dataStr = JSON.stringify(responseData).toLowerCase();
      if (dataStr.includes('order') || dataStr.includes('订单')) return 'orders';
      if (dataStr.includes('product') || dataStr.includes('商品') || dataStr.includes('sku')) return 'products';
      if (dataStr.includes('sale') || dataStr.includes('revenue') || dataStr.includes('销售') || dataStr.includes('营业额')) return 'metrics';
      return rawType; // 保留原类型
    }

    return rawType;
  }

  /**
   * 派发业务数据事件，由 content_script 接收转发给 background
   */
  function emitDataEvent(type, url, data) {
    try {
      window.dispatchEvent(
        new CustomEvent(DATA_CHANNEL, {
          detail: JSON.stringify({ type, url, data }),
        })
      );
    } catch (_) {}
  }

  // ─── fetch 拦截 ───────────────────────────────────────────────────────
  const OrigFetch = window.fetch;
  window.fetch = async function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
    const response = await OrigFetch.apply(this, args);

    const dataType = getDataType(url);
    if (dataType) {
      // 克隆 response 以不影响原始消费
      const clone = response.clone();
      clone.json().then((json) => {
        const type = shouldCapture(url, json);
        if (type) emitDataEvent(type, url, json);
      }).catch(() => {});
    }

    return response;
  };

  // ─── XHR 拦截 ────────────────────────────────────────────────────────
  const OrigXHROpen = XMLHttpRequest.prototype.open;
  const OrigXHRSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__interceptUrl__ = url;
    return OrigXHROpen.apply(this, [method, url, ...rest]);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    const url = this.__interceptUrl__;
    const dataType = getDataType(url);

    if (dataType) {
      this.addEventListener('load', () => {
        try {
          const json = JSON.parse(this.responseText);
          const type = shouldCapture(url, json);
          if (type) emitDataEvent(type, url, json);
        } catch (_) {}
      });
    }

    return OrigXHRSend.apply(this, args);
  };

  console.log('[AI店长] WebSocket + API 拦截器已安装');
})();
