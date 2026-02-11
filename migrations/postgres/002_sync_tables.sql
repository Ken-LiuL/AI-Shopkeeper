-- 牵牛花数据同步表
-- 版本: 2.0
-- 日期: 2026-02-12

-- ========== 同步状态 ==========

CREATE TABLE IF NOT EXISTS sync_state (
    syncer_name VARCHAR(64) PRIMARY KEY,
    last_full_sync TIMESTAMP,
    last_incremental_sync TIMESTAMP,
    last_sync_status VARCHAR(20) DEFAULT 'idle',  -- idle/running/success/failed
    last_sync_error TEXT,
    records_synced INT DEFAULT 0,
    last_sync_duration_ms INT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ========== 牵牛花商品 ==========

CREATE TABLE IF NOT EXISTS qnh_products (
    id SERIAL PRIMARY KEY,
    spu_id VARCHAR(64) NOT NULL,
    sku_id VARCHAR(64),
    tenant_id VARCHAR(32) DEFAULT '1011766',
    name VARCHAR(500) NOT NULL,
    barcode VARCHAR(64),
    category VARCHAR(200),
    brand VARCHAR(200),
    spec VARCHAR(500),           -- 规格
    unit VARCHAR(32),            -- 单位
    cost_price DECIMAL(10,2),
    retail_price DECIMAL(10,2),
    channel_price JSONB,         -- {"meituan": 29.9, "eleme": 29.9, "jddj": 29.9}
    status VARCHAR(32),          -- 上架/下架/停用
    channel_status JSONB,        -- {"meituan": "on", "eleme": "off"}
    image_url TEXT,
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(spu_id, sku_id)
);

CREATE INDEX IF NOT EXISTS idx_qnh_products_spu ON qnh_products(spu_id);
CREATE INDEX IF NOT EXISTS idx_qnh_products_barcode ON qnh_products(barcode);
CREATE INDEX IF NOT EXISTS idx_qnh_products_synced ON qnh_products(synced_at);

-- ========== 牵牛花订单 ==========

CREATE TABLE IF NOT EXISTS qnh_orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    tenant_id VARCHAR(32) DEFAULT '1011766',
    channel VARCHAR(32),         -- meituan/eleme/jddj
    store_name VARCHAR(200),
    total_amount DECIMAL(10,2),
    paid_amount DECIMAL(10,2),
    status VARCHAR(32),
    order_time TIMESTAMP,
    delivery_fee DECIMAL(10,2),
    packaging_fee DECIMAL(10,2),
    customer_phone_suffix VARCHAR(8),
    items JSONB,                 -- [{name, qty, price, sku_id}]
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qnh_orders_time ON qnh_orders(order_time);
CREATE INDEX IF NOT EXISTS idx_qnh_orders_channel ON qnh_orders(channel);
CREATE INDEX IF NOT EXISTS idx_qnh_orders_synced ON qnh_orders(synced_at);

-- ========== 每日经营指标 ==========

CREATE TABLE IF NOT EXISTS qnh_daily_metrics (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(32) DEFAULT '1011766',
    metric_date DATE NOT NULL,
    channel VARCHAR(32),         -- NULL=全渠道
    store_id VARCHAR(32),
    -- 收入指标
    valid_order_amount DECIMAL(12,2),
    valid_order_count INT,
    avg_order_value DECIMAL(10,2),
    net_profit DECIMAL(12,2),
    online_gross_profit DECIMAL(12,2),
    -- 成本指标
    paid_amount DECIMAL(12,2),
    paid_avg_order_value DECIMAL(10,2),
    product_sales_amount DECIMAL(12,2),
    packaging_fee DECIMAL(10,2),
    delivery_fee DECIMAL(10,2),
    customer_count INT,
    -- 运营指标
    product_sell_through_rate DECIMAL(5,2),
    overtime_rate DECIMAL(5,2),
    stockout_refund_rate DECIMAL(5,2),
    turnover_days DECIMAL(8,2),
    stockout_loss DECIMAL(12,2),
    -- 渠道分布
    channel_distribution JSONB,  -- {"meituan": 7, "eleme": 7, "jddj": 1}
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(metric_date, channel, store_id)
);

CREATE INDEX IF NOT EXISTS idx_qnh_metrics_date ON qnh_daily_metrics(metric_date);

-- ========== 库存快照 ==========

CREATE TABLE IF NOT EXISTS qnh_inventory (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(32) DEFAULT '1011766',
    spu_id VARCHAR(64),
    sku_id VARCHAR(64),
    barcode VARCHAR(64),
    product_name VARCHAR(500),
    current_stock INT,
    available_stock INT,
    locked_stock INT,
    cost_price DECIMAL(10,2),
    stock_value DECIMAL(12,2),
    warehouse VARCHAR(100),
    snapshot_time TIMESTAMP DEFAULT NOW(),
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qnh_inventory_sku ON qnh_inventory(sku_id);
CREATE INDEX IF NOT EXISTS idx_qnh_inventory_time ON qnh_inventory(snapshot_time);

-- ========== 流量数据 ==========

CREATE TABLE IF NOT EXISTS qnh_traffic (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(32) DEFAULT '1011766',
    traffic_date DATE NOT NULL,
    channel VARCHAR(32),
    spu_id VARCHAR(64),
    product_name VARCHAR(500),
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    click_rate DECIMAL(5,4),
    orders INT DEFAULT 0,
    conversion_rate DECIMAL(5,4),
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(traffic_date, channel, spu_id)
);

CREATE INDEX IF NOT EXISTS idx_qnh_traffic_date ON qnh_traffic(traffic_date);

-- ========== 评价数据 ==========

CREATE TABLE IF NOT EXISTS qnh_reviews (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(32) DEFAULT '1011766',
    review_id VARCHAR(64) UNIQUE,
    order_id VARCHAR(64),
    channel VARCHAR(32),
    rating INT,                  -- 1-5
    content TEXT,
    reply TEXT,
    review_time TIMESTAMP,
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qnh_reviews_time ON qnh_reviews(review_time);
CREATE INDEX IF NOT EXISTS idx_qnh_reviews_rating ON qnh_reviews(rating);
