-- Add extended feedback columns to cs_feedback table
ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS action VARCHAR(20);
ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS original_reply TEXT;
ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS edited_reply TEXT;
ALTER TABLE cs_feedback ADD COLUMN IF NOT EXISTS actual_reply TEXT;

-- Ensure system_config table exists for dynamic few-shots
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
