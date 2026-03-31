-- Migration: add cs_metrics table for customer service effect tracking
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS cs_metrics (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    message_id VARCHAR(128),
    ai_reply_id VARCHAR(128),

    -- 时间维度
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    replied_at TIMESTAMPTZ,
    response_time_ms INTEGER,  -- 响应时间毫秒

    -- AI 处理维度
    intent VARCHAR(64),
    confidence FLOAT,
    needs_human BOOLEAN DEFAULT FALSE,
    was_fast_path BOOLEAN DEFAULT FALSE,
    compliance_filtered BOOLEAN DEFAULT FALSE,

    -- 效果维度
    user_followed_up BOOLEAN,  -- 用户是否追问（可后续标注）

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_metrics_session ON cs_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_metrics_created ON cs_metrics(created_at);
