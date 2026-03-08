-- Migration: 004_feedback_tracking
-- 反馈追踪表 + price_history 扩展字段

-- feedback_tracking 表
CREATE TABLE IF NOT EXISTS feedback_tracking (
    id SERIAL PRIMARY KEY,
    tracking_type VARCHAR(50) NOT NULL,
    reference_id VARCHAR(255) NOT NULL,
    outcome_data JSONB,
    performance_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_tracking_type ON feedback_tracking (tracking_type);
CREATE INDEX IF NOT EXISTS idx_feedback_tracking_created ON feedback_tracking (created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_tracking_ref ON feedback_tracking (reference_id);

-- price_history 扩展字段（调价追踪）
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS outcome_tracked BOOLEAN DEFAULT FALSE;
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS sales_before INTEGER;
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS sales_after INTEGER;
