-- 027: 商家同步 Cookie 管理表
-- 商家可以通过 API 提交自己的 QNH Cookie，由系统负责同步

CREATE TABLE IF NOT EXISTS merchant_sync_cookies (
    id SERIAL PRIMARY KEY,
    merchant_id VARCHAR(100) NOT NULL DEFAULT 'default',
    cookie_json JSONB NOT NULL,          -- {"key": "value", ...}
    cookie_string TEXT,                  -- 原始 cookie 字符串（备用）
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_verified_at TIMESTAMP,
    last_sync_at TIMESTAMP,
    last_sync_status VARCHAR(50),        -- 'success' | 'failed' | 'running'
    last_sync_error TEXT,
    records_synced_total INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS merchant_sync_cookies_merchant_active
    ON merchant_sync_cookies (merchant_id)
    WHERE is_active = true;

-- 同步状态聚合视图
CREATE OR REPLACE VIEW v_sync_dashboard AS
SELECT
    msc.merchant_id,
    msc.last_verified_at,
    msc.last_sync_at,
    msc.last_sync_status,
    msc.last_sync_error,
    msc.records_synced_total,
    msc.updated_at AS cookie_updated_at,
    (SELECT COUNT(*) FROM qnh_products WHERE synced_at > NOW() - INTERVAL '24 hours') AS products_synced_24h,
    (SELECT MAX(synced_at) FROM qnh_products) AS last_product_sync
FROM merchant_sync_cookies msc
WHERE msc.is_active = true;

COMMENT ON TABLE merchant_sync_cookies IS '商家 QNH Cookie 管理，用于数据同步认证';
