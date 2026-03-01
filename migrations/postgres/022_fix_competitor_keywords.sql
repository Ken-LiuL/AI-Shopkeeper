-- 022_fix_competitor_keywords.sql
-- Add missing competitor_keywords table

CREATE TABLE IF NOT EXISTS competitor_keywords (
    keyword      TEXT PRIMARY KEY,
    search_volume INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,
    avg_price    REAL DEFAULT 0,
    last_synced  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_keywords_volume ON competitor_keywords(search_volume DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_keywords_synced ON competitor_keywords(last_synced);

-- Add sample data for testing
INSERT INTO competitor_keywords (keyword, search_volume, result_count, avg_price)
VALUES
    ('感冒药', 1200, 45, 25.5),
    ('维生素', 800, 32, 15.8),
    ('创可贴', 600, 28, 8.9)
ON CONFLICT (keyword) DO NOTHING;

-- Add sample competitor stores if they don't exist
INSERT INTO competitor_stores (store_id, name, rating, monthly_sales, category)
VALUES
    ('test_store_1', '测试药店A', 4.5, 1500, 'pharmacy'),
    ('test_store_2', '测试药店B', 4.2, 1200, 'pharmacy')
ON CONFLICT (store_id) DO NOTHING;

-- Add sample competitor products if they don't exist
INSERT INTO competitor_products (product_id, store_id, name, price, monthly_sales, rating, category)
VALUES
    ('cp_1', 'test_store_1', '感冒灵颗粒', 18.5, 200, 4.3, 'cold_medicine'),
    ('cp_2', 'test_store_2', '维生素C片', 12.8, 150, 4.1, 'vitamins')
ON CONFLICT (product_id) DO NOTHING;
