-- Add embedding column (JSONB) to qnh_products for semantic search
ALTER TABLE qnh_products ADD COLUMN IF NOT EXISTS embedding JSONB;
