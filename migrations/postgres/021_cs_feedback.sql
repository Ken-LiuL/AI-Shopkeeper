-- Customer Service Feedback Table
CREATE TABLE IF NOT EXISTS cs_feedback (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT,
    rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
    comment TEXT,
    user_message TEXT,
    ai_response TEXT,
    intent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_cs_feedback_rating ON cs_feedback(rating);
CREATE INDEX idx_cs_feedback_created ON cs_feedback(created_at);
CREATE INDEX idx_cs_feedback_session ON cs_feedback(session_id);
