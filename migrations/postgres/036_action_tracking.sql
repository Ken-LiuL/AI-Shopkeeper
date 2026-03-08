-- Agent 决策行动追踪表
CREATE TABLE IF NOT EXISTS action_tracking (
    id SERIAL PRIMARY KEY,
    action_id TEXT UNIQUE NOT NULL,           -- 唯一标识
    agent_type TEXT NOT NULL,                 -- alert/selection/bundle/listing/cs
    action_type TEXT NOT NULL,                -- price_adjust/promotion/restock/bundle_create/...
    product_id TEXT,                          -- 关联商品
    product_name TEXT,

    -- 决策内容
    decision_json JSONB NOT NULL,             -- 完整决策内容
    confidence FLOAT,                         -- 决策置信度
    context_summary TEXT,                     -- 决策时的数据摘要

    -- 基线指标（决策时的快照）
    baseline_metrics JSONB,                   -- {sales_7d: 100, price: 29.9, stock: 50, ...}

    -- 效果指标（定时填充）
    effect_metrics JSONB,                     -- {sales_7d: 130, price: 25.9, stock: 30, ...}
    effect_score FLOAT,                       -- 效果评分 (0-1)
    effect_evaluated_at TIMESTAMPTZ,

    -- 用户反馈
    user_accepted BOOLEAN,                    -- 用户是否采纳
    user_feedback TEXT,                       -- 用户反馈文字

    -- 状态
    status TEXT DEFAULT 'pending',            -- pending/accepted/rejected/evaluated/expired
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_action_tracking_agent ON action_tracking(agent_type);
CREATE INDEX idx_action_tracking_product ON action_tracking(product_id);
CREATE INDEX idx_action_tracking_status ON action_tracking(status);
CREATE INDEX idx_action_tracking_created ON action_tracking(created_at);
