-- P0 功能支持表
-- 创建缺失的表以支持智能定价、库存管理等功能

-- 竞品价格监控表
CREATE TABLE IF NOT EXISTS competitor_products (
    id BIGSERIAL PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    competitor_name VARCHAR(100) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    previous_price DECIMAL(10, 2),
    price_change_percent DECIMAL(8, 4),
    product_url TEXT,
    category VARCHAR(100),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_products_name ON competitor_products(product_name);
CREATE INDEX IF NOT EXISTS idx_competitor_products_competitor ON competitor_products(competitor_name);
CREATE INDEX IF NOT EXISTS idx_competitor_products_updated ON competitor_products(updated_at);

-- 定价规则表
CREATE TABLE IF NOT EXISTS pricing_rules (
    rule_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    rule_type VARCHAR(50) NOT NULL, -- margin_floor, competitor_match, demand_based, etc.
    parameters JSONB NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 商品供应商信息表
CREATE TABLE IF NOT EXISTS product_suppliers (
    id BIGSERIAL PRIMARY KEY,
    product_id VARCHAR(32) REFERENCES products(product_id),
    supplier_name VARCHAR(100) NOT NULL,
    supplier_contact VARCHAR(200),
    lead_time_days INTEGER DEFAULT 7,
    min_order_qty INTEGER DEFAULT 1,
    is_primary BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_suppliers_product ON product_suppliers(product_id);

-- 补货记录表
CREATE TABLE IF NOT EXISTS restock_records (
    id BIGSERIAL PRIMARY KEY,
    product_id VARCHAR(32) REFERENCES products(product_id),
    suggested_qty INTEGER NOT NULL,
    actual_qty INTEGER,
    urgency VARCHAR(20) NOT NULL, -- high, medium, low
    supplier_name VARCHAR(100),
    order_date DATE,
    expected_arrival DATE,
    status VARCHAR(20) DEFAULT 'pending', -- pending, ordered, received
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 门店表（支持多店管理）
CREATE TABLE IF NOT EXISTS stores (
    poi_id INTEGER PRIMARY KEY,
    store_name VARCHAR(100) NOT NULL,
    address TEXT,
    store_type VARCHAR(50), -- flagship, standard, community
    opening_hours VARCHAR(50),
    manager_name VARCHAR(50),
    phone VARCHAR(20),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 插入3家店铺基础数据
INSERT INTO stores (poi_id, store_name, address, store_type, opening_hours, manager_name) VALUES
(1232550, '华康医疗器械店(主店)', '朝阳区建国路88号', '旗舰店', '08:00-22:00', '张经理'),
(1221411, '华康医疗器械店(分店A)', '海淀区中关村大街120号', '标准店', '09:00-21:00', '李经理'),
(1175006, '华康医疗器械店(分店B)', '丰台区南三环路200号', '社区店', '08:30-20:30', '王经理')
ON CONFLICT (poi_id) DO NOTHING;

-- 门店商品库存表
CREATE TABLE IF NOT EXISTS store_inventory (
    id BIGSERIAL PRIMARY KEY,
    poi_id INTEGER REFERENCES stores(poi_id),
    product_id VARCHAR(32) REFERENCES products(product_id),
    stock INTEGER DEFAULT 0,
    reserved_stock INTEGER DEFAULT 0, -- 预留库存
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(poi_id, product_id)
);

-- 商品销量分析表
CREATE TABLE IF NOT EXISTS product_sales_analysis (
    product_id VARCHAR(32) PRIMARY KEY REFERENCES products(product_id),
    daily_avg_sales DECIMAL(8, 2) DEFAULT 0,
    weekly_avg_sales DECIMAL(8, 2) DEFAULT 0,
    monthly_avg_sales DECIMAL(8, 2) DEFAULT 0,
    sales_trend VARCHAR(20) DEFAULT 'stable', -- rising, falling, stable
    seasonality_factor DECIMAL(5, 2) DEFAULT 1.0,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- AI洞察记录表
CREATE TABLE IF NOT EXISTS daily_insights (
    id BIGSERIAL PRIMARY KEY,
    analysis_date DATE NOT NULL,
    poi_id INTEGER, -- NULL表示全局洞察
    insights_data JSONB NOT NULL,
    performance_score DECIMAL(5, 2),
    key_actions TEXT[],
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_insights_date ON daily_insights(analysis_date);
CREATE INDEX IF NOT EXISTS idx_daily_insights_poi ON daily_insights(poi_id);

-- 更新products表，添加缺失字段
ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price DECIMAL(10, 2);
ALTER TABLE products ADD COLUMN IF NOT EXISTS supplier VARCHAR(100);
ALTER TABLE products ADD COLUMN IF NOT EXISTS lead_time_days INTEGER DEFAULT 7;
ALTER TABLE products ADD COLUMN IF NOT EXISTS safety_stock INTEGER DEFAULT 0;

-- 更新orders表，支持门店维度
ALTER TABLE orders ADD COLUMN IF NOT EXISTS poi_id INTEGER;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_fee DECIMAL(6, 2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS estimated_delivery_time TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS actual_delivery_time TIMESTAMPTZ;

-- 创建一些有用的视图

-- 商品销量排行视图
CREATE OR REPLACE VIEW product_sales_ranking AS
SELECT
    p.product_id,
    p.name,
    p.category,
    p.retail_price,
    p.cost_price,
    CASE
        WHEN p.cost_price > 0 THEN ROUND((p.retail_price - p.cost_price) / p.retail_price * 100, 2)
        ELSE NULL
    END as margin_percent,
    COALESCE(SUM(oi.quantity), 0) as total_sold_30d,
    COALESCE(COUNT(DISTINCT oi.order_id), 0) as order_count_30d,
    COALESCE(SUM(oi.quantity * oi.unit_price), 0) as revenue_30d
FROM products p
LEFT JOIN order_items oi ON p.product_id = oi.product_id
LEFT JOIN orders o ON oi.order_id = o.order_id AND o.order_time >= CURRENT_DATE - INTERVAL '30 days'
WHERE p.status = 'active'
GROUP BY p.product_id, p.name, p.category, p.retail_price, p.cost_price
ORDER BY total_sold_30d DESC;

-- 门店表现视图
CREATE OR REPLACE VIEW store_performance_daily AS
SELECT
    s.poi_id,
    s.store_name,
    DATE(o.order_time) as date,
    COUNT(*) as order_count,
    COALESCE(SUM(o.total_amount), 0) as gmv,
    COALESCE(AVG(o.total_amount), 0) as avg_order_value
FROM stores s
LEFT JOIN orders o ON s.poi_id = o.poi_id AND o.order_time >= CURRENT_DATE - INTERVAL '30 days'
WHERE s.is_active = true
GROUP BY s.poi_id, s.store_name, DATE(o.order_time);

-- 插入一些示例竞品数据
INSERT INTO competitor_products (product_name, competitor_name, price, category) VALUES
('电子血压计', '健康之家', 128.00, '医疗器械'),
('电子血压计', '医疗专营店', 135.00, '医疗器械'),
('血糖仪', '健康之家', 89.00, '医疗器械'),
('血糖仪', '医疗专营店', 95.00, '医疗器械'),
('体温计', '健康之家', 25.00, '医疗器械'),
('体温计', '医疗专营店', 28.00, '医疗器械'),
('轮椅', '康复设备店', 380.00, '康复设备'),
('拐杖', '康复设备店', 45.00, '康复设备')
ON CONFLICT DO NOTHING;

-- 插入一些基础定价规则
INSERT INTO pricing_rules (rule_id, name, description, rule_type, parameters) VALUES
('margin_floor_global', '全局毛利率下限', '确保所有商品毛利率不低于15%', 'margin_floor', '{"min_margin_percent": 15.0}'),
('competitor_match_default', '默认竞品对标', '价格保持在竞品平均价格的90%-105%', 'competitor_match', '{"min_ratio": 0.90, "max_ratio": 1.05}'),
('high_demand_premium', '高需求商品溢价', '月销量>100的商品可加价10%', 'demand_based', '{"sales_threshold": 100, "markup": 0.10}')
ON CONFLICT (rule_id) DO NOTHING;

SELECT 'P0 features support tables created successfully' as status;
