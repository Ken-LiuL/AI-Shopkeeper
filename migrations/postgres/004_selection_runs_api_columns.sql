-- Add columns used by selection API that aren't in original schema
BEGIN;

ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT '{}';
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS categories TEXT[] DEFAULT '{}';
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS result JSONB;
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS result_count INTEGER DEFAULT 0;
ALTER TABLE selection_runs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

COMMIT;
