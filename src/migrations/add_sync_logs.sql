CREATE TABLE IF NOT EXISTS sync_logs (
    id SERIAL PRIMARY KEY,
    store_id TEXT,
    sync_type TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    records_count INT DEFAULT 0,
    error_msg TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
