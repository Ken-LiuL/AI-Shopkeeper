/**
 * injected.js — Runs in the PAGE context (not extension context).
 * 支持：yiyao.meituan.com（美团买药商家后台）+ qnh.meituan.com（牵牛花）
 * 拦截 XHR / fetch 自动采集订单、商品、评价、销售数据
 */
(function () {
  'use strict';

  const WS_CHANNEL = '__AI_DIANZHANG_WS__';
  const DATA_CHANNEL = '__AI_DIANZHANG_DATA__';

  // ─── WebSocket 拦截 ───────────────────────────────────────────────────
  const OrigWebSocket = window.WebSocket;
  class InterceptedWebSocket extends OrigWebSocket {
    constructor(url, protocols) {
      super(url, protocols);
      this.addEventListener('message', (event) => {
        try {
          const parsed = typeof event.data === 'string' ? JSON.parse(event.data) : null;
          if (parsed) window.dispatchEvent(new CustomEvent(WS_CHANNEL, { detail: JSON.stringify(parsed) }));
        } catch (_) {}
      });
    }
  }
  InterceptedWebSocket.prototype = OrigWebSocket.prototype;
  Object.defineProperty(window, 'WebSocket', { value: InterceptedWebSocket, writable: true, configurable: true });

  // ─── 业务 API 路径识别（yiyao + qnh 两套）────────────────────────────
  function getDataType(url) {
    if (!url) return null;
    try {
      const u = new URL(url, location.href);
      const h = u.hostname;
      const p = u.pathname;

      // === yiyao.meituan.com 路径规则（精确匹配，不能 fallthrough 到 qnh）===
      if (h === 'yiyao.meituan.com') {
        // 商品列表
        if (p.includes('/retail/r/searchListPage')) return 'products';
        if (p.includes('/product/') && (p.includes('/list') || p.includes('/search'))) return 'products';
        // 订单列表
        if (p.includes('/order/list') || p.includes('/order/history') || p.includes('/waimai/order')) return 'orders';
        // 评价/评论
        if (p.includes('/comment') || p.includes('/review') || p.includes('/evaluate') || p.includes('/appraise')) return 'reviews';
        // 营业额/统计
        if (p.includes('/stat/') || p.includes('/data/report') || p.includes('/data/stat') || p.includes('/business/data') || p.includes('/dashboard')) return 'metrics';
        // 库存
        if (p.includes('/stock') || p.includes('/inventory')) return 'inventory';
        // 退款/售后
        if (p.includes('/refund') || p.includes('/after-sale') || p.includes('/aftersale')) return 'refunds';
      }

      // === qnh.meituan.com 路径规则 ===
      if (h === 'qnh.meituan.com') {
        if (p.includes('/empower/generic/table/query')) return 'table_query';
        if (p.includes('/empower/complexModule/query')) return 'complex_query';
        if (p.includes('/workbench/b/dashboard')) return 'metrics';
        if (p.includes('order')) return 'orders';
        if (p.includes('product') || p.includes('goods') || p.includes('sku')) return 'products';
        if (p.includes('stat') || p.includes('report') || p.includes('analytics')) return 'metrics';
        if (p.includes('review') || p.includes('comment')) return 'reviews';
      }
    } catch (_) {}
    return null;
  }

  function shouldCapture(url, responseData) {
    const rawType = getDataType(url);
    if (!rawType) return null;
    if (!responseData || typeof responseData !== 'object') return null;

    // 通用查询接口：根据响应内容推断业务类型
    if (rawType === 'table_query' || rawType === 'complex_query') {
      const dataStr = JSON.stringify(responseData).toLowerCase();
      if (dataStr.includes('order') || dataStr.includes('订单')) return 'orders';
      if (dataStr.includes('product') || dataStr.includes('商品') || dataStr.includes('sku')) return 'products';
      if (dataStr.includes('sale') || dataStr.includes('revenue') || dataStr.includes('销售')) return 'metrics';
      return rawType;
    }
    return rawType;
  }

  function emitDataEvent(type, url, data) {
    try {
      window.dispatchEvent(new CustomEvent(DATA_CHANNEL, { detail: JSON.stringify({ type, url, data }) }));
    } catch (_) {}
  }

  // ─── fetch 拦截 ───────────────────────────────────────────────────────
  const OrigFetch = window.fetch;
  window.fetch = async function (...args) {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
    const response = await OrigFetch.apply(this, args);
    const dataType = getDataType(url);
    if (dataType) {
      response.clone().json().then((json) => {
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
    if (getDataType(url)) {
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

  console.log('[AI店长] 数据拦截器已安装（yiyao.meituan.com + qnh.meituan.com）');
})();
