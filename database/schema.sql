-- ============================================================================
-- Brand Atlas Knowledge Graph — PostgreSQL 数据库 Schema
-- 版本: 1.0.0
-- 创建日期: 2026-08-07
-- 描述: 第一层通用知识层的数据库表结构，对应 common_knowledge/ 中的 YAML 定义
-- 参考: common_knowledge/ontology/entities.yaml, relations.yaml
-- ============================================================================

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 1. knowledge_definition — 知识定义元数据
-- 管理所有 YAML 文件的版本和发布状态
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_definition (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_path       VARCHAR(500) NOT NULL UNIQUE,        -- 如 ontology/entities.yaml
    file_name       VARCHAR(200) NOT NULL,               -- 如 entities.yaml
    category        VARCHAR(100) NOT NULL,               -- ontology / intents / sources / tasks / policies / examples
    version         VARCHAR(20) NOT NULL,                -- 语义化版本 x.y.z
    status          VARCHAR(20) NOT NULL DEFAULT 'active', -- active / inactive / deprecated
    description     TEXT,
    content_hash    VARCHAR(64),                          -- 文件内容的 SHA-256
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_kd_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

COMMENT ON TABLE knowledge_definition IS '知识定义文件元数据，记录每个 YAML 文件的版本和发布状态';
COMMENT ON COLUMN knowledge_definition.file_path IS '相对于 common_knowledge/ 的文件路径';
COMMENT ON COLUMN knowledge_definition.content_hash IS '文件内容的 SHA-256 哈希，用于变更检测';

-- ============================================================================
-- 2. knowledge_version — 版本变更记录
-- 记录每次定义变更的详细历史
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_version (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    definition_id   UUID NOT NULL REFERENCES knowledge_definition(id) ON DELETE CASCADE,
    version         VARCHAR(20) NOT NULL,                -- 变更后的版本号
    previous_version VARCHAR(20),                        -- 变更前的版本号
    change_type     VARCHAR(20) NOT NULL,                -- major / minor / patch
    change_summary  TEXT NOT NULL,                       -- 变更说明
    change_details  JSONB,                               -- 结构化变更详情
    author          VARCHAR(200),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_kv_change_type CHECK (change_type IN ('major', 'minor', 'patch'))
);

CREATE INDEX IF NOT EXISTS idx_kv_definition ON knowledge_version(definition_id);
CREATE INDEX IF NOT EXISTS idx_kv_version ON knowledge_version(version);

COMMENT ON TABLE knowledge_version IS '知识定义版本变更历史，支持回滚和审计';

-- ============================================================================
-- 3. entity_type — 实体类型注册表
-- 对应 common_knowledge/ontology/entities.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS entity_type (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_code       VARCHAR(50) NOT NULL UNIQUE,         -- 如 brand, product, industry
    canonical_name  VARCHAR(200) NOT NULL,               -- 中文名称
    canonical_name_en VARCHAR(200),                      -- 英文名称
    definition      TEXT NOT NULL,                       -- 定义描述
    examples        JSONB,                               -- 示例数组
    required_fields JSONB NOT NULL,                      -- 必需字段列表
    optional_fields JSONB,                               -- 可选字段列表
    constraints     JSONB,                               -- 约束条件
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    source_refs     JSONB,                               -- 来源引用
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_et_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_et_type_code ON entity_type(type_code);
CREATE INDEX IF NOT EXISTS idx_et_status ON entity_type(status);

COMMENT ON TABLE entity_type IS '实体类型定义，系统支持的 21 种实体类型';

-- ============================================================================
-- 4. relation_type — 关系类型注册表
-- 对应 common_knowledge/ontology/relations.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS relation_type (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    relation_code   VARCHAR(50) NOT NULL UNIQUE,         -- 如 belongs_to, operates_in
    description     TEXT NOT NULL,                       -- 关系描述
    description_en  TEXT,                                -- 英文描述
    subject_types   JSONB NOT NULL,                      -- 允许的主体实体类型数组
    object_types    JSONB NOT NULL,                      -- 允许的客体实体类型数组
    cardinality     VARCHAR(20) NOT NULL,                -- one-to-one / one-to-many / many-to-many
    bidirectional   BOOLEAN NOT NULL DEFAULT FALSE,
    inverse_relation VARCHAR(50),                        -- 反向关系代码
    confidence_required BOOLEAN NOT NULL DEFAULT FALSE,
    source_refs_required BOOLEAN NOT NULL DEFAULT FALSE,
    examples        JSONB,
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_rt_cardinality CHECK (cardinality IN ('one-to-one', 'one-to-many', 'many-to-many')),
    CONSTRAINT      chk_rt_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_rt_relation_code ON relation_type(relation_code);

COMMENT ON TABLE relation_type IS '关系类型定义，系统支持的 31 种关系类型';

-- ============================================================================
-- 5. intent_definition — 意图定义
-- 对应 common_knowledge/intents/intent_types.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS intent_definition (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    intent_code     VARCHAR(50) NOT NULL UNIQUE,         -- 如 intent_definition, intent_comparison
    name            VARCHAR(200) NOT NULL,               -- 中文名称
    name_en         VARCHAR(200),                        -- 英文名称
    decision_stage  VARCHAR(50) NOT NULL,                -- 对应决策阶段
    description     TEXT NOT NULL,
    question_patterns JSONB,                             -- 问题模式数组
    expected_answer_blocks JSONB,                        -- 期望回答结构
    preferred_evidence JSONB,                            -- 偏好证据类型
    content_types   JSONB,                               -- 推荐内容类型
    quality_checks  JSONB,                               -- 质量检查项
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_id_stage CHECK (decision_stage IN (
                        'awareness', 'problem', 'solution', 'evaluation',
                        'decision', 'implementation', 'retention'
                    )),
    CONSTRAINT      chk_id_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_id_intent_code ON intent_definition(intent_code);
CREATE INDEX IF NOT EXISTS idx_id_decision_stage ON intent_definition(decision_stage);

COMMENT ON TABLE intent_definition IS '搜索意图类型定义，包含 13 种主意图和 7 个决策阶段';

-- ============================================================================
-- 6. task_template — 任务模板
-- 对应 common_knowledge/tasks/*.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS task_template (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_code       VARCHAR(50) NOT NULL UNIQUE,         -- 如 task_brand_onboarding
    name            VARCHAR(200) NOT NULL,               -- 中文名称
    name_en         VARCHAR(200),                        -- 英文名称
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    purpose         TEXT NOT NULL,                       -- 任务目的
    description     TEXT,                                -- 详细描述
    required_context JSONB,                              -- 必需上下文
    optional_context JSONB,                              -- 可选上下文
    output_schema   VARCHAR(100),                        -- 输出 Schema 名称
    output_fields   JSONB,                               -- 输出字段定义
    rules           JSONB,                               -- 任务规则
    failure_mode    VARCHAR(100),                        -- 失败模式
    failure_handling JSONB,                              -- 失败处理
    quality_checks  JSONB,                               -- 质量检查
    metric_refs     JSONB,                               -- 预留指标引用
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_tt_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_tt_task_code ON task_template(task_code);

COMMENT ON TABLE task_template IS '任务模板定义，系统支持的 9 种任务类型';

-- ============================================================================
-- 7. source_policy — 来源策略
-- 对应 common_knowledge/sources/source_types.yaml + authority_rules.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS source_policy (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     VARCHAR(50) NOT NULL UNIQUE,         -- 如 official, academic
    name            VARCHAR(200) NOT NULL,               -- 中文名称
    name_en         VARCHAR(200),                        -- 英文名称
    definition      TEXT NOT NULL,
    authority_level VARCHAR(20) NOT NULL,                -- high / medium / low
    suitable_for    JSONB,                               -- 适用场景
    not_suitable_for JSONB,                              -- 不适用场景
    examples        JSONB,
    validation_rules JSONB,                              -- 验证规则
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_sp_authority CHECK (authority_level IN ('high', 'medium', 'low')),
    CONSTRAINT      chk_sp_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

COMMENT ON TABLE source_policy IS '来源类型定义和权威等级策略';

-- ============================================================================
-- 8. quality_rule — 质量规则
-- 对应 common_knowledge/sources/authority_rules.yaml 中的 rules
-- ============================================================================
CREATE TABLE IF NOT EXISTS quality_rule (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_code       VARCHAR(50) NOT NULL UNIQUE,         -- 如 rule_fact_001
    rule            TEXT NOT NULL,                       -- 规则描述
    category        VARCHAR(50) NOT NULL,                -- fact_claim / source_usage / evidence_chain / quality
    applies_to      JSONB,                               -- 适用的实体或来源类型
    priority        VARCHAR(20) NOT NULL,                -- critical / high / medium / low
    description     TEXT,
    positive_example JSONB,                              -- 正例
    negative_example JSONB,                              -- 反例
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_qr_category CHECK (category IN ('fact_claim', 'source_usage', 'evidence_chain', 'quality')),
    CONSTRAINT      chk_qr_priority CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    CONSTRAINT      chk_qr_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_qr_rule_code ON quality_rule(rule_code);
CREATE INDEX IF NOT EXISTS idx_qr_category ON quality_rule(category);
CREATE INDEX IF NOT EXISTS idx_qr_priority ON quality_rule(priority);

COMMENT ON TABLE quality_rule IS '质量规则定义，20 条规则覆盖事实主张、来源适用、证据链和检索质量';

-- ============================================================================
-- 9. example_case — 示例案例
-- 对应 common_knowledge/examples/positive_examples.yaml + negative_examples.yaml
-- ============================================================================
CREATE TABLE IF NOT EXISTS example_case (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_code       VARCHAR(50) NOT NULL UNIQUE,         -- 如 ex_pos_onboarding_001
    task_id         VARCHAR(100) NOT NULL,               -- 关联的任务模板
    name            VARCHAR(300) NOT NULL,               -- 示例名称
    case_type       VARCHAR(20) NOT NULL,                -- positive / negative
    scenario        TEXT NOT NULL,                       -- 场景描述
    input_data      JSONB,                               -- 输入数据（正例）
    expected_output JSONB,                               -- 期望输出（正例）
    wrong_approach  JSONB,                               -- 错误做法（反例）
    why_wrong       TEXT,                                -- 错误原因（反例）
    violated_rule   TEXT,                                -- 违反的规则（反例）
    correct_approach JSONB,                              -- 正确做法（反例）
    demonstrates    TEXT,                                -- 展示的规则/原则
    severity        VARCHAR(20),                         -- 严重程度（反例）
    tags            JSONB,                               -- 标签
    source_refs     JSONB,                               -- 来源引用
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT      chk_ec_type CHECK (case_type IN ('positive', 'negative')),
    CONSTRAINT      chk_ec_severity CHECK (severity IS NULL OR severity IN ('critical', 'high', 'medium', 'low')),
    CONSTRAINT      chk_ec_status CHECK (status IN ('active', 'inactive', 'deprecated'))
);

CREATE INDEX IF NOT EXISTS idx_ec_task ON example_case(task_id);
CREATE INDEX IF NOT EXISTS idx_ec_type ON example_case(case_type);

COMMENT ON TABLE example_case IS '示例案例库，包含正例和反例，用于培训和回归验证';

-- ============================================================================
-- 辅助表：决策阶段
-- ============================================================================
CREATE TABLE IF NOT EXISTS decision_stage (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stage_code      VARCHAR(50) NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,
    name_en         VARCHAR(200),
    description     TEXT,
    typical_behavior TEXT,
    display_order   INT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 插入 7 个决策阶段
INSERT INTO decision_stage (stage_code, name, name_en, description, typical_behavior, display_order) VALUES
    ('awareness', '认知', 'Awareness', '用户首次意识到某个概念、问题或解决方案的存在', '浏览式搜索、宽泛的问题、概念解释类查询', 1),
    ('problem', '问题识别', 'Problem Identification', '用户明确识别到自己的痛点或需求', '症状描述、问题诊断、痛点验证', 2),
    ('solution', '方案探索', 'Solution Exploration', '用户主动寻找解决方案，了解有哪些可选方案', '品类了解、方案对比、功能研究', 3),
    ('evaluation', '比较评估', 'Evaluation', '用户在多个候选方案之间进行比较和评估', '产品对比、评测查看、价格比较', 4),
    ('decision', '购买决策', 'Decision', '用户准备做出最终选择', '价格查询、案例验证、供应商筛选', 5),
    ('implementation', '使用实施', 'Implementation', '用户已购买/采用，正在实施或使用中', '操作指南、故障排除、最佳实践', 6),
    ('retention', '复购/替代', 'Retention / Replacement', '用户评估是否续用、升级或更换现有方案', '替代方案、升级评估、续约决策', 7)
ON CONFLICT (stage_code) DO NOTHING;

-- ============================================================================
-- 触发器和函数
-- ============================================================================

-- 自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为所有含 updated_at 的表添加触发器
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT table_name FROM information_schema.columns
        WHERE column_name = 'updated_at'
        AND table_schema = 'public'
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I;
            CREATE TRIGGER trg_%s_updated_at
                BEFORE UPDATE ON %I
                FOR EACH ROW EXECUTE FUNCTION update_updated_at();
        ', tbl, tbl, tbl, tbl);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 初始数据：插入 knowledge_definition 记录
-- ============================================================================
INSERT INTO knowledge_definition (file_path, file_name, category, version, description) VALUES
    ('ontology/entities.yaml', 'entities.yaml', 'ontology', '1.2.0', '21 种实体类型定义'),
    ('ontology/relations.yaml', 'relations.yaml', 'ontology', '1.2.0', '31 种关系类型定义'),
    ('intents/intent_types.yaml', 'intent_types.yaml', 'intents', '1.0.0', '13 种意图类型 + 7 个决策阶段'),
    ('intents/prompt_patterns.yaml', 'prompt_patterns.yaml', 'intents', '1.0.0', '41 个提问词模式'),
    ('sources/source_types.yaml', 'source_types.yaml', 'sources', '1.1.0', '13 种来源类型'),
    ('sources/authority_rules.yaml', 'authority_rules.yaml', 'sources', '1.0.0', '20 条质量规则'),
    ('tasks/brand_onboarding.yaml', 'brand_onboarding.yaml', 'tasks', '1.2.0', '品牌导入任务模板'),
    ('tasks/prompt_generation.yaml', 'prompt_generation.yaml', 'tasks', '1.0.0', '提问词生成任务模板'),
    ('tasks/topic_planning.yaml', 'topic_planning.yaml', 'tasks', '1.0.0', '主题规划任务模板'),
    ('tasks/search_diagnosis.yaml', 'search_diagnosis.yaml', 'tasks', '1.0.0', '搜索诊断任务模板'),
    ('tasks/content_brief.yaml', 'content_brief.yaml', 'tasks', '1.0.0', '内容 Brief 生成任务模板'),
    ('tasks/industry_knowledge_build.yaml', 'industry_knowledge_build.yaml', 'tasks', '1.1.0', '行业知识构建任务模板'),
    ('tasks/industry_knowledge_refresh.yaml', 'industry_knowledge_refresh.yaml', 'tasks', '1.1.0', '行业知识刷新任务模板'),
    ('tasks/source_discovery.yaml', 'source_discovery.yaml', 'tasks', '1.1.0', '来源发现任务模板'),
    ('tasks/knowledge_promotion.yaml', 'knowledge_promotion.yaml', 'tasks', '1.1.0', '知识晋升任务模板'),
    ('policies/claim_policy.yaml', 'claim_policy.yaml', 'policies', '1.2.0', '事实与主张策略'),
    ('policies/conflict_policy.yaml', 'conflict_policy.yaml', 'policies', '1.2.0', '冲突处理策略'),
    ('policies/context_policy.yaml', 'context_policy.yaml', 'policies', '1.2.0', '上下文检索策略'),
    ('policies/source_discovery_policy.yaml', 'source_discovery_policy.yaml', 'policies', '1.1.0', '来源发现策略'),
    ('policies/knowledge_promotion_policy.yaml', 'knowledge_promotion_policy.yaml', 'policies', '1.1.0', '知识晋升策略'),
    ('policies/report_evidence_policy.yaml', 'report_evidence_policy.yaml', 'policies', '1.1.0', '报告证据策略'),
    ('examples/positive_examples.yaml', 'positive_examples.yaml', 'examples', '1.0.0', '26 组正确示例'),
    ('examples/negative_examples.yaml', 'negative_examples.yaml', 'examples', '1.0.0', '25 组错误示例')
ON CONFLICT (file_path) DO NOTHING;

-- ============================================================================
-- 完成
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Brand Atlas Knowledge Graph Schema v1.0.0 initialized successfully.';
    RAISE NOTICE 'Tables created: knowledge_definition, knowledge_version, entity_type, relation_type, intent_definition, task_template, source_policy, quality_rule, example_case, decision_stage';
END;
$$ LANGUAGE plpgsql;
