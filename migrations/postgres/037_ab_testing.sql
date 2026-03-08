-- A/B 测试框架：实验、分配、结果表

CREATE TABLE IF NOT EXISTS ab_experiments (
    experiment_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    variants JSONB NOT NULL,          -- ["control", "treatment", ...]
    traffic_split JSONB,              -- {"control": 0.5, "treatment": 0.5}
    metrics JSONB,                    -- ["latency", "tokens", ...]
    status VARCHAR(20) DEFAULT 'running',  -- running/stopped/completed
    created_at TIMESTAMP DEFAULT NOW(),
    stopped_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ab_assignments (
    experiment_id VARCHAR(50) REFERENCES ab_experiments(experiment_id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    variant_name VARCHAR(50) NOT NULL,
    assigned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (experiment_id, user_id)
);

CREATE TABLE IF NOT EXISTS ab_outcomes (
    id SERIAL PRIMARY KEY,
    experiment_id VARCHAR(50) REFERENCES ab_experiments(experiment_id) ON DELETE CASCADE,
    variant_name VARCHAR(50) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    metadata JSONB,
    recorded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ab_outcomes_exp ON ab_outcomes(experiment_id, variant_name);
CREATE INDEX IF NOT EXISTS idx_ab_outcomes_metric ON ab_outcomes(experiment_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_ab_assignments_exp ON ab_assignments(experiment_id, variant_name);
