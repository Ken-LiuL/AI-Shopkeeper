-- Migration 050: feedback compatibility fixes for older production schemas

CREATE TABLE IF NOT EXISTS feedback_tracking (
    id SERIAL PRIMARY KEY,
    tracking_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    outcome_data JSONB DEFAULT '{}'::jsonb,
    performance_score REAL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE feedback_tracking
    ADD COLUMN IF NOT EXISTS outcome_data JSONB DEFAULT '{}'::jsonb;

ALTER TABLE feedback_tracking
    ADD COLUMN IF NOT EXISTS performance_score REAL DEFAULT 0;

ALTER TABLE feedback_tracking
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'feedback_tracking' AND column_name = 'tracked_at'
    ) THEN
        EXECUTE $sql$
            UPDATE feedback_tracking
            SET created_at = COALESCE(created_at, tracked_at, NOW())
            WHERE created_at IS NULL
        $sql$;
    ELSE
        EXECUTE $sql$
            UPDATE feedback_tracking
            SET created_at = COALESCE(created_at, NOW())
            WHERE created_at IS NULL
        $sql$;
    END IF;
END $$;

ALTER TABLE feedback_tracking
    ALTER COLUMN created_at SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_feedback_tracking_created
    ON feedback_tracking(created_at DESC);

CREATE TABLE IF NOT EXISTS learning_weights (
    id SERIAL PRIMARY KEY,
    weights JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS adaptive_thresholds (
    name TEXT PRIMARY KEY,
    current_value FLOAT NOT NULL,
    min_value FLOAT NOT NULL,
    max_value FLOAT NOT NULL,
    update_reason TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
