-- API support tables (listings, bundle_tasks, alert_scans, llm_usage)
-- Version: 003

BEGIN;

CREATE TABLE IF NOT EXISTS listings (
    listing_id   VARCHAR(50) PRIMARY KEY,
    status       VARCHAR(20) DEFAULT 'processing'
        CHECK (status IN ('processing', 'completed', 'failed')),
    source_url   TEXT,
    platform     VARCHAR(20),
    product_data JSONB,
    created_at   TIMESTAMPTZ DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bundle_tasks (
    task_id    VARCHAR(50) PRIMARY KEY,
    status     VARCHAR(20) DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    result     JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alert_scans (
    scan_id    VARCHAR(50) PRIMARY KEY,
    status     VARCHAR(20) DEFAULT 'running',
    result     JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id          SERIAL PRIMARY KEY,
    model       VARCHAR(100) NOT NULL,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd    DECIMAL(10, 6) DEFAULT 0,
    agent_type  VARCHAR(50),
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage(model);

COMMIT;
