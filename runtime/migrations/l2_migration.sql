-- ============================================================================
-- Brand Atlas Knowledge Graph — L2 行业知识层数据库迁移
-- 版本: 1.0.0
-- 创建日期: 2026-08-11
-- 描述: 第二层行业知识层 + L2/L3 共享知识业务表
-- 参考: industry_knowledge/README.md §10.2 建议表, §10.3 索引
-- 关联: L1 定义注册库 database/schema.sql（本迁移为独立业务迁移）
-- 前置: L1 migration (database/schema.sql) 必须先执行，因为 entity/relation
--       的 entity_type/relation_type 引用 L1 的 entity_type/relation_type 表。
-- 后置: brand_knowledge/database/brand_l3_migration.sql（L3 依赖本迁移的
--       entity、evidence、document 表）。
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 辅助函数
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 1. industry_scope — 行业研究范围
-- ============================================================================
CREATE TABLE IF NOT EXISTS industry_scope (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    industry_id     VARCHAR(50),
    canonical_name  TEXT NOT NULL,
    market          VARCHAR(20),
    language        VARCHAR(20),
    boundaries      TEXT,
    excluded_scope  TEXT,
    time_start      DATE,
    time_end        DATE,
    focus_dimensions JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE industry_scope IS '行业研究范围定义';

-- ============================================================================
-- 2. industry_requirement — L2 行业数据需求及其版本
-- ============================================================================
CREATE TABLE IF NOT EXISTS industry_requirement (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requirement_id  VARCHAR(100) NOT NULL UNIQUE,
    industry_id     VARCHAR(50),
    scope_id        UUID REFERENCES industry_scope(id),
    schema_version  VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    required_dimensions JSONB NOT NULL,
    source_requirements JSONB,
    report_contract JSONB,
    content_hash    VARCHAR(64),
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE industry_requirement IS 'L2 行业数据需求及版本';

-- ============================================================================
-- 3. research_report — geo-research 行业报告及交付状态
-- ============================================================================
CREATE TABLE IF NOT EXISTS research_report (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id       VARCHAR(100) NOT NULL UNIQUE,
    requirement_id  UUID REFERENCES industry_requirement(id),
    geo_research_run_id VARCHAR(100),
    report_path     TEXT,
    report_hash     VARCHAR(64),
    model           VARCHAR(100),
    prompt_version  VARCHAR(50),
    coverage_status VARCHAR(20),
    validation_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    report_metadata JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE research_report IS 'geo-research 行业报告及交付状态';

-- ============================================================================
-- 4. report_section — 报告章节、表格和行号结构
-- ============================================================================
CREATE TABLE IF NOT EXISTS report_section (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id       UUID NOT NULL REFERENCES research_report(id),
    section_code    VARCHAR(50),
    section_title   TEXT,
    section_order   INT,
    start_line      INT,
    end_line        INT,
    content_type    VARCHAR(20) DEFAULT 'markdown',
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE report_section IS '报告章节结构';

-- ============================================================================
-- 5. source_instance — 实际来源实例
-- ============================================================================
CREATE TABLE IF NOT EXISTS source_instance (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    industry_id     VARCHAR(50),
    source_class    VARCHAR(50),
    source_type     VARCHAR(50) REFERENCES entity_type(type_code),
    publisher       TEXT,
    title           TEXT,
    canonical_url   TEXT,
    external_path   TEXT,
    retrieved_at    TIMESTAMPTZ,
    published_at    TIMESTAMPTZ,
    document_version VARCHAR(50),
    language        VARCHAR(20),
    mime_type       VARCHAR(50),
    content_hash    VARCHAR(64),
    access_level    VARCHAR(20) NOT NULL DEFAULT 'internal',
    allowed_task_types JSONB,
    license         TEXT,
    owner           TEXT,
    discovered_by   VARCHAR(100),
    approval_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    l2_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    attributes      JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'registered',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_ss_access CHECK (access_level IN ('public','internal','confidential','restricted')),
    CONSTRAINT chk_ss_status CHECK (status IN ('registered','gate_passed','parsing','extracted','rejected','inactive'))
);
COMMENT ON TABLE source_instance IS '实际来源实例';

-- ============================================================================
-- 6. document — 文档和版本元数据
-- ============================================================================
CREATE TABLE IF NOT EXISTS document (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    source_id       UUID REFERENCES source_instance(id),
    canonical_url   TEXT,
    document_version VARCHAR(50),
    title           TEXT,
    language        VARCHAR(20),
    mime_type       VARCHAR(50),
    content_hash    VARCHAR(64),
    access_level    VARCHAR(20) NOT NULL DEFAULT 'internal',
    allowed_task_types JSONB,
    allowed_output_channels JSONB,
    contains_pii    BOOLEAN NOT NULL DEFAULT FALSE,
    contains_trade_secret BOOLEAN NOT NULL DEFAULT FALSE,
    embargo_until   TIMESTAMPTZ,
    owner_department TEXT,
    properties      JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE document IS '文档和版本元数据';
COMMENT ON COLUMN document.id IS '被 L3 brand_l3_migration.content_inventory.document_id 引用';

-- ============================================================================
-- 7. document_chunk — 结构化语义单元
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_chunk (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES document(id),
    chunk_index     INT,
    chunk_type      VARCHAR(20),   -- section_chunk / evidence_span / context_window
    heading_path    TEXT,
    start_offset    INT,
    end_offset      INT,
    page_start      INT,
    page_end        INT,
    text            TEXT,
    content_hash    VARCHAR(64),
    access_level    VARCHAR(20) DEFAULT 'internal',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE document_chunk IS '结构化语义单元';

-- ============================================================================
-- 8. entity — L2/L3 实体实例
-- ============================================================================
CREATE TABLE IF NOT EXISTS entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID,
    brand_id        UUID,
    entity_id       VARCHAR(100) UNIQUE,
    entity_type     VARCHAR(50) REFERENCES entity_type(type_code),
    canonical_name  TEXT NOT NULL,
    semantic_subtype VARCHAR(50),
    scope           VARCHAR(20) NOT NULL DEFAULT 'shared',
    industry_id     VARCHAR(50),
    market          VARCHAR(20),
    language        VARCHAR(20),
    attributes      JSONB,
    source_refs     JSONB,
    verification_status VARCHAR(30),
    confidence      NUMERIC(4,3),
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    valid_from      TIMESTAMPTZ,
    valid_to        TIMESTAMPTZ,
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_entity_type CHECK (entity_type IN (
        'brand','product','industry','category','audience','use_case','problem',
        'topic','prompt','competitor','content','source','fact','claim','observation',
        'capability','decision_factor','job_to_be_done','outcome','organization','product_version')),
    CONSTRAINT chk_entity_status CHECK (status IN ('active','inactive','deprecated'))
);
COMMENT ON TABLE entity IS 'L2/L3 实体实例（唯一权威实体表）';
COMMENT ON COLUMN entity.id IS '被 L3 brand_l3_migration 的 brand_workspace/assertion/brand_mapping/product_record 引用';

-- 生成列：从 JSONB 扁平化常用查询字段
ALTER TABLE entity ADD COLUMN IF NOT EXISTS owner_brand UUID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_business_unique
    ON entity (tenant_id, entity_type, canonical_name, COALESCE(owner_brand::text, '') )
    WHERE tenant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_entity_type ON entity(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_status ON entity(status);

-- ============================================================================
-- 9. entity_alias — 实体别名
-- ============================================================================
CREATE TABLE IF NOT EXISTS entity_alias (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL REFERENCES entity(id),
    alias_name      TEXT NOT NULL,
    alias_type      VARCHAR(20),   -- pref_label / alt_label / hidden_label
    language        VARCHAR(20),
    is_preferred    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, alias_name)
);
COMMENT ON TABLE entity_alias IS '实体别名';

-- ============================================================================
-- 10. relation — 实体关系实例
-- ============================================================================
CREATE TABLE IF NOT EXISTS relation (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_id      UUID NOT NULL REFERENCES entity(id),
    relation_type   VARCHAR(50) REFERENCES relation_type(relation_code),
    object_id       UUID NOT NULL REFERENCES entity(id),
    tenant_id       UUID,
    scope           JSONB,
    confidence      NUMERIC(4,3),
    verification_status VARCHAR(30),
    source_refs     JSONB,
    valid_from      TIMESTAMPTZ,
    valid_to        TIMESTAMPTZ,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE relation IS '实体关系实例';
CREATE INDEX IF NOT EXISTS idx_relation_subject ON relation(subject_id);
CREATE INDEX IF NOT EXISTS idx_relation_object ON relation(object_id);
CREATE INDEX IF NOT EXISTS idx_relation_type ON relation(relation_type);

-- ============================================================================
-- 11. statement — fact/claim/observation/inference
-- ============================================================================
CREATE TABLE IF NOT EXISTS statement (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    statement_id    VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    subject_entity_id UUID REFERENCES entity(id),
    predicate       VARCHAR(80),
    object_entity_id UUID REFERENCES entity(id),
    object_value    JSONB,
    statement_text  TEXT NOT NULL,
    statement_class VARCHAR(20) NOT NULL,
    assertion_kind  VARCHAR(30),
    claimant_id     UUID,
    scope           JSONB NOT NULL DEFAULT '{}'::jsonb,
    limitations     JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_status VARCHAR(30),
    publication_status VARCHAR(30),
    access_level    VARCHAR(20) NOT NULL DEFAULT 'internal',
    confidence      NUMERIC(4,3),
    valid_from      TIMESTAMPTZ,
    valid_to        TIMESTAMPTZ,
    supersedes_id   UUID REFERENCES statement(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_stmt_class CHECK (statement_class IN ('fact','claim','observation','inference')),
    CONSTRAINT chk_stmt_value CHECK (object_entity_id IS NOT NULL OR object_value IS NOT NULL)
);
COMMENT ON TABLE statement IS 'fact/claim/observation/inference 统一陈述';
CREATE INDEX IF NOT EXISTS idx_stmt_tenant ON statement(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stmt_subject ON statement(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_stmt_class ON statement(statement_class);

-- ============================================================================
-- 12. evidence — 原文证据片段
-- ============================================================================
CREATE TABLE IF NOT EXISTS evidence (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_id     VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    source_id       UUID REFERENCES source_instance(id),
    document_id     UUID REFERENCES document(id),
    chunk_id        UUID REFERENCES document_chunk(id),
    content_path    TEXT,
    page_ref        TEXT,
    start_offset    INT,
    end_offset      INT,
    quote           TEXT,
    content_hash    VARCHAR(64),
    access_level    VARCHAR(20) NOT NULL DEFAULT 'internal',
    support_status  VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE evidence IS '原文证据片段';
COMMENT ON COLUMN evidence.id IS '被 L3 brand_l3_migration.assertion_evidence.evidence_id 引用';

-- ============================================================================
-- 13. relation_evidence / statement_evidence — 关系/陈述与证据多对多
-- ============================================================================
CREATE TABLE IF NOT EXISTS relation_evidence (
    relation_id     UUID NOT NULL REFERENCES relation(id),
    evidence_id     UUID NOT NULL REFERENCES evidence(id),
    support_status  VARCHAR(20),
    support_reason  TEXT,
    verifier_version VARCHAR(100),
    PRIMARY KEY (relation_id, evidence_id)
);
COMMENT ON TABLE relation_evidence IS '关系与证据多对多';

CREATE TABLE IF NOT EXISTS statement_evidence (
    statement_id    UUID NOT NULL REFERENCES statement(id),
    evidence_id     UUID NOT NULL REFERENCES evidence(id),
    support_status  VARCHAR(20),
    support_reason  TEXT,
    verifier_version VARCHAR(100),
    PRIMARY KEY (statement_id, evidence_id)
);
COMMENT ON TABLE statement_evidence IS '陈述与证据多对多';

-- ============================================================================
-- 14. report_candidate — 从报告抽取的知识候选
-- ============================================================================
CREATE TABLE IF NOT EXISTS report_candidate (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_id       UUID NOT NULL REFERENCES research_report(id),
    section_id      UUID REFERENCES report_section(id),
    section_code    VARCHAR(50),
    report_span     TEXT,
    statement       TEXT NOT NULL,
    candidate_type  VARCHAR(50),
    citation_labels JSONB,
    normalized_statement_hash VARCHAR(64),
    knowledge_candidate_type VARCHAR(50),
    status          VARCHAR(20) NOT NULL DEFAULT 'candidate',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_rc_status CHECK (status IN (
        'candidate','resolved','verified','promoted','rejected','duplicate'))
);
COMMENT ON TABLE report_candidate IS '从报告抽取的知识候选';

-- ============================================================================
-- 15. citation_resolution — 报告 [S#] 到原始证据的映射和验证
-- ============================================================================
CREATE TABLE IF NOT EXISTS citation_resolution (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_candidate_id UUID REFERENCES report_candidate(id),
    citation_label  VARCHAR(20),
    source_id       UUID REFERENCES source_instance(id),
    evidence_id     UUID REFERENCES evidence(id),
    original_url    TEXT,
    access_status   VARCHAR(20),
    evidence_location TEXT,
    support_status  VARCHAR(20),
    support_reason  TEXT,
    verifier_version VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE citation_resolution IS '报告引用到证据的映射和验证';

-- ============================================================================
-- 16. external_import_record — geo-research 导入血缘
-- ============================================================================
CREATE TABLE IF NOT EXISTS external_import_record (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    import_id       VARCHAR(100) UNIQUE,
    requirement_id  VARCHAR(100),
    package_ref     TEXT,
    geo_research_run_id VARCHAR(100),
    report_path     TEXT,
    package_hash    VARCHAR(64),
    status          VARCHAR(20) NOT NULL DEFAULT 'imported',
    registered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB
);
COMMENT ON TABLE external_import_record IS '外部文件级导入血缘，不直接作为知识事实';

-- ============================================================================
-- 17. topic_membership — 主题层级和成员关系
-- ============================================================================
CREATE TABLE IF NOT EXISTS topic_membership (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_topic_id UUID REFERENCES entity(id),
    child_topic_id  UUID REFERENCES entity(id),
    membership_type VARCHAR(20),
    confidence      NUMERIC(4,3),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (parent_topic_id, child_topic_id, membership_type)
);
COMMENT ON TABLE topic_membership IS '主题层级和成员关系';

-- ============================================================================
-- 18. ingestion_job — 采集任务
-- ============================================================================
CREATE TABLE IF NOT EXISTS ingestion_job (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          VARCHAR(100) UNIQUE,
    job_type        VARCHAR(50),
    industry_id     VARCHAR(50),
    requirement_id  VARCHAR(100),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE ingestion_job IS '采集任务';

-- ============================================================================
-- 19. extraction_run — 抽取模型和版本
-- ============================================================================
CREATE TABLE IF NOT EXISTS extraction_run (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          VARCHAR(100) UNIQUE,
    extraction_profile VARCHAR(100),
    model           VARCHAR(100),
    model_version   VARCHAR(50),
    prompt_version  VARCHAR(50),
    inputs          JSONB,
    outputs_summary JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE extraction_run IS '抽取模型和版本';

-- ============================================================================
-- 20. review_queue — 人工审核队列
-- ============================================================================
CREATE TABLE IF NOT EXISTS review_queue (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    target_type     VARCHAR(30),
    target_id       UUID,
    tenant_id       UUID,
    review_type     VARCHAR(50),
    priority        INT DEFAULT 0,
    reason          TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    assigned_to     TEXT,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    decision        VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE review_queue IS '人工审核队列';

-- ============================================================================
-- 21. graph_outbox — PostgreSQL → Neo4j 事件队列
-- ============================================================================
CREATE TABLE IF NOT EXISTS graph_outbox (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type  VARCHAR(50) NOT NULL,
    aggregate_id    UUID NOT NULL,
    event_type      VARCHAR(30) NOT NULL,
    payload         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ,
    retry_count     INT NOT NULL DEFAULT 0,
    error           TEXT
);
COMMENT ON TABLE graph_outbox IS 'PostgreSQL 到 Neo4j 的同步事件队列';

-- ============================================================================
-- updated_at 触发器
-- ============================================================================
DO $$
DECLARE tbl TEXT;
BEGIN
    FOR tbl IN SELECT table_name FROM information_schema.columns
        WHERE column_name='updated_at' AND table_schema='public'
        AND table_name IN ('industry_scope','industry_requirement','research_report',
            'source_instance','document','entity','relation','statement','evidence',
            'report_candidate','citation_resolution','ingestion_job','extraction_run','review_queue')
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;', tbl, tbl);
        EXECUTE format('CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION kg_update_updated_at();', tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 完成
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE 'L2 Industry Knowledge Layer migration v1.0.0 initialized.';
    RAISE NOTICE 'Tables: industry_scope, industry_requirement, research_report, report_section, source_instance, document, document_chunk, entity, entity_alias, relation, statement, evidence, relation_evidence, statement_evidence, report_candidate, citation_resolution, external_import_record, topic_membership, ingestion_job, extraction_run, review_queue, graph_outbox';
END;
$$ LANGUAGE plpgsql;