-- Customer service sessions table
CREATE TABLE IF NOT EXISTS cs_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE,
    customer_id     TEXT,
    channel         TEXT DEFAULT 'web',
    status          TEXT DEFAULT 'active',
    intent          TEXT,
    ai_handled      BOOLEAN DEFAULT TRUE,
    transferred     BOOLEAN DEFAULT FALSE,
    response_ms     INT,
    satisfaction    INT,
    product_id      TEXT,
    product_name    TEXT,
    purchased       BOOLEAN DEFAULT FALSE,
    order_id        TEXT,
    messages        JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cs_sessions_created ON cs_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_cs_sessions_status ON cs_sessions(status);
