-- ============================================================================
-- Brand Atlas Knowledge Graph — L3 品牌认知层数据库迁移
-- 版本: 1.0.0
-- 创建日期: 2026-08-11
-- 描述: 第三层品牌认知层的权威业务存储表结构
-- 参考: brand_knowledge/README.md §10.1 建议表, §10.2 关键 DDL, §10.3 约束和索引
-- 关联: L1 定义注册库 database/schema.sql（本迁移为独立业务迁移，不与 L1 混淆）
--
-- 依赖的外部表（由 L2 层迁移提供）：
--   source_instance, document, document_chunk, entity, entity_alias,
--   relation, statement, evidence, review_queue, graph_outbox
-- 特别地，正确性依赖于 entity 和 evidence 表，本迁移在断言建表时引用它们。
-- 若 L2 业务表尚不存在，请先执行 L2 迁移或在建表处调整外键。
-- ============================================================================

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 辅助函数：自动更新 updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION brand_l3_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 10.1 建议表 (Part 1)
-- tenant — 客户租户
-- ============================================================================
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

-- ============================================================================
-- 10.2 关键 DDL (VERBATIM — 以下 5 张表严格按 README §10.2 原文，一字不改)
-- brand_workspace
-- ============================================================================
CREATE TABLE IF NOT EXISTS brand_workspace (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  brand_entity_id UUID NOT NULL REFERENCES entity(id),
  default_industry_id UUID,
  market VARCHAR(20) NOT NULL,
  language VARCHAR(20) NOT NULL,
  default_access_level VARCHAR(20) NOT NULL,
  onboarding_request JSONB NOT NULL,
  status VARCHAR(20) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, brand_entity_id, market, language)
);

COMMENT ON TABLE brand_workspace IS '品牌接入范围、默认权限和 L2 映射作用域';

-- ============================================================================
-- assertion
-- ============================================================================
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

-- ============================================================================
-- assertion_evidence
-- ============================================================================
CREATE TABLE IF NOT EXISTS assertion_evidence (
  assertion_id UUID NOT NULL REFERENCES assertion(id),
  evidence_id UUID NOT NULL REFERENCES evidence(id),
  support_status VARCHAR(20) NOT NULL,
  support_reason TEXT,
  verifier_version VARCHAR(100),
  PRIMARY KEY (assertion_id, evidence_id)
);

COMMENT ON TABLE assertion_evidence IS 'Assertion 与 Evidence 多对多支持关系';

-- ============================================================================
-- brand_mapping
-- ============================================================================
CREATE TABLE IF NOT EXISTS brand_mapping (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  brand_id UUID NOT NULL,
  local_entity_id UUID NOT NULL REFERENCES entity(id),
  l2_entity_id UUID NOT NULL REFERENCES entity(id),
  mapping_type VARCHAR(20) NOT NULL,
  confidence NUMERIC(4,3),
  mapping_note TEXT,
  review_status VARCHAR(20) NOT NULL,
  mapper_version VARCHAR(100),
  UNIQUE (tenant_id, local_entity_id, l2_entity_id, mapping_type)
);

COMMENT ON TABLE brand_mapping IS 'L3 原始概念到 L2 规范实体的映射';

-- ============================================================================
-- claim_policy
-- ============================================================================
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

-- ============================================================================
-- 10.1 建议表 (Part 2)
-- brand_source_policy — 该品牌允许使用的来源和输出渠道
-- ============================================================================
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

-- ============================================================================
-- product_record — 产品、服务和版本属性
-- ============================================================================
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
COMMENT ON COLUMN product_record.product_version IS '产品版本，能力与口径的版本边界';
COMMENT ON COLUMN product_record.deployment_type IS '部署方式：SaaS/私有化/本地/混合/桌面端';

-- ============================================================================
-- knowledge_conflict — 版本、数值、定义和来源冲突
-- ============================================================================
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
COMMENT ON COLUMN knowledge_conflict.conflict_type IS '服务 revision_conflict 策略的冲突类型';

-- ============================================================================
-- content_inventory — 内容资产、主题覆盖和发布状态
-- ============================================================================
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

-- ============================================================================
-- brand_snapshot — 可复现的品牌知识快照
-- ============================================================================
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
-- 10.3 约束和索引
-- ============================================================================

-- assertion 复合索引 (tenant_id, brand_id, subject_id, predicate, status)
CREATE INDEX IF NOT EXISTS idx_assertion_multi
    ON assertion (tenant_id, brand_id, subject_id, predicate, status);

-- 高频查询常用的单一索引
CREATE INDEX IF NOT EXISTS idx_assertion_brand ON assertion (tenant_id, brand_id, status);
CREATE INDEX IF NOT EXISTS idx_assertion_supersedes ON assertion (supersedes_id);
CREATE INDEX IF NOT EXISTS idx_brand_workspace_tenant ON brand_workspace (tenant_id);
CREATE INDEX IF NOT EXISTS idx_assertion_evidence_evidence ON assertion_evidence (evidence_id);
CREATE INDEX IF NOT EXISTS idx_brand_mapping_l2 ON brand_mapping (l2_entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_policy_brand ON claim_policy (tenant_id, brand_id, status);
CREATE INDEX IF NOT EXISTS idx_brand_snapshot_brand ON brand_snapshot (tenant_id, brand_id, published_at DESC);

-- JSONB 高频生成列：product_record.product_version
ALTER TABLE product_record
    DROP COLUMN IF EXISTS product_version_gen;
ALTER TABLE product_record
    ADD COLUMN product_version_gen TEXT GENERATED ALWAYS AS
        (product_version) STORED;
CREATE INDEX IF NOT EXISTS idx_product_record_version_gen
    ON product_record (product_version_gen);

-- JSONB 高频生成列：product_record.deployment_type
ALTER TABLE product_record
    DROP COLUMN IF EXISTS deployment_type_gen;
ALTER TABLE product_record
    ADD COLUMN deployment_type_gen TEXT GENERATED ALWAYS AS
        (deployment_type) STORED;
CREATE INDEX IF NOT EXISTS idx_product_record_deployment_gen
    ON product_record (deployment_type_gen);

-- JSONB 高频生成列：product_record.market
ALTER TABLE product_record
    DROP COLUMN IF EXISTS market_gen;
ALTER TABLE product_record
    ADD COLUMN market_gen TEXT GENERATED ALWAYS AS
        (market) STORED;
CREATE INDEX IF NOT EXISTS idx_product_record_market_gen
    ON product_record (market_gen);

-- assertion.scope 中的 product_version / market / deployment_type 表达式索引
CREATE INDEX IF NOT EXISTS idx_assertion_scope_product_version
    ON assertion ((scope ->> 'product_version'));
CREATE INDEX IF NOT EXISTS idx_assertion_scope_market
    ON assertion ((scope ->> 'market'));
CREATE INDEX IF NOT EXISTS idx_assertion_scope_deployment
    ON assertion ((scope ->> 'deployment_type'));

-- 权限字段复合索引（服务 permission_propagation 审核）
CREATE INDEX IF NOT EXISTS idx_assertion_access
    ON assertion (tenant_id, access_level, publication_status);

-- ============================================================================
-- 10.3 强制约束：append + supersedes，不物理覆盖证据
-- 在 assertion 上禁止原地 UPDATE，强制通过新版本 + supersedes 表达修订
-- ============================================================================
CREATE OR REPLACE FUNCTION brand_l3_block_assertion_update()
RETURNS TRIGGER AS $$
BEGIN
    -- Candidate rows are work-in-progress and may receive classification,
    -- verification metadata, or the final candidate -> active transition.
    -- Once active, every revision must be appended with supersedes_id.
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

-- L2 migration defines the shared outbox function. Only active assertions are
-- projected; candidate changes remain private to the PostgreSQL review flow.
DROP TRIGGER IF EXISTS trg_assertion_graph_outbox ON assertion;
CREATE TRIGGER trg_assertion_graph_outbox
    AFTER INSERT OR UPDATE OR DELETE ON assertion
    FOR EACH ROW EXECUTE FUNCTION kg_enqueue_graph_change();

-- ============================================================================
-- updated_at 触发器（写入型审计表，允许 append）
-- ============================================================================
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
                FOR EACH ROW EXECUTE FUNCTION brand_l3_update_updated_at();
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 10.3 多租户隔离: Row Level Security (tenant_id = current_setting('app.tenant_id'))
-- ============================================================================

-- RLS 辅助函数：当前租户
CREATE OR REPLACE FUNCTION brand_l3_current_tenant()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.tenant_id', true), '')::UUID;
END;
$$ LANGUAGE plpgsql;

-- 对含 tenant_id 的业务表启用 RLS 并创建策略
DO $$
DECLARE
    tbl TEXT;
    tenant_col TEXT := 'tenant_id';
BEGIN
    -- brand_workspace 等均含 tenant_id；for all listed tables
    FOREACH tbl IN ARRAY ARRAY['brand_workspace', 'assertion', 'brand_mapping',
                               'claim_policy', 'brand_source_policy', 'product_record',
                               'knowledge_conflict', 'content_inventory', 'brand_snapshot']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);

        -- SELECT 策略：当前租户数据
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_select ON %I;
            CREATE POLICY rls_%s_select ON %I
                FOR SELECT
                USING (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);

        -- INSERT 策略：校验写入的 tenant_id
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_insert ON %I;
            CREATE POLICY rls_%s_insert ON %I
                FOR INSERT
                WITH CHECK (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);

        -- UPDATE 策略：仅当前租户数据可更新
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_update ON %I;
            CREATE POLICY rls_%s_update ON %I
                FOR UPDATE
                USING (tenant_id = brand_l3_current_tenant())
                WITH CHECK (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);

        -- DELETE 策略：仅当前租户数据可删除
        EXECUTE format('
            DROP POLICY IF EXISTS rls_%s_delete ON %I;
            CREATE POLICY rls_%s_delete ON %I
                FOR DELETE
                USING (tenant_id = brand_l3_current_tenant());
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- RLS 备注
COMMENT ON TABLE brand_workspace IS '启用 RLS，租户过滤 tenant_id = current_setting(%''app.tenant_id%'')';
COMMENT ON TABLE assertion IS '启用 RLS，租户过滤 tenant_id = current_setting(%''app.tenant_id%'')';
COMMENT ON TABLE brand_mapping IS '启用 RLS，租户过滤 tenant_id = current_setting(%''app.tenant_id%'')';
COMMENT ON TABLE claim_policy IS '启用 RLS，租户过滤 tenant_id = current_setting(%''app.tenant_id%'')';

-- ============================================================================
-- 完成
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Brand Atlas L3 migration v1.0.0 applied.';
    RAISE NOTICE 'Tables: tenant, brand_workspace, brand_source_policy, product_record, brand_mapping, assertion, assertion_evidence, knowledge_conflict, claim_policy, content_inventory, brand_snapshot.';
    RAISE NOTICE 'RLS enabled, composite + JSONB expression indexes created, assertion append+supersedes enforced.';
END;
$$ LANGUAGE plpgsql;
