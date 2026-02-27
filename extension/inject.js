/**
 * 注入脚本 - 运行在页面上下文，绕过 content script 限制
 * 主要用于执行需要 mtgsig/h5guard 签名的 API 请求
 */

(function() {
  'use strict';

  // 防止重复注入
  if (window.aiStoreManagerInjected) {
    return;
  }
  window.aiStoreManagerInjected = true;

  /**
   * 页面上下文的 API 客户端
   * 可以访问页面的 cookies 和签名函数
   */
  class PageAPIClient {
    constructor() {
      this.csecParams = {
        yodaReady: 'h5',
        csecplatform: '4',
        csecversion: '4.2.0'
      };
    }

    /**
     * 在页面上下文执行 fetch 请求
     * 自动携带 cookies 和必要的签名
     */
    async executeAPICall(url, options = {}) {
      try {
        // 为 goldengateway 和 qnh-gw3 添加 CSEC 参数
        if (url.includes('/goldengateway/') || url.includes('/qnh-gw3/')) {
          const urlObj = new URL(url);
          Object.entries(this.csecParams).forEach(([key, value]) => {
            urlObj.searchParams.set(key, value);
          });
          url = urlObj.toString();
        }

        const defaultOptions = {
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Origin': 'https://qnh.meituan.com',
            'Referer': 'https://qnh.meituan.com/home.html',
            ...options.headers
          }
        };

        const response = await fetch(url, { ...defaultOptions, ...options });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        // 检查 API 错误
        if (data.code !== undefined && data.code !== 0) {
          throw new Error(`API 错误 ${data.code}: ${data.msg || data.message || '未知错误'}`);
        }

        return { success: true, data };
      } catch (error) {
        console.error('页面 API 调用失败:', error);
        return { success: false, error: error.message };
      }
    }
  }

  const pageClient = new PageAPIClient();

  /**
   * 监听来自 content script 的消息
   */
  window.addEventListener('message', async function(event) {
    // 只处理来自同源的消息
    if (event.origin !== 'https://qnh.meituan.com') {
      return;
    }

    const { type, payload, requestId } = event.data;

    if (type !== 'AI_STORE_MANAGER_API_CALL') {
      return;
    }

    try {
      const { url, options } = payload;
      const result = await pageClient.executeAPICall(url, options);

      // 回传结果
      window.postMessage({
        type: 'AI_STORE_MANAGER_API_RESPONSE',
        requestId,
        payload: result
      }, 'https://qnh.meituan.com');

    } catch (error) {
      // 回传错误
      window.postMessage({
        type: 'AI_STORE_MANAGER_API_RESPONSE',
        requestId,
        payload: { success: false, error: error.message }
      }, 'https://qnh.meituan.com');
    }
  });

  /**
   * 获取当前页面的租户和门店信息
   */
  function extractTenantInfo() {
    try {
      // 尝试从页面 URL 或全局变量获取租户信息
      const urlParams = new URLSearchParams(window.location.search);
      const tenantId = urlParams.get('tenantId');

      // 尝试从页面的全局变量获取
      const globalTenant = window.APP_CONFIG?.tenantId || window.tenantId;
      const globalPoiIds = window.APP_CONFIG?.poiIds || window.poiIds;

      return {
        tenantId: tenantId || globalTenant || DEFAULT_CONFIG?.defaultTenantId,
        poiIds: globalPoiIds || DEFAULT_CONFIG?.defaultPoiIds || []
      };
    } catch (error) {
      console.warn('无法提取租户信息:', error);
      return {
        tenantId: '1011766',
        poiIds: [1175006, 1221411, 1232550]
      };
    }
  }

  // 初始化时广播租户信息
  setTimeout(() => {
    const tenantInfo = extractTenantInfo();
    window.postMessage({
      type: 'AI_STORE_MANAGER_TENANT_INFO',
      payload: tenantInfo
    }, 'https://qnh.meituan.com');
  }, 1000);

  console.log('AI店长注入脚本已加载');
})();
