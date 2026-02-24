-- 014: 评价NLP分析结果表

CREATE TABLE IF NOT EXISTS qnh_review_analysis (
    id                  BIGSERIAL PRIMARY KEY,
    review_id           VARCHAR(64) NOT NULL UNIQUE,
    sentiment           VARCHAR(16),           -- positive / neutral / negative
    sentiment_score     NUMERIC(4,2),          -- -1.0 to 1.0
    keywords            JSONB,
    issue_categories    JSONB,                 -- ["质量","物流"]
    summary             TEXT,
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_review_analysis_sentiment ON qnh_review_analysis(sentiment);
CREATE INDEX idx_review_analysis_time ON qnh_review_analysis(analyzed_at);
