CREATE TABLE IF NOT EXISTS issue_actions (
    id SERIAL PRIMARY KEY,
    issue_type VARCHAR(100) NOT NULL,
    issue_key TEXT NOT NULL,
    title TEXT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('acknowledged', 'resolved', 'ignored')),
    notes TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(issue_type, issue_key)
);

CREATE INDEX IF NOT EXISTS idx_issue_actions_type_status ON issue_actions(issue_type, status);
