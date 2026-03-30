CREATE TABLE IF NOT EXISTS policy_documents (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE,
    title TEXT,
    content TEXT,
    category TEXT,
    policy_type TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS policy_type TEXT;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
