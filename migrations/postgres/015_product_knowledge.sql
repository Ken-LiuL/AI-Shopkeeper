-- Product Knowledge Base — vector embeddings + vision-extracted text
-- For semantic search over product catalog
-- Depends on: pgvector extension (007), qnh_products (002)

CREATE TABLE IF NOT EXISTS product_knowledge (
    id              SERIAL PRIMARY KEY,
    spu_id          TEXT NOT NULL,
    sku_id          TEXT DEFAULT '',
    name            TEXT NOT NULL,
    category        TEXT DEFAULT '',
    brand           TEXT DEFAULT '',
    spec            TEXT DEFAULT '',
    description     TEXT DEFAULT '',       -- from product detail
    image_text      TEXT DEFAULT '',       -- OCR/vision extracted text from images
    combined_text   TEXT NOT NULL,         -- merged text for display
    embedding       vector(512),           -- BGE-small-zh-v1.5
    image_urls      TEXT[] DEFAULT '{}',   -- all image URLs
    price           NUMERIC(10, 2),
    status          TEXT DEFAULT '',
    fts             tsvector GENERATED ALWAYS AS (
                        to_tsvector('simple', coalesce(name, '') || ' ' ||
                                    coalesce(category, '') || ' ' ||
                                    coalesce(brand, '') || ' ' ||
                                    coalesce(spec, '') || ' ' ||
                                    coalesce(description, '') || ' ' ||
                                    coalesce(image_text, ''))
                    ) STORED,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(spu_id, sku_id)
);

-- Vector similarity index
CREATE INDEX IF NOT EXISTS idx_product_knowledge_embedding
    ON product_knowledge USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_product_knowledge_fts
    ON product_knowledge USING gin (fts);

-- SPU lookup
CREATE INDEX IF NOT EXISTS idx_product_knowledge_spu
    ON product_knowledge(spu_id);
