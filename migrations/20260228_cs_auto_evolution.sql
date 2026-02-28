-- AI客服自我进化系统数据库迁移
-- 创建自动进化所需的数据库表

-- 1. 客服改进日志表
CREATE TABLE IF NOT EXISTS cs_improvement_log (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_msg TEXT NOT NULL,
    reply TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    analysis TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Few-shot候选示例表
CREATE TABLE IF NOT EXISTS cs_few_shot_candidates (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    user_msg TEXT NOT NULL,
    reply TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 客服回复评分表（如果不存在的话，评分器可能已经创建了）
CREATE TABLE IF NOT EXISTS cs_reply_scores (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_message TEXT NOT NULL,
    ai_reply TEXT NOT NULL,
    accuracy REAL CHECK (accuracy >= 0 AND accuracy <= 1),
    professionalism REAL CHECK (professionalism >= 0 AND professionalism <= 1),
    tone REAL CHECK (tone >= 0 AND tone <= 1),
    resolution REAL CHECK (resolution >= 0 AND resolution <= 1),
    compliance REAL CHECK (compliance >= 0 AND compliance <= 1),
    overall REAL NOT NULL CHECK (overall >= 0 AND overall <= 1),
    feedback TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 系统配置表（存储动态配置，如few-shot示例）
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 创建索引优化查询性能

-- cs_improvement_log 索引
CREATE INDEX IF NOT EXISTS idx_cs_improvement_log_score 
ON cs_improvement_log(score);

CREATE INDEX IF NOT EXISTS idx_cs_improvement_log_created 
ON cs_improvement_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cs_improvement_log_session 
ON cs_improvement_log(session_id);

-- cs_few_shot_candidates 索引
CREATE INDEX IF NOT EXISTS idx_cs_few_shot_candidates_score 
ON cs_few_shot_candidates(score DESC);

CREATE INDEX IF NOT EXISTS idx_cs_few_shot_candidates_category 
ON cs_few_shot_candidates(category);

CREATE INDEX IF NOT EXISTS idx_cs_few_shot_candidates_created 
ON cs_few_shot_candidates(created_at DESC);

-- cs_reply_scores 索引
CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_session 
ON cs_reply_scores(session_id);

CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_overall 
ON cs_reply_scores(overall DESC);

CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_created 
ON cs_reply_scores(created_at DESC);

-- 复合索引：按时间和分数查询高质量回复
CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_recent_high_score 
ON cs_reply_scores(created_at DESC, overall DESC) 
WHERE overall >= 0.85;

-- 复合索引：按时间和分数查询低质量回复
CREATE INDEX IF NOT EXISTS idx_cs_reply_scores_recent_low_score 
ON cs_reply_scores(created_at DESC, overall ASC) 
WHERE overall < 0.6;

-- system_config 索引
CREATE INDEX IF NOT EXISTS idx_system_config_key 
ON system_config(key);

-- 添加一些初始配置数据
INSERT INTO system_config (key, value) 
VALUES ('cs_evolution_enabled', 'true'::jsonb)
ON CONFLICT (key) DO NOTHING;

INSERT INTO system_config (key, value) 
VALUES ('cs_evolution_high_score_threshold', '0.85'::jsonb)
ON CONFLICT (key) DO NOTHING;

INSERT INTO system_config (key, value) 
VALUES ('cs_evolution_low_score_threshold', '0.6'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- 添加表注释
COMMENT ON TABLE cs_improvement_log IS 'AI客服低分回复改进日志，记录需要优化的对话';
COMMENT ON TABLE cs_few_shot_candidates IS 'Few-shot学习候选示例，存储高质量对话用于提升模型表现';
COMMENT ON TABLE cs_reply_scores IS 'AI客服回复质量评分记录，用于自动评估和改进';
COMMENT ON TABLE system_config IS '系统配置表，存储动态配置参数';

-- 添加列注释
COMMENT ON COLUMN cs_improvement_log.score IS '回复质量评分 (0-1)';
COMMENT ON COLUMN cs_improvement_log.analysis IS 'LLM分析的改进建议和问题原因';
COMMENT ON COLUMN cs_few_shot_candidates.category IS '对话场景类别 (product_inquiry, after_sales等)';
COMMENT ON COLUMN cs_few_shot_candidates.score IS '回复质量评分 (0-1)，用于排序选择最佳示例';
COMMENT ON COLUMN cs_reply_scores.overall IS '综合评分 (0-1)，用于触发自动学习';

-- 创建视图方便数据分析

-- 高质量回复统计视图
CREATE OR REPLACE VIEW cs_high_quality_replies AS
SELECT 
    category,
    COUNT(*) as count,
    AVG(score) as avg_score,
    MAX(score) as max_score,
    MIN(created_at) as first_seen,
    MAX(created_at) as last_updated
FROM cs_few_shot_candidates 
WHERE score >= 0.85
GROUP BY category
ORDER BY count DESC, avg_score DESC;

-- 改进需求统计视图
CREATE OR REPLACE VIEW cs_improvement_summary AS
SELECT 
    DATE(created_at) as date,
    COUNT(*) as low_score_count,
    AVG(score) as avg_low_score,
    COUNT(DISTINCT session_id) as affected_sessions
FROM cs_improvement_log
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- 评分趋势分析视图
CREATE OR REPLACE VIEW cs_scoring_trends AS
SELECT 
    DATE(created_at) as date,
    COUNT(*) as total_evaluations,
    AVG(overall) as avg_overall_score,
    AVG(accuracy) as avg_accuracy,
    AVG(professionalism) as avg_professionalism,
    AVG(tone) as avg_tone,
    AVG(resolution) as avg_resolution,
    AVG(compliance) as avg_compliance,
    COUNT(CASE WHEN overall >= 0.85 THEN 1 END) as high_score_count,
    COUNT(CASE WHEN overall < 0.6 THEN 1 END) as low_score_count
FROM cs_reply_scores
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- 添加视图注释
COMMENT ON VIEW cs_high_quality_replies IS '高质量回复统计，按场景类别汇总最佳实践示例';
COMMENT ON VIEW cs_improvement_summary IS '改进需求汇总，显示每日低分回复数量趋势';
COMMENT ON VIEW cs_scoring_trends IS '评分趋势分析，显示客服质量的时间序列变化';