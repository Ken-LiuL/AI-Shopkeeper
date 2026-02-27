/**
 * Content Script - 运行在牵牛花页面上下文
 * 负责执行数据获取和与 background script 通信
 */

(function() {
  'use strict';

  let tenantId = DEFAULT_CONFIG.defaultTenantId;
  let poiIds = DEFAULT_CONFIG.defaultPoiIds;
  let requestIdCounter = 0;
  const pendingRequests = new Map();

  console.log('AI店长 Content Script 已加载');

  /**
   * 注入页面脚本
   */
  function injectPageScript() {
    const script = document.createElement('script');
    script.src = chrome.runtime.getURL('inject.js');
    script.onload = function() {
      this.remove();
    };
    (document.head || document.documentElement).appendChild(script);
  }

  /**
   * 通过页面上下文执行 API 调用
   * 用于需要 mtgsig/h5guard 签名的请求
   */
  function executeInPageContext(url, options = {}) {
    return new Promise((resolve, reject) => {
      const requestId = `req_${++requestIdCounter}`;

      // 设置超时
      const timeout = setTimeout(() => {
        pendingRequests.delete(requestId);
        reject(new Error('请求超时'));
      }, 30000); // 30秒超时

      pendingRequests.set(requestId, { resolve, reject, timeout });

      // 发送消息到页面脚本
      window.postMessage({
        type: 'AI_STORE_MANAGER_API_CALL',
        requestId,
        payload: { url, options }
      }, 'https://qnh.meituan.com');
    });
  }

  /**
   * 监听页面脚本的响应
   */
  window.addEventListener('message', function(event) {
    if (event.origin !== 'https://qnh.meituan.com') {
      return;
    }

    const { type, requestId, payload } = event.data;

    if (type === 'AI_STORE_MANAGER_API_RESPONSE' && pendingRequests.has(requestId)) {
      const { resolve, reject, timeout } = pendingRequests.get(requestId);
      clearTimeout(timeout);
      pendingRequests.delete(requestId);

      if (payload.success) {
        resolve(payload.data);
      } else {
        reject(new Error(payload.error));
      }
    } else if (type === 'AI_STORE_MANAGER_TENANT_INFO') {
      // 更新租户信息
      if (payload.tenantId) {
        tenantId = payload.tenantId;
      }
      if (payload.poiIds && payload.poiIds.length > 0) {
        poiIds = payload.poiIds;
      }

      // 更新 API 客户端配置
      if (window.dataFetchers) {
        window.dataFetchers.updateConfig(tenantId, poiIds);
      }

      console.log('更新租户配置:', { tenantId, poiIds });
    }
  });

  /**
   * 增强的 API 客户端 - 优先使用页面上下文
   */
  class EnhancedAPIClient extends QNHAPIClient {

    /**
     * 智能路由：goldengateway 和 qnh-gw3 通过页面上下文，其他直接请求
     */
    async post(path, body = {}, params = {}) {
      if (path.includes('/goldengateway/') || path.includes('/qnh-gw3/')) {
        // 通过页面上下文执行
        const url = this.buildURL(path, params);
        return await executeInPageContext(url, {
          method: 'POST',
          body: JSON.stringify(body)
        });
      } else {
        // 直接执行
        return await super.post(path, body, params);
      }
    }

    async get(path, params = {}) {
      if (path.includes('/goldengateway/') || path.includes('/qnh-gw3/')) {
        // 通过页面上下文执行
        const url = this.buildURL(path, params);
        return await executeInPageContext(url, { method: 'GET' });
      } else {
        // 直接执行
        return await super.get(path, params);
      }
    }
  }

  /**
   * 增强的数据获取器
   */
  class EnhancedDataFetchers extends DataFetchers {
    constructor() {
      super(new EnhancedAPIClient());
      this.updateConfig(tenantId, poiIds);
    }

    /**
     * 获取当前页面的实时数据
     * 比直接 API 调用更准确
     */
    async fetchPageData() {
      try {
        // 尝试从页面 DOM 提取数据
        const pageData = this.extractDataFromDOM();
        if (pageData && Object.keys(pageData).length > 0) {
          return pageData;
        }
      } catch (error) {
        console.warn('从页面 DOM 提取数据失败:', error);
      }

      return null;
    }

    /**
     * 从页面 DOM 提取数据
     */
    extractDataFromDOM() {
      const data = {};

      try {
        // 提取门店概览数据
        const overviewCards = document.querySelectorAll('.overview-card, .metric-card');
        if (overviewCards.length > 0) {
          data.overview = [];
          overviewCards.forEach(card => {
            const title = card.querySelector('.title, .metric-title')?.textContent;
            const value = card.querySelector('.value, .metric-value')?.textContent;
            if (title && value) {
              data.overview.push({ title: title.trim(), value: value.trim() });
            }
          });
        }

        // 提取表格数据
        const tables = document.querySelectorAll('table');
        if (tables.length > 0) {
          data.tables = [];
          tables.forEach((table, index) => {
            const rows = [];
            const tableRows = table.querySelectorAll('tr');
            tableRows.forEach(row => {
              const cells = [];
              row.querySelectorAll('td, th').forEach(cell => {
                cells.push(cell.textContent.trim());
              });
              if (cells.length > 0) {
                rows.push(cells);
              }
            });
            if (rows.length > 0) {
              data.tables.push({ index, rows });
            }
          });
        }
      } catch (error) {
        console.error('DOM 数据提取错误:', error);
      }

      return data;
    }
  }

  // 创建增强的实例
  window.enhancedDataFetchers = new EnhancedDataFetchers();

  /**
   * 监听来自 background script 的消息
   */
  chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
    console.log('收到 background 消息:', request);

    if (request.action === 'syncData') {
      handleSyncRequest(request, sendResponse);
      return true; // 异步响应
    } else if (request.action === 'getStatus') {
      handleStatusRequest(request, sendResponse);
      return true; // 异步响应
    } else if (request.action === 'testConnection') {
      handleTestConnection(request, sendResponse);
      return true; // 异步响应
    }

    return false;
  });

  /**
   * 处理同步请求
   */
  async function handleSyncRequest(request, sendResponse) {
    const { source } = request;

    try {
      console.log(`开始同步数据源: ${source}`);

      const fetchers = window.enhancedDataFetchers;
      const fetcherName = DATA_SOURCES[source]?.fetcher;

      if (!fetcherName || typeof fetchers[fetcherName] !== 'function') {
        throw new Error(`未找到数据获取器: ${fetcherName}`);
      }

      // 执行数据获取
      const data = await fetchers[fetcherName]();

      console.log(`${source} 数据获取成功:`, data?.length || 'N/A', '条记录');

      sendResponse({
        success: true,
        source,
        data,
        count: Array.isArray(data) ? data.length : 1,
        timestamp: new Date().toISOString()
      });

    } catch (error) {
      console.error(`${source} 同步失败:`, error);
      sendResponse({
        success: false,
        source,
        error: error.message,
        timestamp: new Date().toISOString()
      });
    }
  }

  /**
   * 处理状态请求
   */
  async function handleStatusRequest(request, sendResponse) {
    try {
      // 检查页面是否已登录
      const isLoggedIn = await checkLoginStatus();

      // 获取当前页面信息
      const pageInfo = {
        url: window.location.href,
        title: document.title,
        tenantId,
        poiIds,
        isLoggedIn
      };

      sendResponse({
        success: true,
        pageInfo,
        timestamp: new Date().toISOString()
      });

    } catch (error) {
      sendResponse({
        success: false,
        error: error.message,
        timestamp: new Date().toISOString()
      });
    }
  }

  /**
   * 处理连接测试
   */
  async function handleTestConnection(request, sendResponse) {
    try {
      // 测试一个简单的 API 调用
      const result = await window.enhancedDataFetchers.api.get('/api/v1/isLogined');

      sendResponse({
        success: true,
        connected: true,
        data: result,
        timestamp: new Date().toISOString()
      });

    } catch (error) {
      sendResponse({
        success: false,
        connected: false,
        error: error.message,
        timestamp: new Date().toISOString()
      });
    }
  }

  /**
   * 检查登录状态
   */
  async function checkLoginStatus() {
    try {
      const result = await window.enhancedDataFetchers.api.get('/api/v1/isLogined');
      return result.data === true || result.code === 0;
    } catch (error) {
      console.warn('检查登录状态失败:', error);
      return false;
    }
  }

  // 页面加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

  function initialize() {
    // 注入页面脚本
    injectPageScript();

    // 发送初始化消息到 background
    chrome.runtime.sendMessage({
      action: 'contentScriptReady',
      url: window.location.href,
      title: document.title
    });

    console.log('AI店长 Content Script 初始化完成');
  }

})();
