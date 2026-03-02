-- Migration 026: users table for authentication
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    role        TEXT NOT NULL DEFAULT 'admin',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Placeholder row; actual password hash is set by the app at startup
-- See src/auth/seed.py which runs after migrations
INSERT INTO users (user_id, username, password_hash, tenant_id, role)
VALUES (
    'user-admin-001',
    'admin',
    '__PLACEHOLDER__',
    'default',
    'admin'
) ON CONFLICT (username) DO NOTHING;
