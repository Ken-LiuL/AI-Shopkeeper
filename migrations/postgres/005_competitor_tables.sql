-- 005_competitor_tables.sql
-- 竞品数据表：存储通过 RPC 设备采集的美团竞品数据

-- 竞品店铺
CREATE TABLE IF NOT EXISTS competitor_stores (
    store_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    rating      REAL DEFAULT 0,
    monthly_sales INTEGER DEFAULT 0,
    distance_km REAL DEFAULT 0,
    lat         REAL DEFAULT 0,
    lng         REAL DEFAULT 0,
    category    TEXT DEFAULT '',
    last_synced TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_stores_category ON competitor_stores(category);
CREATE INDEX IF NOT EXISTS idx_competitor_stores_distance ON competitor_stores(distance_km);
CREATE INDEX IF NOT EXISTS idx_competitor_stores_synced ON competitor_stores(last_synced);

-- 竞品商品
CREATE TABLE IF NOT EXISTS competitor_products (
    product_id  TEXT PRIMARY KEY,
    store_id    TEXT DEFAULT '' REFERENCES competitor_stores(store_id) ON DELETE SET DEFAULT,
    name        TEXT NOT NULL,
    price       REAL DEFAULT 0,
    monthly_sales INTEGER DEFAULT 0,
    rating      REAL DEFAULT 0,
    category    TEXT DEFAULT '',
    last_synced TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_products_store ON competitor_products(store_id);
CREATE INDEX IF NOT EXISTS idx_competitor_products_category ON competitor_products(category);
CREATE INDEX IF NOT EXISTS idx_competitor_products_sales ON competitor_products(monthly_sales DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_products_synced ON competitor_products(last_synced);

-- 搜索关键词统计
CREATE TABLE IF NOT EXISTS competitor_keywords (
    keyword      TEXT PRIMARY KEY,
    search_volume INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,
    avg_price    REAL DEFAULT 0,
    last_synced  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitor_keywords_volume ON competitor_keywords(search_volume DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_keywords_synced ON competitor_keywords(last_synced);
