-- 020_knowledge_base.sql
-- 创建客服知识库表

CREATE TABLE IF NOT EXISTS knowledge_base (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,      -- faq/usage_guide/policy/compliance
    subcategory VARCHAR(100),           -- 产品品类或主题
    question TEXT,                      -- 用户可能问的问题
    answer TEXT NOT NULL,               -- 标准回答
    keywords TEXT[],                    -- 触发关键词
    priority INT DEFAULT 0,             -- 优先级
    product_categories TEXT[],          -- 关联产品品类
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 创建索引
CREATE INDEX idx_kb_category ON knowledge_base(category);
CREATE INDEX idx_kb_keywords ON knowledge_base USING GIN(keywords);
CREATE INDEX idx_kb_product_categories ON knowledge_base USING GIN(product_categories);
CREATE INDEX idx_kb_priority ON knowledge_base(priority DESC);

-- 添加对话日志表
CREATE TABLE IF NOT EXISTS cs_conversation_log (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100),
    user_message TEXT NOT NULL,
    intent VARCHAR(50),
    ai_response TEXT NOT NULL,
    matched_kb_ids INT[],
    matched_product_ids TEXT[],
    confidence FLOAT,
    feedback VARCHAR(20),  -- good/bad/null
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 创建对话日志表索引
CREATE INDEX idx_cs_log_session ON cs_conversation_log(session_id);
CREATE INDEX idx_cs_log_intent ON cs_conversation_log(intent);
CREATE INDEX idx_cs_log_created_at ON cs_conversation_log(created_at DESC);
