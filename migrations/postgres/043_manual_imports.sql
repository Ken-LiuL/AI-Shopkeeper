-- 043_manual_imports.sql
-- 手动 Excel 导入支持：导入记录、兼容列、派生数据集

CREATE TABLE IF NOT EXISTS manual_import_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    import_type VARCHAR(32) NOT NULL,
    filename TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    detected_sheets TEXT[] DEFAULT '{}',
    total_rows INTEGER DEFAULT 0,
    imported_rows INTEGER DEFAULT 0,
    skipped_rows INTEGER DEFAULT 0,
    quality_score NUMERIC(5,2) DEFAULT 0,
    quality_report JSONB DEFAULT '{}'::jsonb,
    import_summary JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_manual_import_runs_created
    ON manual_import_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_manual_import_runs_type
    ON manual_import_runs(import_type, created_at DESC);

ALTER TABLE products ADD COLUMN IF NOT EXISTS spu_id VARCHAR(64);
ALTER TABLE products ADD COLUMN IF NOT EXISTS sku_id VARCHAR(64);
ALTER TABLE products ADD COLUMN IF NOT EXISTS store_id VARCHAR(32);
ALTER TABLE products ADD COLUMN IF NOT EXISTS upc_code VARCHAR(64);
ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'manual_import';
ALTER TABLE products ADD COLUMN IF NOT EXISTS extra JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_products_sku_id ON products(sku_id);
CREATE INDEX IF NOT EXISTS idx_products_spu_id ON products(spu_id);
CREATE INDEX IF NOT EXISTS idx_products_store_id ON products(store_id);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS store_id VARCHAR(32);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_name VARCHAR(128);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_paid DECIMAL(10, 2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_date DATE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS commission DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_fee DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS merchant_discount DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS day_seq INTEGER;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS items JSONB DEFAULT '{"products": []}'::jsonb;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS source VARCHAR(32) DEFAULT 'manual_import';

CREATE INDEX IF NOT EXISTS idx_orders_store_id ON orders(store_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);

ALTER TABLE qnh_inventory ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0;
ALTER TABLE qnh_inventory ADD COLUMN IF NOT EXISTS store_id VARCHAR(32);
ALTER TABLE qnh_inventory ADD COLUMN IF NOT EXISTS store_name VARCHAR(200);
ALTER TABLE qnh_inventory ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_qnh_inventory_store_sku ON qnh_inventory(store_id, sku_id);
CREATE INDEX IF NOT EXISTS idx_qnh_inventory_stock ON qnh_inventory(stock);

ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0;
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS monthly_sales INTEGER DEFAULT 0;

ALTER TABLE qnh_dataset_records ADD COLUMN IF NOT EXISTS dataset VARCHAR(100);
ALTER TABLE qnh_dataset_records ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE qnh_dataset_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_qnh_dataset_records_dataset
    ON qnh_dataset_records(dataset, synced_at DESC);
