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

ALTER TABLE listings ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS platform VARCHAR(32) DEFAULT 'alibaba';
ALTER TABLE listings ADD COLUMN IF NOT EXISTS raw_product_data TEXT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS parsed_product JSONB;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS matched_standard JSONB;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS match_confidence FLOAT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS listing_info JSONB;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS compliance_check JSONB;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS current_step VARCHAR(32) DEFAULT 'parsing';
ALTER TABLE listings ADD COLUMN IF NOT EXISTS step_detail TEXT;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS errors JSONB;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);

-- Backfill old schema columns into the current shape.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'listings' AND column_name = 'product_data'
    ) THEN
        UPDATE listings
        SET raw_product_data = COALESCE(raw_product_data, product_data::text),
            parsed_product = COALESCE(parsed_product, product_data::jsonb)
        WHERE product_data IS NOT NULL
          AND (raw_product_data IS NULL OR parsed_product IS NULL);
    END IF;
END
$$;
