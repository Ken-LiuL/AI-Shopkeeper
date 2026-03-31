-- Migration: add_listings_table
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',  -- processing/completed/failed
    source_url TEXT,
    platform VARCHAR(32) DEFAULT 'alibaba',  -- alibaba/pdd
    raw_product_data TEXT,

    -- 解析结果
    parsed_product JSONB,

    -- 匹配结果
    matched_standard JSONB,
    match_confidence FLOAT,

    -- 上架信息
    listing_info JSONB,

    -- 合规结果
    compliance_check JSONB,

    -- 当前步骤（用于进度展示）
    current_step VARCHAR(32) DEFAULT 'parsing',  -- parsing/matching/filling/compliance/done
    step_detail TEXT,

    -- 错误信息
    errors JSONB,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);

-- Migrate existing rows that have product_data column (old schema) but not parsed_product
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listings' AND column_name = 'product_data'
    ) THEN
        -- backfill parsed_product from old product_data column if needed
        UPDATE listings
        SET parsed_product = product_data::jsonb
        WHERE parsed_product IS NULL AND product_data IS NOT NULL;
    END IF;
END
$$;
