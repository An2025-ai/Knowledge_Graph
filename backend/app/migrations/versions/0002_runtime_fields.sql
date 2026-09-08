-- Add fields introduced by the desktop runtime after the initial schema.

ALTER TABLE entities ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE pipeline_jobs ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE knowledge_candidates ADD COLUMN evidence_refs_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE chat_messages ADD COLUMN mode TEXT NOT NULL DEFAULT 'unknown';
