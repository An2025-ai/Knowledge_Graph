-- ============================================================================
-- Brand Atlas Knowledge Graph — L2/L3 统一数据库 schema（同一个 database 文件）
-- 版本: 2.0.0
-- 创建日期: 2026-08-26
-- 描述: 按《L2/L3 知识图谱构建技术执行方案》§9/§10 统一证据层 → 文档级候选知识层
--       → 门禁候选知识层 → active graph 的数据结构。本文件为 L2 行业层与 L3 品牌层的
--       唯一业务 schema（原 l2_migration.sql / brand_l3_migration.sql / vector_migration.sql
--       已并入），覆盖 pgvector 候选向量表。
-- 参考: database/schema.sql（L1 定义注册库，前置必须已执行）
-- 前置: L1 migration (database/schema.sql) 必须先执行，因为 entity/relation/statement
--       的 entity_type/relation_type 直接引用 L1 的 def 表。
-- 说明:
--   - 保留 active graph（entity/relation/statement/assertion）与支撑表
--     （tenant/source/document/evidence/review_queue/graph_outbox 等），
--     neo4j projection 与 visualize export 依赖其结构。
--   - 删除旧中间过程表：report_section / report_candidate / citation_resolution /
--     document_chunk / extraction_candidate，统一由 evidence_spans / evidence_units /
--     knowledge_candidates / gate_candidate_* 替代（§9）。
--   - entity 移除过时的硬编码实体类型 CHECK（改由 L1 entity_type 外键 + L1 registry
--     权威约束），避免拒绝 L1 本体的合法类型（如 business_line / brand_claim）。
-- ============================================================================

-- ============================================================================
-- 扩展
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

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
-- 1. industry_scope — L2 行业研究范围
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
-- 2. industry_requirement — L2 行业数据需求
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
-- 3. source_instance — 实际来源实例（L2 信源建档）
-- ============================================================================
CREATE TABLE IF NOT EXISTS source_instance (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    industry_id     VARCHAR(50),
    source_class    VARCHAR(50),
    source_type     VARCHAR(50),
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
ALTER TABLE source_instance DROP CONSTRAINT IF EXISTS source_instance_source_type_fkey;

-- ============================================================================
-- 4. document — 文档元数据（§9 documents；L2 文章 / L3 品牌文件共用）
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
COMMENT ON COLUMN document.id IS '被 content_inventory / evidence / evidence_spans / evidence_units / knowledge_candidates 引用';
-- §9 语义字段（若旧库已有该表则幂等补齐）
ALTER TABLE document ADD COLUMN IF NOT EXISTS layer VARCHAR(20);
ALTER TABLE document ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE document ADD COLUMN IF NOT EXISTS original_url TEXT;
ALTER TABLE document ADD COLUMN IF NOT EXISTS source_status VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_document_layer ON document (layer);
CREATE INDEX IF NOT EXISTS idx_document_hash ON document (content_hash);

-- ============================================================================
-- 5. 证据层（§9.1）
-- ============================================================================

-- evidence_spans — 正文解析后的最小证据片段
CREATE TABLE IF NOT EXISTS evidence_spans (
    span_id         VARCHAR(64) PRIMARY KEY,
    document_id     UUID NOT NULL REFERENCES document(id),
    span_type       VARCHAR(20) NOT NULL CHECK (span_type IN
        ('heading','paragraph','list_item','table','caption')),
    text            TEXT NOT NULL,
    heading_path    JSONB NOT NULL DEFAULT '[]'::jsonb,
    order_index     INT NOT NULL DEFAULT 0,
    locator         JSONB,
    char_start      INT,
    char_end        INT,
    embedding_id    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE evidence_spans IS '正文解析后的最小证据片段（§9.1）';
CREATE INDEX IF NOT EXISTS idx_es_document ON evidence_spans (document_id, order_index);

-- evidence_units — 合并后的证据单元（一条被抽取的知识所依据）
CREATE TABLE IF NOT EXISTS evidence_units (
    unit_id         VARCHAR(64) PRIMARY KEY,
    document_id     UUID NOT NULL REFERENCES document(id),
    source_span_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    text            TEXT NOT NULL,
    heading_path    JSONB NOT NULL DEFAULT '[]'::jsonb,
    merge_reason    JSONB NOT NULL DEFAULT '[]'::jsonb,
    token_count     INT NOT NULL DEFAULT 0,
    embedding_id    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE evidence_units IS '合并后的证据单元（§9.1）';
CREATE INDEX IF NOT EXISTS idx_eu_document ON evidence_units (document_id);

-- ============================================================================
-- 6. 文档级候选知识层（§9.2）
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_candidates (
    candidate_id    VARCHAR(64) PRIMARY KEY,
    profile_id      VARCHAR(50) NOT NULL CHECK (profile_id IN ('l2_industry','l3_brand')),
    layer           VARCHAR(20) NOT NULL CHECK (layer IN ('l2_industry','l3_brand')),
    document_id     UUID NOT NULL REFERENCES document(id),
    evidence_unit_id VARCHAR(64) REFERENCES evidence_units(unit_id),
    source_span_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    candidate_type  VARCHAR(20) NOT NULL CHECK (candidate_type IN
        ('relation','metric','statement','event')),
    subject         JSONB NOT NULL DEFAULT '{}'::jsonb,
    predicate       JSONB,
    object          JSONB,
    metric          JSONB,
    statement       JSONB,
    event           JSONB,
    evidence_text   TEXT NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    extraction_method JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding_id    VARCHAR(64),
    schema_valid    BOOLEAN NOT NULL DEFAULT TRUE,
    -- 溯源字段（文章失效/撤稿/更新时按 document_id/content_hash 追踪）
    source_status   VARCHAR(20) CHECK (source_status IN ('active','expired','retracted','updated')),
    published_at    TIMESTAMPTZ,
    original_url    TEXT,
    content_hash    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE knowledge_candidates IS '文档级候选知识（§9.2），保留完整溯源信息';
CREATE INDEX IF NOT EXISTS idx_kc_document ON knowledge_candidates (document_id);
CREATE INDEX IF NOT EXISTS idx_kc_type ON knowledge_candidates (candidate_type);
CREATE INDEX IF NOT EXISTS idx_kc_profile ON knowledge_candidates (profile_id);

-- ============================================================================
-- 7. 门禁候选知识层（§9.3）
-- ============================================================================

-- gate_candidate_entities — 跨文档融合后的门禁候选实体
CREATE TABLE IF NOT EXISTS gate_candidate_entities (
    entity_id       VARCHAR(64) PRIMARY KEY,
    profile_id      VARCHAR(50) NOT NULL CHECK (profile_id IN ('l2_industry','l3_brand')),
    layer           VARCHAR(20) NOT NULL CHECK (layer IN ('l2_industry','l3_brand')),
    tenant_id       UUID,
    entity_type     VARCHAR(50) NOT NULL,
    name            TEXT NOT NULL,
    aliases         JSONB NOT NULL DEFAULT '[]'::jsonb,
    description     TEXT,
    source_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence      NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    embedding_id    VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE gate_candidate_entities IS '跨文档融合后的门禁候选实体（§9.3）';
CREATE INDEX IF NOT EXISTS idx_gce_type ON gate_candidate_entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_gce_profile ON gate_candidate_entities (profile_id);

-- gate_candidate_knowledge — 跨文档融合后的门禁候选知识（relation/metric/statement/event）
CREATE TABLE IF NOT EXISTS gate_candidate_knowledge (
    knowledge_id    VARCHAR(64) PRIMARY KEY,
    profile_id      VARCHAR(50) NOT NULL CHECK (profile_id IN ('l2_industry','l3_brand')),
    layer           VARCHAR(20) NOT NULL CHECK (layer IN ('l2_industry','l3_brand')),
    tenant_id       UUID,
    knowledge_type  VARCHAR(20) NOT NULL CHECK (knowledge_type IN
        ('relation','metric','statement','event')),
    subject_entity_id VARCHAR(64) REFERENCES gate_candidate_entities(entity_id),
    predicate_type  VARCHAR(50),
    object_entity_id VARCHAR(64) REFERENCES gate_candidate_entities(entity_id),
    statement_text  TEXT,
    metric_name     VARCHAR(80),
    metric_value    JSONB,
    event           JSONB,
    scope           JSONB NOT NULL DEFAULT '{}'::jsonb,
    time_scope      JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    latest_published_at TIMESTAMPTZ,
    confidence      NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    embedding_id    VARCHAR(64),
    gate_status     VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (gate_status IN ('pending','passed','rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE gate_candidate_knowledge IS '跨文档融合后的门禁候选知识（§9.3），位于 knowledge_candidates 与 active graph 之间';
CREATE INDEX IF NOT EXISTS idx_gck_type ON gate_candidate_knowledge (knowledge_type);
CREATE INDEX IF NOT EXISTS idx_gck_status ON gate_candidate_knowledge (gate_status);
CREATE INDEX IF NOT EXISTS idx_gck_profile ON gate_candidate_knowledge (profile_id);

-- ============================================================================
-- 8. entity — 实体实例（唯一权威实体表；active graph）
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
    CONSTRAINT chk_entity_status CHECK (status IN ('candidate','active','inactive','deprecated'))
);
COMMENT ON TABLE entity IS 'L2/L3 实体实例（唯一权威实体表）';
COMMENT ON COLUMN entity.id IS '被 brand_workspace / assertion / product_record 引用';
-- 移除过时的硬编码实体类型 CHECK：实体类型合法性由 L1 entity_type 外键 + L1 registry 权威约束
ALTER TABLE entity DROP CONSTRAINT IF EXISTS chk_entity_type;

CREATE TABLE IF NOT EXISTS entity_alias (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL REFERENCES entity(id),
    alias_name      TEXT NOT NULL,
    alias_type      VARCHAR(30) DEFAULT 'alt_label',
    is_preferred    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, alias_name)
);
COMMENT ON TABLE entity_alias IS '实体别名';

-- ============================================================================
-- 9. relation / statement — active graph 边与陈述
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
-- 10. evidence — 原文证据片段（active graph 知识所依据的原文）
-- ============================================================================
CREATE TABLE IF NOT EXISTS evidence (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_id     VARCHAR(100) UNIQUE,
    tenant_id       UUID,
    source_id       UUID REFERENCES source_instance(id),
    document_id     UUID REFERENCES document(id),
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
COMMENT ON COLUMN evidence.id IS '被 assertion_evidence.evidence_id / relation_evidence.evidence_id / statement_evidence.evidence_id 引用';

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
-- 11. L3 品牌层表（并入统一 schema）
-- ============================================================================

-- tenant — 客户租户，L3 数据安全边界
CREATE TABLE IF NOT EXISTS tenant (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200) NOT NULL,
    tenant_key      VARCHAR(100) NOT NULL UNIQUE,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_tenant_status CHECK (status IN ('active', 'inactive', 'suspended'))
);
COMMENT ON TABLE tenant IS '客户租户，L3 数据安全边界';

CREATE TABLE IF NOT EXISTS brand_workspace (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  brand_entity_id UUID NOT NULL REFERENCES entity(id),
  market VARCHAR(20) NOT NULL,
  language VARCHAR(20) NOT NULL,
  default_access_level VARCHAR(20) NOT NULL,
  onboarding_request JSONB NOT NULL,
  status VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, brand_entity_id, market, language)
);
COMMENT ON TABLE brand_workspace IS '品牌接入范围和默认权限';

CREATE TABLE IF NOT EXISTS assertion (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  brand_id UUID NOT NULL,
  subject_id UUID NOT NULL REFERENCES entity(id),
  predicate VARCHAR(80) NOT NULL,
  object_entity_id UUID REFERENCES entity(id),
  object_value JSONB,
  statement_text TEXT NOT NULL,
  statement_class VARCHAR(20) NOT NULL,
  assertion_kind VARCHAR(30) NOT NULL,
  claimant_id UUID,
  scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
  verification_status VARCHAR(30) NOT NULL,
  publication_status VARCHAR(30) NOT NULL,
  access_level VARCHAR(20) NOT NULL,
  confidence NUMERIC(4,3),
  valid_from TIMESTAMPTZ,
  valid_to TIMESTAMPTZ,
  supersedes_id UUID REFERENCES assertion(id),
  status VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (statement_class IN ('fact','claim','observation','inference')),
  CHECK (object_entity_id IS NOT NULL OR object_value IS NOT NULL)
);
COMMENT ON TABLE assertion IS '统一事实、主张和推断，附证据和条件';

CREATE TABLE IF NOT EXISTS assertion_evidence (
  assertion_id UUID NOT NULL REFERENCES assertion(id),
  evidence_id UUID NOT NULL REFERENCES evidence(id),
  support_status VARCHAR(20) NOT NULL,
  support_reason TEXT,
  verifier_version VARCHAR(100),
  PRIMARY KEY (assertion_id, evidence_id)
);
COMMENT ON TABLE assertion_evidence IS 'Assertion 与 Evidence 多对多支持关系';

CREATE TABLE IF NOT EXISTS claim_policy (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  brand_id UUID NOT NULL,
  assertion_id UUID REFERENCES assertion(id),
  normalized_phrase TEXT,
  policy_type VARCHAR(20) NOT NULL,
  allowed_channels JSONB NOT NULL,
  required_qualifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
  approval_owner TEXT,
  effective_from TIMESTAMPTZ,
  effective_to TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL
);
COMMENT ON TABLE claim_policy IS '品牌允许、限制和禁止的表述口径';

CREATE TABLE IF NOT EXISTS brand_source_policy (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL,
    brand_id            UUID NOT NULL,
    source_type         VARCHAR(50) NOT NULL,
    allowed             BOOLEAN NOT NULL DEFAULT TRUE,
    default_authority   VARCHAR(20),
    allowed_output_channels JSONB NOT NULL DEFAULT '[]'::jsonb,
    license_note        TEXT,
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, brand_id, source_type),
    CONSTRAINT chk_bsp_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);
COMMENT ON TABLE brand_source_policy IS '品牌接入后允许使用的来源类型和输出渠道';

CREATE TABLE IF NOT EXISTS product_record (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL,
    brand_id            UUID NOT NULL,
    product_entity_id   UUID NOT NULL REFERENCES entity(id),
    product_version     VARCHAR(100),
    deployment_type     VARCHAR(30),
    market              VARCHAR(20),
    status              VARCHAR(20) NOT NULL DEFAULT 'active',
    scope               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, brand_id, product_entity_id, product_version, market),
    CONSTRAINT chk_pr_deployment CHECK (deployment_type IS NULL OR deployment_type IN
        ('SaaS', 'private_cloud', 'on_premise', 'local', 'hybrid', 'desktop'))
);
COMMENT ON TABLE product_record IS '产品、服务和版本的属性记录';

CREATE TABLE IF NOT EXISTS knowledge_conflict (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL,
    brand_id            UUID NOT NULL,
    conflict_type       VARCHAR(40) NOT NULL,
    assert_id_a         UUID REFERENCES assertion(id),
    assert_id_b         UUID REFERENCES assertion(id),
    conflict_reason     TEXT,
    conflict_status     VARCHAR(20) NOT NULL DEFAULT 'open',
    resolution_note     TEXT,
    resolution_by       VARCHAR(200),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_kc_type CHECK (conflict_type IN
        ('naming_conflict', 'document_version_conflict', 'sla_conflict',
         'scope_conflict', 'value_conflict', 'definition_conflict', 'source_conflict')),
    CONSTRAINT chk_kc_status CHECK (conflict_status IN
        ('open', 'under_review', 'resolved', 'superseded'))
);
COMMENT ON TABLE knowledge_conflict IS '无法自动解释的差异，进入人工审核';

CREATE TABLE IF NOT EXISTS content_inventory (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL,
    brand_id                UUID NOT NULL,
    document_id             UUID REFERENCES document(id),
    content_type            VARCHAR(30) NOT NULL,
    canonical_url           TEXT,
    title                   TEXT,
    l2_topics_covered       JSONB NOT NULL DEFAULT '[]'::jsonb,
    publication_status      VARCHAR(30) NOT NULL DEFAULT 'draft',
    access_level            VARCHAR(20) NOT NULL DEFAULT 'internal',
    published_at            TIMESTAMPTZ,
    status                  VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_ci_publication CHECK (publication_status IN
        ('draft', 'review', 'published', 'unpublished', 'archived')),
    CONSTRAINT chk_ci_status CHECK (status IN ('active', 'inactive', 'archived'))
);
COMMENT ON TABLE content_inventory IS '内容资产、L2 主题覆盖和发布状态';

CREATE TABLE IF NOT EXISTS brand_snapshot (
    snapshot_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL,
    brand_id            UUID NOT NULL,
    l1_version          VARCHAR(20) NOT NULL,
    l2_snapshot_id      UUID,
    source_manifest_hash VARCHAR(64),
    entity_count        INTEGER NOT NULL DEFAULT 0,
    assertion_count     INTEGER NOT NULL DEFAULT 0,
    conflict_count      INTEGER NOT NULL DEFAULT 0,
    approved_by         VARCHAR(200),
    published_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    previous_snapshot_id UUID REFERENCES brand_snapshot(snapshot_id)
);
COMMENT ON TABLE brand_snapshot IS '可复现的品牌知识快照，用于回滚与一致性校验';

-- ============================================================================
-- 12. 跨文档/审核/血缘支撑表
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_queue_target_unique
    ON review_queue(target_type, target_id, review_type)
    WHERE status = 'pending';

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
-- 13. 候选知识向量表（pgvector，复用同一批 embedding）
-- ============================================================================
CREATE TABLE IF NOT EXISTS candidate_embedding (
    candidate_id    VARCHAR(64) PRIMARY KEY REFERENCES knowledge_candidates(candidate_id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gate_entity_embedding (
    entity_id       VARCHAR(64) PRIMARY KEY REFERENCES gate_candidate_entities(entity_id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gate_knowledge_embedding (
    knowledge_id    VARCHAR(64) PRIMARY KEY REFERENCES gate_candidate_knowledge(knowledge_id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 保留 entity_embedding（_helpers.upsert_entity 写入，实体消歧仍用）
CREATE TABLE IF NOT EXISTS entity_embedding (
    entity_id       UUID PRIMARY KEY REFERENCES entity(id),
    tenant_id       UUID,
    embedding_model TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedded_text   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW 索引（cosine 相似度）
CREATE INDEX IF NOT EXISTS idx_candidate_embedding_hnsw
    ON candidate_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gate_entity_embedding_hnsw
    ON gate_entity_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gate_knowledge_embedding_hnsw
    ON gate_knowledge_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_entity_embedding_hnsw
    ON entity_embedding USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- Active knowledge 变更 → Neo4j 事件队列
-- Candidate 行留在 PostgreSQL 直到晋级，永不进入图投影。
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_enqueue_graph_change()
RETURNS TRIGGER AS $$
DECLARE
    row_data JSONB;
    row_id UUID;
    row_status TEXT;
    change_type TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        row_data := to_jsonb(OLD);
        row_id := OLD.id;
        row_status := OLD.status;
        change_type := 'delete';
    ELSE
        row_data := to_jsonb(NEW);
        row_id := NEW.id;
        row_status := NEW.status;
        change_type := CASE WHEN row_status = 'active' THEN 'upsert' ELSE 'delete' END;
    END IF;

    IF TG_OP = 'DELETE' OR row_status = 'active'
       OR (TG_OP = 'UPDATE' AND OLD.status = 'active') THEN
        INSERT INTO graph_outbox (aggregate_type, aggregate_id, event_type, payload)
        VALUES (TG_TABLE_NAME, row_id, change_type, row_data);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['entity', 'relation', 'statement']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_graph_outbox ON %I;', tbl, tbl);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_graph_outbox AFTER INSERT OR UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION kg_enqueue_graph_change();', tbl, tbl
        );
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- assertion append + supersedes（不允许原地改活性 assertion，强制 append）
-- ============================================================================
CREATE OR REPLACE FUNCTION brand_l3_block_assertion_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'candidate'
       AND NEW.status IN ('candidate', 'active')
       AND NEW.id = OLD.id
       AND NEW.tenant_id = OLD.tenant_id
       AND NEW.brand_id = OLD.brand_id
       AND NEW.subject_id IS NOT DISTINCT FROM OLD.subject_id
       AND NEW.predicate IS NOT DISTINCT FROM OLD.predicate
       AND NEW.object_entity_id IS NOT DISTINCT FROM OLD.object_entity_id
       AND NEW.object_value IS NOT DISTINCT FROM OLD.object_value
       AND NEW.statement_text = OLD.statement_text
       AND NEW.supersedes_id IS NOT DISTINCT FROM OLD.supersedes_id THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'active assertion 不允许原地 UPDATE：修订必须 append + supersedes (PK=%s)', OLD.id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assertion_no_update ON assertion;
CREATE TRIGGER trg_assertion_no_update
    BEFORE UPDATE ON assertion
    FOR EACH ROW EXECUTE FUNCTION brand_l3_block_assertion_update();

DROP TRIGGER IF EXISTS trg_assertion_graph_outbox ON assertion;
CREATE TRIGGER trg_assertion_graph_outbox
    AFTER INSERT OR UPDATE OR DELETE ON assertion
    FOR EACH ROW EXECUTE FUNCTION kg_enqueue_graph_change();

-- ============================================================================
-- updated_at 触发器
-- ============================================================================
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT table_name FROM information_schema.columns
        WHERE column_name='updated_at' AND table_schema='public'
        AND table_name IN (
            'industry_scope','industry_requirement','source_instance','document',
            'entity','relation','statement','evidence','ingestion_job','extraction_run',
            'review_queue','knowledge_candidates','gate_candidate_entities',
            'gate_candidate_knowledge','candidate_embedding','gate_entity_embedding',
            'gate_knowledge_embedding','entity_embedding'
        )
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;', tbl, tbl);
        EXECUTE format('CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I
                        FOR EACH ROW EXECUTE FUNCTION kg_update_updated_at();', tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- L3 品牌层 updated_at（append 型审计表）
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['tenant', 'brand_source_policy', 'product_record',
                              'knowledge_conflict', 'content_inventory']
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;
            CREATE TRIGGER trg_%s_updated_at
                BEFORE UPDATE ON %I
                FOR EACH ROW EXECUTE FUNCTION kg_update_updated_at();
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- L3 多租户隔离：Row Level Security (tenant_id = current_setting('app.tenant_id'))
-- ============================================================================
CREATE OR REPLACE FUNCTION brand_l3_current_tenant()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.tenant_id', true), '')::UUID;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['brand_workspace', 'assertion',
                               'claim_policy', 'brand_source_policy', 'product_record',
                               'knowledge_conflict', 'content_inventory', 'brand_snapshot']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_select ON %I;
            CREATE POLICY rls_%s_select ON %I FOR SELECT
                USING (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_insert ON %I;
            CREATE POLICY rls_%s_insert ON %I FOR INSERT
                WITH CHECK (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_update ON %I;
            CREATE POLICY rls_%s_update ON %I FOR UPDATE
                USING (tenant_id = brand_l3_current_tenant())
                WITH CHECK (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_delete ON %I;
            CREATE POLICY rls_%s_delete ON %I FOR DELETE
                USING (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 完成
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Brand Atlas L2/L3 unified schema v2.0.0 applied.';
    RAISE NOTICE 'Evidence: documents, evidence_spans, evidence_units';
    RAISE NOTICE 'Candidate: knowledge_candidates; Gate: gate_candidate_entities, gate_candidate_knowledge';
    RAISE NOTICE 'Active graph: entity, relation, statement, assertion';
    RAISE NOTICE 'Legacy intermediate tables (report_section/report_candidate/citation_resolution/document_chunk/extraction_candidate) removed.';
END;
$$ LANGUAGE plpgsql;