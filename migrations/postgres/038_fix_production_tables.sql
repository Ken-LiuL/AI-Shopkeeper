-- 038: Fix production table issues
-- 1. Ensure selection_runs has run_id column (may have been created without it)
-- 2. Create store_daily_metrics as view of qnh_daily_metrics if only latter exists
-- 3. Create feedback_tracking table
-- 4. Add missing columns to price_history

BEGIN;

-- Fix selection_runs: ensure run_id exists
DO $$
BEGIN
    -- Check if selection_runs exists but lacks run_id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'selection_runs')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'selection_runs' AND column_name = 'run_id') THEN
        ALTER TABLE selection_runs ADD COLUMN run_id VARCHAR(50);
        -- Backfill run_id with id if it exists
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'selection_runs' AND column_name = 'id') THEN
            UPDATE selection_runs SET run_id = 'sel_' || id::text WHERE run_id IS NULL;
        END IF;
    END IF;
END $$;

-- Ensure selection_runs has all needed columns
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT '{}';
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS categories TEXT[] DEFAULT '{}';
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS result JSONB;
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS result_count INTEGER DEFAULT 0;
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

-- Create store_daily_metrics view if qnh_daily_metrics exists but store_daily_metrics doesn't
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'qnh_daily_metrics')
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'store_daily_metrics') THEN
        EXECUTE 'CREATE VIEW store_daily_metrics AS SELECT * FROM qnh_daily_metrics';
    END IF;
END $$;

-- Feedback tracking table
CREATE TABLE IF NOT EXISTS feedback_tracking (
    id SERIAL PRIMARY KEY,
    tracking_type VARCHAR(50) NOT NULL,
    reference_id VARCHAR(255) NOT NULL,
    outcome_data JSONB,
    performance_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_tracking_type ON feedback_tracking(tracking_type);
CREATE INDEX IF NOT EXISTS idx_feedback_tracking_ref ON feedback_tracking(reference_id);

-- Price history: add outcome tracking columns
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS outcome_tracked BOOLEAN DEFAULT FALSE;
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS sales_before INTEGER;
ALTER TABLE price_history ADD COLUMN IF NOT EXISTS sales_after INTEGER;

-- LLM usage table (for metrics tracking)
CREATE TABLE IF NOT EXISTS llm_usage (
    id SERIAL PRIMARY KEY,
    model VARCHAR(100),
    agent_type VARCHAR(50),
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd DECIMAL(10,6) DEFAULT 0,
    latency_ms INTEGER,
    trace_name VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage(model);

-- CS conversation log table
CREATE TABLE IF NOT EXISTS cs_conversation_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    user_message TEXT,
    intent VARCHAR(50),
    ai_response TEXT,
    matched_kb_ids INTEGER[] DEFAULT '{}',
    matched_product_ids TEXT[] DEFAULT '{}',
    confidence REAL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cs_log_session ON cs_conversation_log(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_log_created ON cs_conversation_log(created_at DESC);

COMMIT;
