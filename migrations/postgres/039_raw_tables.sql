-- 039: Create missing raw data tables
BEGIN;

CREATE TABLE IF NOT EXISTS qnh_orders_raw (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(100),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qnh_orders_raw_created ON qnh_orders_raw(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qnh_orders_raw_order ON qnh_orders_raw(order_id);

CREATE TABLE IF NOT EXISTS qnh_store_metrics_raw (
    id SERIAL PRIMARY KEY,
    raw_data JSONB,
    metric_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qnh_metrics_raw_created ON qnh_store_metrics_raw(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qnh_metrics_raw_date ON qnh_store_metrics_raw(metric_date);

CREATE TABLE IF NOT EXISTS qnh_reviews_raw (
    id SERIAL PRIMARY KEY,
    review_id VARCHAR(100),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qnh_reviews_raw_created ON qnh_reviews_raw(created_at DESC);

-- store_daily_metrics (structured, for reports/dashboard)
CREATE TABLE IF NOT EXISTS store_daily_metrics (
    id SERIAL PRIMARY KEY,
    metric_date DATE NOT NULL,
    transaction_volume INTEGER DEFAULT 0,
    deal_amount DECIMAL(12,2) DEFAULT 0,
    refund_count INTEGER DEFAULT 0,
    total_customers INTEGER DEFAULT 0,
    new_customers INTEGER DEFAULT 0,
    exposure_uv INTEGER DEFAULT 0,
    commission_amount DECIMAL(12,2) DEFAULT 0,
    settlement_amount DECIMAL(12,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_store_daily_date ON store_daily_metrics(metric_date DESC);

COMMIT;
