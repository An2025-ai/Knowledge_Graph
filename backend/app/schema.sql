PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_path TEXT,
    source_type TEXT NOT NULL DEFAULT 'local_document',
    layer TEXT NOT NULL DEFAULT 'l3_brand',
    brand_id TEXT,
    tenant_id TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_spans (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    span_type TEXT NOT NULL,
    text TEXT NOT NULL,
    heading_path_json TEXT NOT NULL DEFAULT '[]',
    order_index INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(document_id, id)
);

CREATE TABLE IF NOT EXISTS evidence_units (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_span_ids_json TEXT NOT NULL DEFAULT '[]',
    text TEXT NOT NULL,
    heading_path_json TEXT NOT NULL DEFAULT '[]',
    merge_reason_json TEXT NOT NULL DEFAULT '[]',
    token_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(document_id, id)
);

CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    candidate_type TEXT NOT NULL,
    subject_json TEXT NOT NULL DEFAULT '{}',
    predicate_type TEXT,
    object_json TEXT NOT NULL DEFAULT '{}',
    metric_json TEXT NOT NULL DEFAULT '{}',
    statement_json TEXT NOT NULL DEFAULT '{}',
    evidence_text TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    extraction_method_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    layer TEXT NOT NULL,
    brand_id TEXT,
    tenant_id TEXT,
    properties_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(type, normalized_name, layer, brand_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, target_id, relation_type, document_id)
);

CREATE TABLE IF NOT EXISTS statements (
    id TEXT PRIMARY KEY,
    subject_id TEXT REFERENCES entities(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    statement_text TEXT NOT NULL,
    statement_class TEXT NOT NULL DEFAULT 'observation',
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id TEXT PRIMARY KEY,
    document_id TEXT,
    job_type TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT 'queued',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    embedded_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, source_type, model)
);

CREATE INDEX IF NOT EXISTS idx_documents_layer ON documents(layer);
CREATE INDEX IF NOT EXISTS idx_spans_document ON evidence_spans(document_id, order_index);
CREATE INDEX IF NOT EXISTS idx_units_document ON evidence_units(document_id);
CREATE INDEX IF NOT EXISTS idx_candidates_document ON knowledge_candidates(document_id, status);
CREATE INDEX IF NOT EXISTS idx_entities_layer ON entities(layer, brand_id);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON pipeline_jobs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_embeddings_source ON embeddings(source_type, source_id);

INSERT OR IGNORE INTO schema_versions(version, applied_at)
VALUES ('desktop-1.0.0', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
