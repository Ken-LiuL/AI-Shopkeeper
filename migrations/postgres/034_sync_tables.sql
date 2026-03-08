-- 034_sync_tables.sql
-- 补齐 YiyaoFullSyncer / Agent 所需数据表

CREATE TABLE IF NOT EXISTS qnh_refunds (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(100),
    refund_id VARCHAR(100) UNIQUE NOT NULL,
    order_id VARCHAR(100),
    channel VARCHAR(50) DEFAULT 'meituan',
    sku_id VARCHAR(100),
    sku_name TEXT,
    refund_reason TEXT,
    refund_amount NUMERIC(10,2) DEFAULT 0,
    refund_status VARCHAR(50),
    refund_time TIMESTAMP,
    resolved_time TIMESTAMP,
    extra JSONB,
    synced_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qnh_promotions (
    id SERIAL PRIMARY KEY,
    promotion_id VARCHAR(100) UNIQUE NOT NULL,
    promotion_type VARCHAR(50),
    title TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    product_ids JSONB,
    discount_rule TEXT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qnh_daily_metrics (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    order_count INTEGER DEFAULT 0,
    gmv NUMERIC(12,2) DEFAULT 0,
    actual_revenue NUMERIC(12,2) DEFAULT 0,
    avg_order_value NUMERIC(10,2) DEFAULT 0,
    refund_count INTEGER DEFAULT 0,
    refund_rate NUMERIC(5,4) DEFAULT 0,
    new_customers INTEGER DEFAULT 0,
    synced_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qnh_dataset_records (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(12,2),
    source VARCHAR(50) DEFAULT 'yiyao_sync',
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(date, metric_name)
);

CREATE TABLE IF NOT EXISTS qnh_sales_history (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    spu_id VARCHAR(100) NOT NULL,
    product_name TEXT,
    quantity_sold INTEGER DEFAULT 0,
    revenue NUMERIC(12,2) DEFAULT 0,
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(date, spu_id)
);

CREATE TABLE IF NOT EXISTS qnh_review_analysis (
    id SERIAL PRIMARY KEY,
    review_id VARCHAR(100) UNIQUE,
    product_id VARCHAR(100),
    product_name TEXT,
    rating INTEGER,
    content TEXT,
    sentiment VARCHAR(20),
    keywords TEXT[],
    analyzed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qnh_refunds_order_id ON qnh_refunds(order_id);
CREATE INDEX IF NOT EXISTS idx_qnh_daily_metrics_date ON qnh_daily_metrics(date);
CREATE INDEX IF NOT EXISTS idx_qnh_dataset_records_date ON qnh_dataset_records(date);
CREATE INDEX IF NOT EXISTS idx_qnh_sales_history_date ON qnh_sales_history(date);
CREATE INDEX IF NOT EXISTS idx_qnh_review_analysis_sentiment ON qnh_review_analysis(sentiment);
