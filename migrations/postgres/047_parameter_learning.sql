-- Migration 047: 参数自学习系统
-- 创建 parameter_versions 和 selection_feedback 表

-- ── parameter_versions ─────────────────────────────────────────────────────
-- 记录每次权重/阈值更新的版本历史，支持版本对比与回滚
CREATE TABLE IF NOT EXISTS parameter_versions (
    id           SERIAL PRIMARY KEY,
    param_type   TEXT        NOT NULL,  -- 'scoring_weights' | 'anomaly_thresholds'
    version      INT         NOT NULL,
    params       JSONB       NOT NULL,  -- 更新后的参数快照（或变更 diff）
    feedback_stats JSONB,               -- 触发本次学习的统计信息
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parameter_versions_type_created
    ON parameter_versions (param_type, created_at DESC);

-- ── selection_feedback ─────────────────────────────────────────────────────
-- 记录运营对选品推荐的操作反馈（采纳/忽略/拒绝）
-- 由前端在运营确认/关闭推荐时写入
CREATE TABLE IF NOT EXISTS selection_feedback (
    id                SERIAL PRIMARY KEY,
    recommendation_id TEXT,
    product_id        TEXT,
    action            TEXT,   -- 'adopted' | 'ignored' | 'rejected'
    scores            JSONB,  -- 各维度得分快照 {'market_heat': 85, ...}
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_selection_feedback_created
    ON selection_feedback (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_selection_feedback_action
    ON selection_feedback (action);

-- ── 保留 learning_weights 和 adaptive_thresholds 兼容旧实现 ───────────────
-- （WeightLearner / AdaptiveThresholds 仍在使用这两张表）
CREATE TABLE IF NOT EXISTS learning_weights (
    id         SERIAL PRIMARY KEY,
    weights    JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS adaptive_thresholds (
    name          TEXT PRIMARY KEY,
    current_value FLOAT NOT NULL,
    min_value     FLOAT NOT NULL,
    max_value     FLOAT NOT NULL,
    update_reason TEXT,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
