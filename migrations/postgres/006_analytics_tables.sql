-- 006_analytics_tables.sql
-- 客服分析、价格历史、采购单表

-- 客服日统计
CREATE TABLE IF NOT EXISTS cs_analytics (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    total_inquiries INTEGER DEFAULT 0,
    ai_handled      INTEGER DEFAULT 0,
    human_transfer  INTEGER DEFAULT 0,
    avg_response_ms INTEGER DEFAULT 0,
    intent_distribution JSONB DEFAULT '{}',
    satisfaction_score REAL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_analytics_date ON cs_analytics(date DESC);

-- 价格变更历史
CREATE TABLE IF NOT EXISTS price_history (
    id              SERIAL PRIMARY KEY,
    product_id      TEXT NOT NULL,
    old_price       REAL NOT NULL,
    new_price       REAL NOT NULL,
    reason          TEXT DEFAULT '',
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    outcome_tracked BOOLEAN DEFAULT FALSE,
    sales_before    INTEGER DEFAULT 0,
    sales_after     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(changed_at DESC);

-- 采购单
CREATE TABLE IF NOT EXISTS purchase_orders (
    order_id        TEXT PRIMARY KEY,
    items           JSONB NOT NULL DEFAULT '[]',
    total_cost      REAL DEFAULT 0,
    status          TEXT DEFAULT 'draft',
    supplier        TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_date ON purchase_orders(created_at DESC);

-- 反馈追踪
CREATE TABLE IF NOT EXISTS feedback_tracking (
    id              SERIAL PRIMARY KEY,
    tracking_type   TEXT NOT NULL,  -- 'selection' | 'bundle' | 'pricing'
    reference_id    TEXT NOT NULL,
    tracked_at      TIMESTAMPTZ DEFAULT NOW(),
    outcome_data    JSONB DEFAULT '{}',
    performance_score REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_feedback_tracking_type ON feedback_tracking(tracking_type);
CREATE INDEX IF NOT EXISTS idx_feedback_tracking_ref ON feedback_tracking(reference_id);

-- 转化追踪
CREATE TABLE IF NOT EXISTS cs_conversion (
    id              SERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    product_id      TEXT NOT NULL,
    recommended_at  TIMESTAMPTZ DEFAULT NOW(),
    purchased       BOOLEAN DEFAULT FALSE,
    purchased_at    TIMESTAMPTZ,
    order_id        TEXT
);

CREATE INDEX IF NOT EXISTS idx_cs_conversion_session ON cs_conversion(session_id);
CREATE INDEX IF NOT EXISTS idx_cs_conversion_product ON cs_conversion(product_id);
