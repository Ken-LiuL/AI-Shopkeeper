/**
 * injected.js — Runs in the PAGE context (not extension context).
 * 数据来源：yiyao.meituan.com（美团买药商家后台）
 * 拦截 XHR / fetch 自动采集订单、商品、评价、销售数据
 */
(function () {
  'use strict';

  const DATA_CHANNEL = '__AI_DIANZHANG_DATA__';
  // ─── 业务 API 路径识别（仅 yiyao）──────────────────────────────────────
  function getDataType(url) {
    if (!url) return null;
    try {
      const u = new URL(url, location.href);
      const h = u.hostname;
      const p = u.pathname;

      // === yiyao.meituan.com 路径规则 ===
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
    } catch (_) {}
    return null;
  }

  function shouldCapture(url, responseData) {
    const rawType = getDataType(url);
    if (!rawType) return null;
    if (!responseData || typeof responseData !== 'object') return null;
    if (responseData.code !== undefined && responseData.code !== 0 && responseData.code !== 200) return null;
    if (responseData.errno !== undefined && responseData.errno !== 0) return null;

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

  console.log('[AI店长] 已安装 yiyao.meituan.com 数据拦截器');
})();
