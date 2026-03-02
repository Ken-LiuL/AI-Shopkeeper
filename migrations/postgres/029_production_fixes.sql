-- 029: Production environment fixes - 确保所有表和列存在

-- 确保 users 表存在（登录功能）
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    role        TEXT NOT NULL DEFAULT 'admin',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 插入默认管理员用户（如果不存在）
INSERT INTO users (user_id, username, password_hash, tenant_id, role)
VALUES (
    'user-admin-001',
    'admin',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',  -- 'admin123' 的 bcrypt hash
    'default',
    'admin'
) ON CONFLICT (username) DO UPDATE SET
    password_hash = EXCLUDED.password_hash;

-- 确保 qnh_products 表有 stock_num 列（dashboard action items 需要）
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS stock_num INTEGER DEFAULT 0;
UPDATE qnh_products SET stock_num = COALESCE(stock, 0) WHERE stock_num IS NULL OR stock_num = 0;

-- 确保 orders_summary 表存在（竞品分析 fallback demo 需要）
CREATE TABLE IF NOT EXISTS orders_summary (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(100),
    product_id VARCHAR(100),
    product_name VARCHAR(500),
    category VARCHAR(200),
    quantity VARCHAR(32) DEFAULT '1',
    price VARCHAR(32) DEFAULT '0',
    date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_summary_date ON orders_summary(date);
CREATE INDEX IF NOT EXISTS idx_orders_summary_product ON orders_summary(product_id);

-- 确保 competitor_products 表有 competitor_name 列（竞品分析 fallback demo 需要）
ALTER TABLE competitor_products ADD COLUMN IF NOT EXISTS competitor_name VARCHAR(100);
UPDATE competitor_products SET competitor_name = store_id WHERE competitor_name IS NULL AND store_id IS NOT NULL;

-- 确保其他可能缺失的列
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS stock INTEGER DEFAULT 0;
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS reserved_stock INTEGER DEFAULT 0;
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS safety_stock INTEGER DEFAULT 0;

-- 确保客服相关表存在
CREATE TABLE IF NOT EXISTS cs_sessions (
    session_id TEXT PRIMARY KEY,
    customer_id TEXT,
    status TEXT DEFAULT 'active',
    needs_human BOOLEAN DEFAULT FALSE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cs_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT REFERENCES cs_sessions(session_id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_messages_session ON cs_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_messages_created ON cs_messages(created_at);

CREATE TABLE IF NOT EXISTS cs_feedback (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT,
    message_id TEXT,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cs_conversation_log (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT,
    user_message TEXT,
    intent TEXT,
    ai_response TEXT,
    matched_kb_ids INTEGER[],
    matched_product_ids TEXT[],
    confidence DECIMAL(5, 4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_conversation_log_session ON cs_conversation_log(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_conversation_log_created ON cs_conversation_log(created_at);

-- 插入一些示例订单数据到 orders_summary（如果表为空）
INSERT INTO orders_summary (order_id, product_id, product_name, category, quantity, price, date)
SELECT
    'demo-' || generate_random_uuid()::TEXT,
    cp.product_name,
    cp.product_name,
    COALESCE(cp.category, '医疗器械'),
    '1',
    cp.price::TEXT,
    CURRENT_DATE - (random() * 30)::INTEGER
FROM competitor_products cp
WHERE NOT EXISTS (SELECT 1 FROM orders_summary LIMIT 1)
LIMIT 10;

SELECT 'Production fixes applied successfully' AS status;
