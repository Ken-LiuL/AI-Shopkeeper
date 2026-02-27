/**
 * 数据源配置 - 定义各数据源的同步频率、优先级和获取器
 */
const DATA_SOURCES = {
  // 高频数据源 (5分钟)
  orders: {
    interval: 5 * 60 * 1000, // 5 分钟
    priority: 'high',
    fetcher: 'fetchOrders',
    source: 'orders',
    description: '订单数据',
    viewCode: 'homepage_not_erp_poi_rank_table_view', // 需要根据实际情况调整
    enabled: true
  },

  // 中频数据源 (15分钟)
  inventory: {
    interval: 15 * 60 * 1000, // 15 分钟
    priority: 'medium',
    fetcher: 'fetchInventory',
    source: 'inventory',
    description: '库存数据',
    enabled: true
  },

  im_messages: {
    interval: 15 * 60 * 1000, // 15 分钟
    priority: 'medium',
    fetcher: 'fetchIMMessages',
    source: 'im_history',
    description: '客服消息',
    enabled: true
  },

  // 低频数据源 (1小时)
  products: {
    interval: 60 * 60 * 1000, // 1 小时
    priority: 'low',
    fetcher: 'fetchProducts',
    source: 'products',
    description: '商品数据',
    enabled: true
  },

  metrics: {
    interval: 60 * 60 * 1000, // 1 小时
    priority: 'low',
    fetcher: 'fetchMetrics',
    source: 'metrics',
    description: '经营指标',
    viewCodes: [
      'homepage_business_overview_table_view_new',
      'homepage_hotsale_goods_rank_table_view_new',
      'homepage_channel_distribute_table_view_new',
      'homepage_customer_consume_rank_table_view_new'
    ],
    enabled: true
  },

  traffic: {
    interval: 60 * 60 * 1000, // 1 小时
    priority: 'low',
    fetcher: 'fetchTraffic',
    source: 'traffic',
    description: '流量数据',
    enabled: true
  },

  im_sessions: {
    interval: 60 * 60 * 1000, // 1 小时
    priority: 'low',
    fetcher: 'fetchIMSessions',
    source: 'im_sessions',
    description: '客服会话',
    enabled: true
  },

  // 每日数据源 (24小时)
  finance: {
    interval: 24 * 60 * 60 * 1000, // 24 小时
    priority: 'daily',
    fetcher: 'fetchFinance',
    source: 'finance',
    description: '财务数据',
    enabled: true
  },

  refunds: {
    interval: 24 * 60 * 60 * 1000, // 24 小时
    priority: 'daily',
    fetcher: 'fetchRefunds',
    source: 'refunds',
    description: '退款数据',
    enabled: true
  }
};

// 默认配置
const DEFAULT_CONFIG = {
  backendUrl: 'https://ai-shopkeeper-kk.fly.dev',
  apiKey: '',
  retryAttempts: 3,
  retryDelay: 5000, // 5 秒
  batchSize: 50,

  // CSEC 安全参数 (QNH API 必需)
  csecParams: {
    yodaReady: 'h5',
    csecplatform: '4',
    csecversion: '4.2.0'
  },

  // 默认门店配置 (需要从实际登录获取)
  defaultTenantId: '1011766',
  defaultPoiIds: [1175006, 1221411, 1232550]
};

// 导出配置 (用于其他模块)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { DATA_SOURCES, DEFAULT_CONFIG };
}
