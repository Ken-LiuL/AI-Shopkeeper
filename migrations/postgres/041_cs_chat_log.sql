-- Customer service chat log table used by /api/customer-service/log-chat
CREATE TABLE IF NOT EXISTS cs_chat_log (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(200),
    message_id VARCHAR(200),
    role VARCHAR(20) NOT NULL DEFAULT 'agent',
    content TEXT NOT NULL,
    content_hash VARCHAR(32),
    source_timestamp TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Backfill-safe column ensures for old environments
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS session_id VARCHAR(200);
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS message_id VARCHAR(200);
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'agent';
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS content_hash VARCHAR(32);
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS source_timestamp TIMESTAMPTZ;
ALTER TABLE cs_chat_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- Dedupe and query indexes
CREATE UNIQUE INDEX IF NOT EXISTS idx_cs_chat_log_hash
ON cs_chat_log (content_hash);

CREATE INDEX IF NOT EXISTS idx_cs_chat_log_session_created
ON cs_chat_log (session_id, created_at DESC);
