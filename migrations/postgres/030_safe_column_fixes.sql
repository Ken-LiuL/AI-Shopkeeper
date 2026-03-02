-- 030: Safe column fixes - 安全地添加缺失的列

-- 1. qnh_products表添加必要列
ALTER TABLE qnh_products
    ADD COLUMN IF NOT EXISTS stock_num INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 更新stock_num = stock如果stock_num为空
UPDATE qnh_products
SET stock_num = COALESCE(stock, 0)
WHERE stock_num IS NULL OR stock_num = 0;

-- 2. competitor_products表确保有必要列
ALTER TABLE competitor_products
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 确保competitor_name列存在且有值
UPDATE competitor_products
SET competitor_name = COALESCE(store_id, 'unknown')
WHERE competitor_name IS NULL OR competitor_name = '';

-- 3. 确保orders_summary表有足够的演示数据
INSERT INTO orders_summary (order_id, product_id, product_name, category, quantity, price, date)
SELECT
    'demo-' || generate_random_uuid()::TEXT,
    spu_id,
    name,
    COALESCE(category, '医疗器械'),
    '1',
    COALESCE(retail_price, 0)::TEXT,
    CURRENT_DATE - (random() * 30)::INTEGER
FROM qnh_products
WHERE status = '在售'
  AND NOT EXISTS (SELECT 1 FROM orders_summary LIMIT 5)
LIMIT 20;

-- 4. 其他表的安全列添加
ALTER TABLE qnh_orders
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 5. 创建需要的索引（如果不存在）
CREATE INDEX IF NOT EXISTS idx_qnh_products_stock_num ON qnh_products(stock_num);
CREATE INDEX IF NOT EXISTS idx_qnh_products_updated ON qnh_products(updated_at);
CREATE INDEX IF NOT EXISTS idx_competitor_products_updated ON competitor_products(updated_at);

SELECT 'Safe column fixes applied successfully' AS status;
