CREATE TABLE IF NOT EXISTS sync_logs (
    id BIGSERIAL PRIMARY KEY,
    store_id VARCHAR(64),
    sync_type VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_count INT DEFAULT 0,
    error_msg TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_logs_type_started_at
    ON sync_logs (sync_type, started_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_sync_logs_store_started_at
    ON sync_logs (store_id, started_at DESC NULLS LAST);
