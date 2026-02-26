-- Migration 016: Change embedding dimension from 1024 to 512 (bge-small-zh-v1.5)
-- This requires dropping and recreating the column + index

-- Drop index first
DROP INDEX IF EXISTS idx_product_knowledge_embedding;

-- Change column dimension
ALTER TABLE product_knowledge DROP COLUMN IF EXISTS embedding;
ALTER TABLE product_knowledge ADD COLUMN embedding vector(512);

-- Recreate index (will be populated on next knowledge build)
CREATE INDEX idx_product_knowledge_embedding
    ON product_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
