-- ============================================================================
-- Brand Atlas Knowledge Graph — pgvector / embedding / candidate migration
-- 版本: 1.0.0
-- 创建日期: 2026-08-12
-- 描述: OPTIMIZATION_TECH_PLAN.md §4.2 (extraction_candidate) + §4.6 (pgvector)
-- 前置: L1/L2/L3 migrations 必须先执行（依赖 entity/evidence/assertion 表）
-- ============================================================================

-- pgvector 扩展（PostgreSQL 必须为 pgvector 镜像，如 pgvector/pgvector:pg16）
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. extraction_candidate — 规则/词典预抽取候选（Phase 2）
-- ============================================================================
CREATE TABLE IF NOT EXISTS extraction_candidate (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID,
    brand_id        UUID,
    document_id     UUID,
    chunk_id        UUID,
    candidate_type  VARCHAR(40) NOT NULL,
    candidate_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    generator       VARCHAR(100) NOT NULL,
    confidence      NUMERIC(4,3),
    status          VARCHAR(20) NOT NULL DEFAULT 'candidate',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_ec_status CHECK (status IN ('candidate','accepted','rejected','promoted'))
);
CREATE INDEX IF NOT EXISTS idx_ec_chunk ON extraction_candidate(chunk_id);
CREATE INDEX IF NOT EXISTS idx_ec_doc ON extraction_candidate(document_id);
CREATE INDEX IF NOT EXISTS idx_ec_type ON extraction_candidate(candidate_type);

-- ============================================================================
-- 2. entity_embedding — 实体向量（Phase 3/4，供实体消歧）
-- ============================================================================
CREATE TABLE IF NOT EXISTS entity_embedding (
    entity_id       UUID PRIMARY KEY REFERENCES entity(id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 3. evidence_embedding — 证据向量（Phase 5，供语义证据核验）
-- ============================================================================
CREATE TABLE IF NOT EXISTS evidence_embedding (
    evidence_id     UUID PRIMARY KEY REFERENCES evidence(id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 4. assertion_embedding — 断言向量（供相似断言检测 + 未来 GraphRAG）
-- ============================================================================
CREATE TABLE IF NOT EXISTS assertion_embedding (
    assertion_id    UUID PRIMARY KEY REFERENCES assertion(id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- HNSW 索引（cosine 相似度）
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_entity_embedding_hnsw
    ON entity_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_embedding_hnsw
    ON evidence_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_assertion_embedding_hnsw
    ON assertion_embedding USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- updated_at 触发器
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_update_ts()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE tbl TEXT;
BEGIN
    FOR tbl IN SELECT table_name FROM information_schema.columns
        WHERE column_name='updated_at' AND table_schema='public'
        AND table_name IN ('entity_embedding','evidence_embedding','assertion_embedding')
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;', tbl, tbl);
        EXECUTE format('CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION kg_update_ts();', tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    RAISE NOTICE 'pgvector / embedding / candidate migration v1.0.0 initialized.';
END;
$$ LANGUAGE plpgsql;