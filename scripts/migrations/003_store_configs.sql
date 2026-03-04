CREATE TABLE IF NOT EXISTS store_configs (
    id SERIAL PRIMARY KEY,
    store_name VARCHAR(200) NOT NULL,
    platform VARCHAR(50) NOT NULL DEFAULT 'meituan_yiyao',
    poi_id VARCHAR(50),
    account VARCHAR(100),
    password_encrypted VARCHAR(500),
    cookie_json TEXT,
    wm_poi_id VARCHAR(50),
    region_id VARCHAR(50),
    region_version VARCHAR(50),
    sync_status VARCHAR(20) DEFAULT 'active',
    last_sync_at TIMESTAMP,
    last_sync_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS upc_code VARCHAR(64);
