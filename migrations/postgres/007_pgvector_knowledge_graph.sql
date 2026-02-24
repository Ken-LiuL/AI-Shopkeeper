-- pgvector extension + knowledge graph tables for vector search
-- Replaces Neo4j as the vector store backend when VECTOR_STORE=postgres

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Products with embeddings ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_products (
    product_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    price       NUMERIC(10, 2) DEFAULT 0,
    embedding   vector(1024),     -- BGE-large-zh-v1.5 = 1024 dims
    fts         tsvector GENERATED ALWAYS AS (
                    to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, ''))
                ) STORED,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Vector similarity index (IVFFlat — good for <1M rows; switch to HNSW if needed)
CREATE INDEX IF NOT EXISTS idx_kg_products_embedding
    ON kg_products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_kg_products_fts
    ON kg_products USING gin (fts);

-- ── Populations ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_populations (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT ''
);

-- ── Product ↔ Population relations ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_product_population (
    product_id    TEXT NOT NULL REFERENCES kg_products(product_id) ON DELETE CASCADE,
    population_id INTEGER NOT NULL REFERENCES kg_populations(id) ON DELETE CASCADE,
    relation      TEXT NOT NULL CHECK (relation IN ('suitable', 'contraindicated')),
    reason        TEXT DEFAULT '',
    PRIMARY KEY (product_id, population_id, relation)
);

-- ── Scenarios ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_scenarios (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS kg_product_scenario (
    product_id  TEXT NOT NULL REFERENCES kg_products(product_id) ON DELETE CASCADE,
    scenario_id INTEGER NOT NULL REFERENCES kg_scenarios(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, scenario_id)
);

-- ── Related products ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_related_products (
    product_id         TEXT NOT NULL REFERENCES kg_products(product_id) ON DELETE CASCADE,
    related_product_id TEXT NOT NULL REFERENCES kg_products(product_id) ON DELETE CASCADE,
    relation           TEXT DEFAULT 'OFTEN_BOUGHT_WITH',
    PRIMARY KEY (product_id, related_product_id)
);

-- ── FAQs ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_faqs (
    id         SERIAL PRIMARY KEY,
    product_id TEXT REFERENCES kg_products(product_id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    category   TEXT DEFAULT 'general',
    embedding  vector(1024),
    fts        tsvector GENERATED ALWAYS AS (
                   to_tsvector('simple', coalesce(question, '') || ' ' || coalesce(answer, ''))
               ) STORED
);

CREATE INDEX IF NOT EXISTS idx_kg_faqs_embedding
    ON kg_faqs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_kg_faqs_fts
    ON kg_faqs USING gin (fts);
