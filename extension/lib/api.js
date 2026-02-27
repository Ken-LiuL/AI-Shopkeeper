/**
 * API 调用封装库 - 牵牛花 API 客户端
 * 运行在 content script 上下文，可以直接调用页面 API
 */

class QNHAPIClient {
  constructor() {
    this.baseURL = 'https://qnh.meituan.com';
    this.neixinBaseURL = 'https://api.neixin.cn';

    // CSEC 安全参数 (所有 QNH API 必需)
    this.csecParams = {
      yodaReady: 'h5',
      csecplatform: '4',
      csecversion: '4.2.0'
    };

    // 默认请求头
    this.defaultHeaders = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/plain, */*',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      'Origin': this.baseURL,
      'Referer': `${this.baseURL}/home.html`
    };
  }

  /**
   * 构建带 CSEC 参数的 URL
   */
  buildURL(path, extraParams = {}) {
    const url = new URL(path, this.baseURL);
    // 添加 CSEC 参数
    Object.entries(this.csecParams).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
    // 添加额外参数
    Object.entries(extraParams).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
    return url.toString();
  }

  /**
   * 通用 GET 请求
   */
  async get(path, params = {}) {
    try {
      const url = this.buildURL(path, params);
      const response = await fetch(url, {
        method: 'GET',
        headers: this.defaultHeaders,
        credentials: 'include' // 包含 cookies
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.checkAPIError(data);
      return data;
    } catch (error) {
      console.error(`GET ${path} 失败:`, error);
      throw error;
    }
  }

  /**
   * 通用 POST 请求
   */
  async post(path, body = {}, params = {}) {
    try {
      const url = this.buildURL(path, params);
      const response = await fetch(url, {
        method: 'POST',
        headers: this.defaultHeaders,
        credentials: 'include',
        body: JSON.stringify(body)
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.checkAPIError(data);
      return data;
    } catch (error) {
      console.error(`POST ${path} 失败:`, error);
      throw error;
    }
  }

  /**
   * 检查 API 响应错误
   */
  checkAPIError(data) {
    const code = data.code;
    if (code !== undefined && code !== 0) {
      const msg = data.msg || data.message || '未知错误';
      throw new Error(`API 错误 ${code}: ${msg}`);
    }
  }

  /**
   * goldengateway 通用查询
   * 需要在页面上下文执行 (mtgsig 签名)
   */
  async queryGoldenGateway(viewCode, param) {
    return await this.post('/goldengateway/empower/generic/table/query', {
      viewCode,
      param
    });
  }

  /**
   * 获取今日日期字符串
   */
  getTodayString() {
    const today = new Date();
    return today.getFullYear().toString() +
           (today.getMonth() + 1).toString().padStart(2, '0') +
           today.getDate().toString().padStart(2, '0');
  }

  /**
   * 构建默认的 goldengateway 参数
   */
  buildGoldenParam(extra = {}) {
    const today = this.getTodayString();
    return {
      poiIds: [], // 将由 content script 填充实际门店 ID
      channelIds: [],
      dateType: 'd', // d=日, w=周, m=月
      beginDate: today,
      endDate: today,
      page: 1,
      pageSize: 50,
      order: '',
      isSelectAllPoi: false,
      ...extra
    };
  }
}

/**
 * 具体的数据获取器类
 */
class DataFetchers {
  constructor(apiClient) {
    this.api = apiClient;
    this.tenantId = DEFAULT_CONFIG.defaultTenantId;
    this.poiIds = DEFAULT_CONFIG.defaultPoiIds;
  }

  /**
   * 更新租户和门店配置
   */
  updateConfig(tenantId, poiIds) {
    this.tenantId = tenantId;
    this.poiIds = poiIds;
  }

  /**
   * 获取订单数据
   */
  async fetchOrders() {
    // TODO: 需要确认正确的订单 viewCode
    const param = this.api.buildGoldenParam({
      poiIds: this.poiIds,
      pageSize: 100 // 订单数据可能较多
    });

    const response = await this.api.queryGoldenGateway(
      'homepage_not_erp_poi_rank_table_view', // 需要确认
      param
    );

    return response.data?.list || [];
  }

  /**
   * 获取商品数据 - 优先使用 qnh-gw3 API
   */
  async fetchProducts() {
    try {
      // 策略 1: qnh-gw3 SPU API (需要 h5guard 签名)
      const response = await this.api.post('/qnh-gw3/api/product/tenant/page-query', {
        page: 1,
        pageSize: 50,
        current: 1
      });

      return response.data?.list || [];
    } catch (error) {
      console.warn('qnh-gw3 商品 API 失败，fallback 到 goldengateway:', error);

      // 策略 2: goldengateway 热销商品 (fallback)
      const param = this.api.buildGoldenParam({
        poiIds: this.poiIds,
        pageSize: 100
      });

      const response = await this.api.queryGoldenGateway(
        'homepage_hotsale_goods_rank_table_view_new',
        param
      );

      return response.data?.list || [];
    }
  }

  /**
   * 获取经营指标数据
   */
  async fetchMetrics() {
    const results = {};
    const viewCodes = DATA_SOURCES.metrics.viewCodes;

    for (const viewCode of viewCodes) {
      try {
        const param = this.api.buildGoldenParam({
          poiIds: this.poiIds
        });

        const response = await this.api.queryGoldenGateway(viewCode, param);
        results[viewCode] = response.data || {};
      } catch (error) {
        console.error(`获取指标 ${viewCode} 失败:`, error);
        results[viewCode] = { error: error.message };
      }
    }

    return [results]; // 统一返回数组格式
  }

  /**
   * 获取渠道分布数据
   */
  async fetchTraffic() {
    const param = this.api.buildGoldenParam({
      poiIds: this.poiIds,
      pageSize: 100
    });

    const response = await this.api.queryGoldenGateway(
      'homepage_channel_distribute_table_view_new',
      param
    );

    return response.data?.list || [];
  }

  /**
   * 获取 IM 消息历史
   */
  async fetchIMMessages() {
    try {
      // 先获取会话列表
      const chatListResponse = await fetch(`${this.api.neixinBaseURL}/msg/api/pub/v1/chatlist`, {
        method: 'POST',
        headers: this.api.defaultHeaders,
        credentials: 'include',
        body: JSON.stringify({})
      });

      if (!chatListResponse.ok) {
        throw new Error(`获取会话列表失败: ${chatListResponse.status}`);
      }

      const chatList = await chatListResponse.json();
      const chats = chatList.data?.list || [];

      // 获取近期消息
      const messages = [];
      const endTime = Date.now();
      const startTime = endTime - (24 * 60 * 60 * 1000); // 最近24小时

      for (const chat of chats.slice(0, 10)) { // 最多处理10个会话
        try {
          const historyResponse = await fetch(`${this.api.neixinBaseURL}/msg/api/pub/v3/history/chat/range`, {
            method: 'POST',
            headers: this.api.defaultHeaders,
            credentials: 'include',
            body: JSON.stringify({
              chatId: chat.chatId,
              startTime,
              endTime
            })
          });

          if (historyResponse.ok) {
            const history = await historyResponse.json();
            if (history.data?.list) {
              messages.push(...history.data.list);
            }
          }
        } catch (error) {
          console.error(`获取会话 ${chat.chatId} 历史失败:`, error);
        }
      }

      return messages;
    } catch (error) {
      console.error('获取 IM 消息失败:', error);
      return [];
    }
  }

  /**
   * 获取 IM 会话数据
   */
  async fetchIMSessions() {
    try {
      const response = await fetch(`${this.api.neixinBaseURL}/msg/api/pub/v1/chatlist`, {
        method: 'POST',
        headers: this.api.defaultHeaders,
        credentials: 'include',
        body: JSON.stringify({})
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      return data.data?.list || [];
    } catch (error) {
      console.error('获取 IM 会话失败:', error);
      return [];
    }
  }

  /**
   * 获取库存数据 - 暂时返回空数据，需要找到对应 API
   */
  async fetchInventory() {
    console.warn('库存数据 API 暂未实现');
    return [];
  }

  /**
   * 获取财务数据 - 暂时返回空数据，需要找到对应 API
   */
  async fetchFinance() {
    console.warn('财务数据 API 暂未实现');
    return [];
  }

  /**
   * 获取退款数据 - 暂时返回空数据，需要找到对应 API
   */
  async fetchRefunds() {
    console.warn('退款数据 API 暂未实现');
    return [];
  }
}

// 全局实例
window.qnhAPIClient = new QNHAPIClient();
window.dataFetchers = new DataFetchers(window.qnhAPIClient);
