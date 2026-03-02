-- 客服消息表
CREATE TABLE IF NOT EXISTS cs_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    message_type VARCHAR(20) NOT NULL, -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_messages_session_id ON cs_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_messages_timestamp ON cs_messages(timestamp);

-- 客服会话统计视图
CREATE OR REPLACE VIEW cs_session_stats AS
SELECT
    session_id,
    COUNT(*) as message_count,
    MIN(timestamp) as session_start,
    MAX(timestamp) as session_end,
    COUNT(CASE WHEN message_type = 'user' THEN 1 END) as user_messages,
    COUNT(CASE WHEN message_type = 'assistant' THEN 1 END) as bot_responses
FROM cs_messages
GROUP BY session_id;

SELECT 'Customer service messages table created' as status;
