-- AI Store Manager - Initial PostgreSQL Schema
-- Version: 001
-- Date: 2026-02-11

BEGIN;

-- ============================================================
-- 商品表
-- ============================================================
CREATE TABLE products (
    product_id   VARCHAR(32) PRIMARY KEY,
    name         VARCHAR(200) NOT NULL,
    barcode      VARCHAR(50),
    category     VARCHAR(100),
    brand        VARCHAR(100),
    description  TEXT,
    cost_price   DECIMAL(10, 2),
    retail_price DECIMAL(10, 2),
    stock        INTEGER      DEFAULT 0,
    monthly_sales INTEGER     DEFAULT 0,
    status       VARCHAR(20)  DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'delisted')),
    created_at   TIMESTAMPTZ  DEFAULT now(),
    updated_at   TIMESTAMPTZ  DEFAULT now()
);

CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_barcode  ON products (barcode);
CREATE INDEX idx_products_status   ON products (status);

-- ============================================================
-- 订单表
-- ============================================================
CREATE TABLE orders (
    order_id              VARCHAR(50) PRIMARY KEY,
    platform              VARCHAR(20)  DEFAULT 'meituan',
    customer_phone_suffix VARCHAR(4),
    total_amount          DECIMAL(10, 2),
    status                VARCHAR(20),
    order_time            TIMESTAMPTZ,
    delivery_address_type VARCHAR(20),
    created_at            TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_orders_time   ON orders (order_time);
CREATE INDEX idx_orders_status ON orders (status);

-- ============================================================
-- 订单明细表
-- ============================================================
CREATE TABLE order_items (
    id         SERIAL PRIMARY KEY,
    order_id   VARCHAR(50)   NOT NULL REFERENCES orders (order_id),
    product_id VARCHAR(32)   NOT NULL REFERENCES products (product_id),
    quantity   INTEGER       NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMPTZ   DEFAULT now()
);

CREATE INDEX idx_order_items_order   ON order_items (order_id);
CREATE INDEX idx_order_items_product ON order_items (product_id);

-- ============================================================
-- 竞品店铺表
-- ============================================================
CREATE TABLE competitor_stores (
    competitor_id VARCHAR(50) PRIMARY KEY,
    name          VARCHAR(200),
    platform      VARCHAR(20)  DEFAULT 'meituan',
    distance_km   DECIMAL(4, 2),
    rating        DECIMAL(2, 1),
    review_count  INTEGER,
    threat_level  VARCHAR(20)
        CHECK (threat_level IN ('high', 'medium', 'low')),
    last_crawl_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 竞品商品表
-- ============================================================
CREATE TABLE competitor_products (
    id            SERIAL PRIMARY KEY,
    competitor_id VARCHAR(50)   NOT NULL REFERENCES competitor_stores (competitor_id),
    product_name  VARCHAR(200),
    barcode       VARCHAR(50),
    price         DECIMAL(10, 2),
    monthly_sales INTEGER,
    is_stockout   BOOLEAN DEFAULT FALSE,
    crawled_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_comp_products_competitor ON competitor_products (competitor_id);
CREATE INDEX idx_comp_products_barcode    ON competitor_products (barcode);

-- ============================================================
-- 预警表
-- ============================================================
CREATE TABLE alerts (
    alert_id           VARCHAR(50) PRIMARY KEY,
    product_id         VARCHAR(32) REFERENCES products (product_id),
    alert_type         VARCHAR(50)  NOT NULL,
    severity           VARCHAR(20)  NOT NULL
        CHECK (severity IN ('critical', 'warning', 'info')),
    detection_method   VARCHAR(30),
    metrics            JSONB,
    root_cause         TEXT,
    recommended_action TEXT,
    status             VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'acknowledged', 'resolved', 'ignored')),
    created_at         TIMESTAMPTZ DEFAULT now(),
    resolved_at        TIMESTAMPTZ
);

CREATE INDEX idx_alerts_product ON alerts (product_id);
CREATE INDEX idx_alerts_status  ON alerts (status);
CREATE INDEX idx_alerts_created ON alerts (created_at DESC);
CREATE INDEX idx_alerts_severity ON alerts (severity);

-- ============================================================
-- 选品运行记录表
-- ============================================================
CREATE TABLE selection_runs (
    run_id              VARCHAR(50) PRIMARY KEY,
    trigger_type        VARCHAR(20),
    trigger_params      JSONB,
    status              VARCHAR(20)
        CHECK (status IN ('running', 'completed', 'failed')),
    recommendations     JSONB,
    total_opportunities INTEGER,
    total_llm_tokens    INTEGER,
    total_cost_usd      DECIMAL(10, 4),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 套餐表
-- ============================================================
CREATE TABLE bundles (
    bundle_id       VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100),
    tagline         VARCHAR(100),
    products        JSONB,
    original_price  DECIMAL(10, 2),
    bundle_price    DECIMAL(10, 2),
    discount_percent DECIMAL(4, 2),
    confidence      DECIMAL(3, 2),
    lift            DECIMAL(4, 2),
    status          VARCHAR(20) DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'archived')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 销量历史表（Prophet 训练数据源）
-- ============================================================
CREATE TABLE sales_history (
    id               SERIAL PRIMARY KEY,
    product_id       VARCHAR(32) NOT NULL REFERENCES products (product_id),
    sale_date        DATE        NOT NULL,
    quantity         INTEGER     NOT NULL DEFAULT 0,
    revenue          DECIMAL(10, 2),
    is_promotion     BOOLEAN DEFAULT FALSE,
    is_weather_event BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (product_id, sale_date)
);

CREATE INDEX idx_sales_history_product_date ON sales_history (product_id, sale_date);

-- ============================================================
-- Prophet 模型元数据表
-- ============================================================
CREATE TABLE prophet_models (
    product_id       VARCHAR(32) PRIMARY KEY REFERENCES products (product_id),
    model_data       BYTEA,
    training_samples INTEGER,
    last_trained_at  TIMESTAMPTZ,
    metrics          JSONB,
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 参数版本历史表
-- ============================================================
CREATE TABLE parameter_versions (
    version_id       VARCHAR(50)  PRIMARY KEY,
    parameter_type   VARCHAR(50),
    parameter_values JSONB,
    learning_method  VARCHAR(50),
    training_samples INTEGER,
    validation_score DECIMAL(5, 4),
    status           VARCHAR(20) DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'ab_testing', 'active', 'archived')),
    created_at       TIMESTAMPTZ DEFAULT now(),
    activated_at     TIMESTAMPTZ
);

-- ============================================================
-- 选品效果追踪表
-- ============================================================
CREATE TABLE recommendation_outcomes (
    id                  SERIAL PRIMARY KEY,
    recommendation_id   VARCHAR(50),
    product_keyword     VARCHAR(100),
    features            JSONB,
    predicted_score     DECIMAL(5, 2),
    was_purchased       BOOLEAN,
    purchase_date       DATE,
    actual_monthly_sales INTEGER,
    actual_margin       DECIMAL(5, 4),
    outcome_score       DECIMAL(5, 4),
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- updated_at 自动触发器
-- ============================================================
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMIT;
