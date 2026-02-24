-- 012: 客服IM会话与消息表
-- 数据源: 牵牛花 在线客服模块

CREATE TABLE IF NOT EXISTS qnh_im_sessions (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       VARCHAR(32) NOT NULL,
    session_id      VARCHAR(64) NOT NULL UNIQUE,
    channel         VARCHAR(32),
    customer_id     VARCHAR(64),
    customer_name   VARCHAR(128),
    order_id        VARCHAR(64),
    status          VARCHAR(32),           -- open / closed / transferred
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    message_count   INT DEFAULT 0,
    satisfaction    SMALLINT,              -- 1-5 满意度评分
    extra           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qnh_im_messages (
    id              BIGSERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL REFERENCES qnh_im_sessions(session_id),
    message_id      VARCHAR(64) NOT NULL UNIQUE,
    role            VARCHAR(16) NOT NULL,  -- customer / merchant / system
    content         TEXT,
    msg_time        TIMESTAMPTZ,
    msg_type        VARCHAR(32) DEFAULT 'text',  -- text / image / order_card
    extra           JSONB,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_im_sessions_tenant ON qnh_im_sessions(tenant_id);
CREATE INDEX idx_im_sessions_customer ON qnh_im_sessions(customer_id);
CREATE INDEX idx_im_sessions_order ON qnh_im_sessions(order_id);
CREATE INDEX idx_im_sessions_time ON qnh_im_sessions(started_at);
CREATE INDEX idx_im_messages_session ON qnh_im_messages(session_id);
CREATE INDEX idx_im_messages_time ON qnh_im_messages(msg_time);

-- 向量化索引（用于语义检索历史对话）
-- 需要 pgvector 扩展
-- CREATE INDEX idx_im_messages_embedding ON qnh_im_messages USING ivfflat (embedding vector_cosine_ops);
