// ============================================================================
// Brand Atlas Knowledge Graph — Neo4j 初始化
// 版本: 1.0.0
// 用途: 创建唯一约束和索引，供投影服务使用
// 参考: industry_knowledge/README.md §10.4
// ============================================================================

// 实体唯一约束
CREATE CONSTRAINT n10s_entity_id IF NOT EXISTS
FOR (n:Entity) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_assertion_id IF NOT EXISTS
FOR (n:Assertion) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_evidence_id IF NOT EXISTS
FOR (n:Evidence) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_source_id IF NOT EXISTS
FOR (n:Source) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_report_id IF NOT EXISTS
FOR (n:Report) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_content_id IF NOT EXISTS
FOR (n:Content) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT n10s_conflict_id IF NOT EXISTS
FOR (n:Conflict) REQUIRE n.id IS UNIQUE;

// 实体类型索引（按 tenant 过滤）
CREATE INDEX n10s_entity_tenant_type IF NOT EXISTS
FOR (n:Entity) ON (n.tenant_id, n.entity_type);

CREATE INDEX n10s_entity_canonical IF NOT EXISTS
FOR (n:Entity) ON (n.canonical_name);