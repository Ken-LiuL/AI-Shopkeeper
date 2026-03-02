-- 028: Fix missing columns and tables

-- competitor_products may have been created by 005 without competitor_name
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS competitor_name VARCHAR(100);
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS product_name VARCHAR(200);
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS previous_price DECIMAL(10, 2);
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS price_change_percent DECIMAL(8, 4);
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS product_url TEXT;
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- Backfill competitor_name from store name if null
UPDATE competitor_products SET competitor_name = store_id WHERE competitor_name IS NULL AND store_id IS NOT NULL;
UPDATE competitor_products SET product_name = name WHERE product_name IS NULL AND name IS NOT NULL;

-- qnh_products: add stock column if missing
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0;
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS reserved_stock INTEGER DEFAULT 0;
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS safety_stock INTEGER DEFAULT 0;

-- orders_summary table (used by pricing and competitor_data_service)
CREATE TABLE IF NOT EXISTS orders_summary (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(100),
    product_id VARCHAR(100),
    product_name VARCHAR(500),
    category VARCHAR(200),
    quantity VARCHAR(32) DEFAULT '1',
    price VARCHAR(32) DEFAULT '0',
    date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_summary_date ON orders_summary(date);
CREATE INDEX IF NOT EXISTS idx_orders_summary_product ON orders_summary(product_id);
