-- 032_product_embeddings.sql
-- 为 qnh_products 表添加 pgvector embedding 列（1536维，兼容 text-embedding-3-small）
-- 并创建 IVFFlat 近似最近邻索引以加速向量检索

-- 1. 启用 pgvector 扩展（若尚未启用）
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 添加 embedding 列（若已存在则跳过）
ALTER TABLE qnh_products
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- 3. 创建 IVFFlat 索引（适合 1k~1M 行；lists 参数 = sqrt(rows)，此处取 100）
--    使用余弦距离（vector_cosine_ops）以匹配 <-> 算子的语义
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_indexes
        WHERE  tablename = 'qnh_products'
          AND  indexname  = 'idx_qnh_products_embedding_ivfflat'
    ) THEN
        -- 需要表中有足够的非 NULL 行才能建索引；使用 CREATE INDEX CONCURRENTLY 避免锁表
        -- 注意：CONCURRENTLY 在事务块中不可用，此处用普通 CREATE INDEX 加 IF NOT EXISTS 保护
        CREATE INDEX idx_qnh_products_embedding_ivfflat
            ON qnh_products
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
    END IF;
END
$$;

-- 4. 同样为 products 表（若存在）添加 embedding 列和索引
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'products'
    ) THEN
        -- 添加列
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = 'products'
              AND column_name  = 'embedding'
        ) THEN
            EXECUTE 'ALTER TABLE products ADD COLUMN embedding vector(1536)';
        END IF;

        -- 添加索引
        IF NOT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'products'
              AND indexname  = 'idx_products_embedding_ivfflat'
        ) THEN
            EXECUTE 'CREATE INDEX idx_products_embedding_ivfflat
                     ON products
                     USING ivfflat (embedding vector_cosine_ops)
                     WITH (lists = 100)';
        END IF;
    END IF;
END
$$;
