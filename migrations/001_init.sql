-- AI Store Manager 初始化数据库 Schema
-- 版本: 1.0
-- 日期: 2026-02-11

-- ========== 商品相关 ==========

CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    barcode VARCHAR(50),
    category VARCHAR(100),
    brand VARCHAR(100),
    description TEXT,
    cost_price DECIMAL(10, 2),
    retail_price DECIMAL(10, 2),
    stock INT DEFAULT 0,
    monthly_sales INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);

-- ========== 订单相关 ==========

CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(50) PRIMARY KEY,
    platform VARCHAR(20) DEFAULT 'meituan',
    customer_phone_suffix VARCHAR(4),
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20),
    order_time TIMESTAMP,
    delivery_address_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) REFERENCES orders(order_id),
    product_id VARCHAR(32) REFERENCES products(product_id),
    quantity INT NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_order_time ON orders(order_time);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);

-- 销量统计视图/表
CREATE TABLE IF NOT EXISTS product_sales (
    id SERIAL PRIMARY KEY,
    product_id VARCHAR(32) REFERENCES products(product_id),
    sale_date DATE NOT NULL,
    quantity INT DEFAULT 0,
    revenue DECIMAL(10, 2) DEFAULT 0,
    UNIQUE(product_id, sale_date)
);

CREATE INDEX IF NOT EXISTS idx_product_sales_date ON product_sales(sale_date);

-- ========== 预警相关 ==========

CREATE TABLE IF NOT EXISTS alerts (
    alert_id VARCHAR(50) PRIMARY KEY,
    product_id VARCHAR(32),
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    detection_method VARCHAR(30),
    metrics JSONB,
    title VARCHAR(200),
    description TEXT,
    root_cause TEXT,
    suggestion TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    notification_status VARCHAR(32) DEFAULT 'not_sent',
    notification_reason TEXT,
    notification_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_product ON alerts(product_id);

CREATE TABLE IF NOT EXISTS alert_scans (
    scan_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'running',
    result JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ========== 选品相关 ==========

CREATE TABLE IF NOT EXISTS selection_runs (
    run_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'running',
    keywords TEXT[],
    categories TEXT[],
    result JSONB,
    result_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_selection_runs_status ON selection_runs(status);

-- ========== 套餐相关 ==========

CREATE TABLE IF NOT EXISTS bundles (
    bundle_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    tagline VARCHAR(100),
    products JSONB,
    original_price DECIMAL(10, 2),
    bundle_price DECIMAL(10, 2),
    discount_percent DECIMAL(5, 2),
    confidence DECIMAL(5, 4),
    lift DECIMAL(5, 2),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bundle_tasks (
    task_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'running',
    result JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP
);

-- ========== 上架相关 ==========

CREATE TABLE IF NOT EXISTS listings (
    listing_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'processing',
    source_url TEXT,
    platform VARCHAR(20),
    product_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP
);

-- ========== Prophet 模型存储 ==========

CREATE TABLE IF NOT EXISTS prophet_models (
    product_id VARCHAR(32) PRIMARY KEY,
    model_data BYTEA NOT NULL,
    trained_at TIMESTAMP DEFAULT NOW()
);

-- ========== 参数自学习相关 ==========

CREATE TABLE IF NOT EXISTS learning_weights (
    id SERIAL PRIMARY KEY,
    weights JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS adaptive_thresholds (
    name VARCHAR(100) PRIMARY KEY,
    current_value DECIMAL(10, 4) NOT NULL,
    min_value DECIMAL(10, 4),
    max_value DECIMAL(10, 4),
    update_reason TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS parameter_versions (
    version_id VARCHAR(100) PRIMARY KEY,
    param_type VARCHAR(50) NOT NULL,
    values JSONB NOT NULL,
    description TEXT,
    created_by VARCHAR(50) DEFAULT 'system',
    is_active BOOLEAN DEFAULT FALSE,
    performance_score DECIMAL(5, 2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parameter_versions_type ON parameter_versions(param_type);
CREATE INDEX IF NOT EXISTS idx_parameter_versions_active ON parameter_versions(is_active);

-- ========== 完成 ==========

SELECT 'AI Store Manager database initialized successfully' AS status;
