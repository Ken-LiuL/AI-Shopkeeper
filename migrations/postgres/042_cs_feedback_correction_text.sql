-- Add missing extended feedback column used by API
ALTER TABLE cs_feedback
ADD COLUMN IF NOT EXISTS correction_text TEXT;
