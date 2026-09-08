"""SQLite repositories for local knowledge data and durable jobs."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .database import LocalDatabase, json_loads


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def normalized_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().casefold())


def _merge_entity_properties(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge entity metadata without replacing provenance from another document."""
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    merged = {**existing, **incoming}
    source_ids: list[str] = []
    for value in (
        existing.get("source_document_ids", []),
        [existing.get("source_document_id")] if existing.get("source_document_id") else [],
        incoming.get("source_document_ids", []),
        [incoming.get("source_document_id")] if incoming.get("source_document_id") else [],
    ):
        values = value if isinstance(value, list) else [value]
        for source_id in values:
            if source_id and str(source_id) not in source_ids:
                source_ids.append(str(source_id))
    if source_ids:
        merged["source_document_id"] = source_ids[0]
        merged["source_document_ids"] = source_ids
    for key in ("aliases", "evidence_refs"):
        existing_values = existing.get(key, [])
        incoming_values = incoming.get(key, [])
        if isinstance(existing_values, list) or isinstance(incoming_values, list):
            merged_values: list[Any] = []
            for values in (
                existing_values if isinstance(existing_values, list) else [],
                incoming_values if isinstance(incoming_values, list) else [],
            ):
                for item in values:
                    if item not in merged_values:
                        merged_values.append(item)
            merged[key] = merged_values
    return merged


class KnowledgeRepository:
    """Persistence boundary used by services and API routes.

    The rest of the application does not know SQL table names.  A future
    server edition can provide a PostgreSQL implementation behind this same
    service boundary without changing the HTTP contract.
    """

    def __init__(self, db: LocalDatabase):
        self.db = db

    def document_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM documents WHERE content_hash=?", (content_hash,))
        return rows[0] if rows else None

    def document(self, document_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM documents WHERE id=?", (document_id,))
        return rows[0] if rows else None

    def save_bundle(
        self,
        document: dict[str, Any],
        spans: Iterable[dict[str, Any]],
        units: Iterable[dict[str, Any]],
        candidates: Iterable[dict[str, Any]],
        entities: Iterable[dict[str, Any]],
        relations: Iterable[dict[str, Any]],
        statements: Iterable[dict[str, Any]],
    ) -> None:
        now = document.get("updated_at") or utc_now()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO documents
                (id,title,content,source_path,source_type,layer,brand_id,tenant_id,
                 content_hash,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title, content=excluded.content,
                  source_path=excluded.source_path, updated_at=excluded.updated_at""",
                (
                    document["id"], document["title"], document["content"],
                    document.get("source_path"), document.get("source_type", "local_document"),
                    document.get("layer", "l3_brand"), document.get("brand_id"),
                    document.get("tenant_id"), document["content_hash"],
                    document.get("status", "active"), document.get("created_at", now), now,
                ),
            )

            # Re-importing the same document is deterministic and does not
            # leave stale extraction rows behind.
            conn.execute("DELETE FROM relations WHERE document_id=?", (document["id"],))
            conn.execute("DELETE FROM statements WHERE document_id=?", (document["id"],))
            conn.execute("DELETE FROM knowledge_candidates WHERE document_id=?", (document["id"],))
            conn.execute("DELETE FROM evidence_units WHERE document_id=?", (document["id"],))
            conn.execute("DELETE FROM evidence_spans WHERE document_id=?", (document["id"],))

            for span in spans:
                conn.execute(
                    """INSERT INTO evidence_spans
                    (id,document_id,span_type,text,heading_path_json,order_index,
                     char_start,char_end,locator_json)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        span["span_id"], document["id"], span["span_type"], span["text"],
                        self.db.json(span.get("heading_path", [])), span["order_index"],
                        span["char_start"], span["char_end"], self.db.json(span.get("locator", {})),
                    ),
                )
            for unit in units:
                conn.execute(
                    """INSERT INTO evidence_units
                    (id,document_id,source_span_ids_json,text,heading_path_json,
                     merge_reason_json,token_count)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        unit["unit_id"], document["id"], self.db.json(unit.get("source_span_ids", [])),
                        unit["text"], self.db.json(unit.get("heading_path", [])),
                        self.db.json(unit.get("merge_reason", [])), unit.get("token_count", 0),
                    ),
                )
            for candidate in candidates:
                conn.execute(
                    """INSERT INTO knowledge_candidates
                    (id,document_id,candidate_type,subject_json,predicate_type,object_json,
                     metric_json,statement_json,evidence_text,evidence_refs_json,confidence,
                     extraction_method_json,status,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        candidate["id"], document["id"], candidate["candidate_type"],
                        self.db.json(candidate.get("subject", {})), candidate.get("predicate_type"),
                        self.db.json(candidate.get("object", {})), self.db.json(candidate.get("metric", {})),
                        self.db.json(candidate.get("statement", {})), candidate["evidence_text"],
                        self.db.json(candidate.get("evidence_refs", [])),
                        candidate.get("confidence", 0.5), self.db.json(candidate.get("extraction_method", [])),
                        candidate.get("status", "pending"), now,
                    ),
                )

            entity_ids: set[str] = set()
            for entity in entities:
                entity_ids.add(entity["id"])
                incoming_properties = entity.get("properties", {})
                existing = conn.execute(
                    "SELECT properties_json FROM entities WHERE id=?",
                    (entity["id"],),
                ).fetchone()
                properties = _merge_entity_properties(
                    json_loads(existing["properties_json"], {}) if existing else {},
                    incoming_properties,
                )
                conn.execute(
                    """INSERT INTO entities
                    (id,type,name,normalized_name,layer,brand_id,tenant_id,properties_json,status,
                     created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name, properties_json=excluded.properties_json,
                      updated_at=excluded.updated_at""",
                    (
                        entity["id"], entity["type"], entity["name"],
                        normalized_name(entity["name"]), entity["layer"], entity.get("brand_id"),
                        entity.get("tenant_id"), self.db.json(properties),
                        entity.get("status", "active"), entity.get("created_at", now), now,
                    ),
                )

            for relation in relations:
                conn.execute(
                    """INSERT INTO relations
                    (id,source_id,target_id,relation_type,document_id,properties_json,
                     confidence,created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                      properties_json=excluded.properties_json,
                      confidence=excluded.confidence""",
                    (
                        relation["id"], relation["source_id"], relation["target_id"],
                        relation["relation_type"], document["id"],
                        self.db.json(relation.get("properties", {})), relation.get("confidence", 0.6), now,
                    ),
                )
            for statement in statements:
                conn.execute(
                    """INSERT INTO statements
                    (id,subject_id,document_id,statement_text,statement_class,
                     properties_json,created_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        statement["id"], statement.get("subject_id"), document["id"],
                        statement["statement_text"], statement.get("statement_class", "observation"),
                        self.db.json(statement.get("properties", {})), now,
                    ),
                )

            # Outbox is retained even though the first desktop projection is
            # read directly from SQLite. It gives a clean seam for sync/export.
            # Keep an unprocessed aggregate event idempotent across reprocesses.
            for entity_id in entity_ids:
                conn.execute(
                    """INSERT INTO graph_outbox
                    (aggregate_type,aggregate_id,event_type,payload_json,created_at)
                    SELECT ?,?,?,?,?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM graph_outbox
                        WHERE aggregate_type=? AND aggregate_id=?
                          AND event_type=? AND processed_at IS NULL
                    )""",
                    (
                        "entity", entity_id, "upsert", "{}", now,
                        "entity", entity_id, "upsert",
                    ),
                )

    def graph(self, layer: str | None = None, brand_id: str | None = None, limit: int = 500) -> dict[str, Any]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if layer:
            clauses.append("layer=?")
            params.append(layer)
        if brand_id:
            clauses.append("(brand_id=? OR brand_id IS NULL)")
            params.append(brand_id)
        entity_rows = self.db.query(
            "SELECT id,type,name,layer,brand_id,properties_json FROM entities WHERE "
            + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [limit]),
        )
        ids = [row["id"] for row in entity_rows]
        if not ids:
            return {"nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}
        placeholders = ",".join("?" for _ in ids)
        relation_rows = self.db.query(
            f"SELECT id,source_id,target_id,relation_type,confidence,properties_json "
            f"FROM relations WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT ?",
            tuple(ids + ids + [limit * 2]),
        )
        nodes = [
            {
                "id": row["id"], "type": row["type"], "name": row["name"],
                "layer": row["layer"], "brand_id": row["brand_id"],
                "properties": json_loads(row["properties_json"], {}),
            }
            for row in entity_rows
        ]
        edges = [
            {
                "id": row["id"], "source": row["source_id"], "target": row["target_id"],
                "type": row["relation_type"], "confidence": row["confidence"],
                "properties": json_loads(row["properties_json"], {}),
            }
            for row in relation_rows
        ]
        return {"nodes": nodes, "edges": edges, "stats": {"nodes": len(nodes), "edges": len(edges)}}

    def stats(self) -> dict[str, Any]:
        def count(table: str) -> int:
            return self.db.query(f"SELECT COUNT(*) AS count FROM {table}")[0]["count"]

        by_layer = self.db.query("SELECT layer, COUNT(*) AS count FROM entities GROUP BY layer ORDER BY layer")
        jobs = self.db.query(
            "SELECT status, COUNT(*) AS count FROM pipeline_jobs GROUP BY status ORDER BY status"
        )
        return {
            "documents": count("documents"),
            "evidence_units": count("evidence_units"),
            "candidates": count("knowledge_candidates"),
            "entities": count("entities"),
            "relations": count("relations"),
            "layers": {row["layer"]: row["count"] for row in by_layer},
            "jobs": {row["status"]: row["count"] for row in jobs},
        }

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        entities = self.db.query(
            "SELECT id,type,name,layer,brand_id,properties_json FROM entities "
            "WHERE name LIKE ? OR type LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (pattern, pattern, limit),
        )
        statements = self.db.query(
            "SELECT s.id,s.statement_text,s.statement_class,e.name AS subject_name "
            "FROM statements s LEFT JOIN entities e ON e.id=s.subject_id "
            "WHERE s.statement_text LIKE ? ORDER BY s.created_at DESC LIMIT ?",
            (pattern, limit),
        )
        return [
            {"kind": "entity", "id": row["id"], "title": row["name"], "type": row["type"],
             "layer": row["layer"], "snippet": f"{row['type']} · {row['name']}"}
            for row in entities
        ] + [
            {"kind": "statement", "id": row["id"], "title": row["subject_name"] or "陈述",
             "type": row["statement_class"], "snippet": row["statement_text"]}
            for row in statements
        ]

    def save_embedding(
        self, *, source_id: str, source_type: str, model: str,
        vector: list[float], embedded_text: str,
    ) -> None:
        self.db.execute(
            """INSERT INTO embeddings
            (id,source_id,source_type,model,vector_json,embedded_text,created_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(source_id,source_type,model) DO UPDATE SET
              vector_json=excluded.vector_json, embedded_text=excluded.embedded_text""",
            (
                stable_id("vec", source_type, source_id, model), source_id, source_type,
                model, self.db.json(vector), embedded_text, utc_now(),
            ),
        )


class JobRepository:
    def __init__(self, db: LocalDatabase):
        self.db = db

    def create(self, job_type: str, document_id: str | None = None,
               payload: dict[str, Any] | None = None) -> str:
        job_id = str(uuid.uuid4())
        now = utc_now()
        self.db.execute(
            "INSERT INTO pipeline_jobs(id,document_id,job_type,current_stage,status,progress,payload_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, document_id, job_type, "queued", "queued", 0, self.db.json(payload or {}), now, now),
        )
        return job_id

    def update(self, job_id: str, *, stage: str, status: str, progress: int,
               result: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE pipeline_jobs SET current_stage=?,status=?,progress=?,result_json=?,error=?,updated_at=? WHERE id=?",
            (stage, status, max(0, min(100, progress)), self.db.json(result or {}), error, utc_now(), job_id),
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM pipeline_jobs WHERE id=?", (job_id,))
        if not rows:
            return None
        row = rows[0]
        row["result"] = json_loads(row.pop("result_json"), {})
        row["payload"] = json_loads(row.pop("payload_json"), {})
        return row

    def recoverable(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id,job_type,document_id,payload_json FROM pipeline_jobs "
            "WHERE status IN ('queued','running') ORDER BY created_at"
        )
        for row in rows:
            row["payload"] = json_loads(row.pop("payload_json"), {})
        return rows
