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

    def list_documents(self) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT id,title,source_type,layer,brand_id,content_hash,status,created_at,updated_at "
            "FROM documents ORDER BY updated_at DESC LIMIT 100"
        )

    def document_extraction_counts(self, document_id: str) -> dict[str, int]:
        """Return fixed document-owned extraction counts."""
        rows = self.db.query(
            "SELECT "
            "(SELECT COUNT(*) FROM evidence_spans WHERE document_id=?) AS spans, "
            "(SELECT COUNT(*) FROM evidence_units WHERE document_id=?) AS units, "
            "(SELECT COUNT(*) FROM knowledge_candidates WHERE document_id=?) AS candidates, "
            "(SELECT COUNT(*) FROM relations WHERE document_id=?) AS relations, "
            "(SELECT COUNT(*) FROM statements WHERE document_id=?) AS statements",
            (document_id, document_id, document_id, document_id, document_id),
        )
        row = rows[0] if rows else {}
        return {
            field: int(row.get(field, 0) or 0)
            for field in ("spans", "units", "candidates", "relations", "statements")
        }

    def evidence_citations(
        self,
        evidence_refs: Iterable[dict[str, Any]] | None,
        *,
        document_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Resolve stored evidence references to source units and spans."""
        refs = [ref for ref in (evidence_refs or []) if isinstance(ref, dict)]
        if not refs:
            return []
        limit = max(1, limit)
        unit_ids = {
            str(ref.get("evidence_unit_id"))
            for ref in refs
            if ref.get("evidence_unit_id")
        }
        span_ids = {
            str(ref.get("evidence_span_id") or ref.get("span_id"))
            for ref in refs
            if ref.get("evidence_span_id") or ref.get("span_id")
        }
        quote_by_unit = {
            str(ref["evidence_unit_id"]): str(ref.get("quote") or "")
            for ref in refs
            if ref.get("evidence_unit_id")
        }
        quote_by_span = {
            str(ref.get("evidence_span_id") or ref.get("span_id")): str(ref.get("quote") or "")
            for ref in refs
            if ref.get("evidence_span_id") or ref.get("span_id")
        }

        def rows_for_ids(table: str, ids: set[str]) -> list[dict[str, Any]]:
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            clauses = [f"id IN ({placeholders})"]
            params: list[Any] = sorted(ids)
            if document_id:
                clauses.append("document_id=?")
                params.append(document_id)
            return self.db.query(
                f"SELECT * FROM {table} WHERE " + " AND ".join(clauses),
                tuple(params),
            )

        units = rows_for_ids("evidence_units", unit_ids)
        unit_source_span_ids: set[str] = set()
        for unit in units:
            source_span_ids = json_loads(unit.get("source_span_ids_json"), []) or []
            unit_source_span_ids.update(str(span_id) for span_id in source_span_ids if span_id)
        span_ids.update(unit_source_span_ids)
        spans = rows_for_ids("evidence_spans", span_ids)
        spans_by_id = {str(row["id"]): row for row in spans}
        citations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for unit in units:
            source_span_ids = json_loads(unit.get("source_span_ids_json"), []) or []
            source_spans = [
                spans_by_id[str(span_id)]
                for span_id in source_span_ids
                if str(span_id) in spans_by_id
            ]
            key = (str(unit.get("document_id")), str(unit["id"]))
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "id": f"{unit['document_id']}:{unit['id']}",
                "document_id": unit["document_id"],
                "document_title": self._document_title(unit["document_id"]),
                "evidence_unit_id": unit["id"],
                "evidence_span_ids": [str(span["id"]) for span in source_spans] or source_span_ids,
                "quote": quote_by_unit.get(str(unit["id"])) or unit.get("text", ""),
                "span_texts": [span["text"] for span in source_spans],
                "char_start": min((span["char_start"] for span in source_spans), default=None),
                "char_end": max((span["char_end"] for span in source_spans), default=None),
                "heading_path": json_loads(unit.get("heading_path_json"), []),
            })

        for span in spans:
            if str(span["id"]) in unit_source_span_ids:
                continue
            key = (str(span.get("document_id")), str(span["id"]))
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "id": f"{span['document_id']}:{span['id']}",
                "document_id": span["document_id"],
                "document_title": self._document_title(span["document_id"]),
                "evidence_span_ids": [span["id"]],
                "quote": quote_by_span.get(str(span["id"])) or span.get("text", ""),
                "span_texts": [span.get("text", "")],
                "char_start": span.get("char_start"),
                "char_end": span.get("char_end"),
                "heading_path": json_loads(span.get("heading_path_json"), []),
            })

        return citations[:limit]

    def _document_title(self, document_id: str) -> str | None:
        rows = self.db.query("SELECT title FROM documents WHERE id=?", (document_id,))
        return rows[0]["title"] if rows else None

    def _citations_for_properties(
        self,
        properties: dict[str, Any] | None,
        *,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        properties = properties if isinstance(properties, dict) else {}
        refs = list(properties.get("evidence_refs") or [])
        source_span_id = properties.get("source_span_id")
        if source_span_id:
            refs.append({"evidence_span_id": source_span_id})
        return self.evidence_citations(refs, document_id=document_id)

    def _attach_search_citations(
        self,
        items: list[dict[str, Any]],
        entity_rows: list[dict[str, Any]],
        statement_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for index, row in enumerate(entity_rows):
            items[index]["citations"] = self._citations_for_properties(
                json_loads(row.get("properties_json"), {})
            )
        offset = len(entity_rows)
        for index, row in enumerate(statement_rows):
            items[offset + index]["citations"] = self._citations_for_properties(
                json_loads(row.get("properties_json"), {}),
                document_id=row.get("document_id"),
            )
        return items

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
            f"SELECT id,source_id,target_id,relation_type,confidence,document_id,properties_json "
            f"FROM relations WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders}) "
            "ORDER BY created_at DESC LIMIT ?",
            tuple(ids + ids + [limit * 2]),
        )
        nodes = [
            {
                "id": row["id"], "type": row["type"], "name": row["name"],
                "layer": row["layer"], "brand_id": row["brand_id"],
                "properties": json_loads(row["properties_json"], {}),
                "citations": self._citations_for_properties(
                    json_loads(row["properties_json"], {})
                ),
            }
            for row in entity_rows
        ]
        edges = [
            {
                "id": row["id"], "source": row["source_id"], "target": row["target_id"],
                "type": row["relation_type"], "confidence": row["confidence"],
                "properties": json_loads(row["properties_json"], {}),
                "citations": self._citations_for_properties(
                    json_loads(row["properties_json"], {}),
                    document_id=row["document_id"],
                ),
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

    def search(
        self,
        query: str,
        limit: int = 20,
        *,
        overview: bool = False,
        entity_types: Iterable[str] | None = None,
        brand_id: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if overview:
            return self._workspace_overview(
                query, limit, entity_types=entity_types
            )
        if entity_types is not None or brand_id is not None or document_id is not None:
            return self.search_scoped(
                query,
                limit,
                entity_types=entity_types,
                brand_id=brand_id,
                document_id=document_id,
            )
        query = query.strip()
        if not query:
            return []
        pattern = f"%{query}%"
        entities = self.db.query(
            "SELECT id,type,name,layer,brand_id,properties_json FROM entities "
            "WHERE name LIKE ? OR type LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (pattern, pattern, limit),
        )
        statements = self.db.query(
            "SELECT s.id,s.document_id,s.properties_json,s.statement_text,s.statement_class,e.name AS subject_name "
            "FROM statements s LEFT JOIN entities e ON e.id=s.subject_id "
            "WHERE s.statement_text LIKE ? ORDER BY s.created_at DESC LIMIT ?",
            (pattern, limit),
        )
        items = [
            {"kind": "entity", "id": row["id"], "title": row["name"], "type": row["type"],
             "layer": row["layer"], "snippet": f"{row['type']} · {row['name']}"}
            for row in entities
        ] + [
            {"kind": "statement", "id": row["id"], "title": row["subject_name"] or "陈述",
             "type": row["statement_class"], "snippet": row["statement_text"]}
            for row in statements
        ]
        return self._attach_search_citations(items, entities, statements)

    def document_id_for_reference(self, reference: str) -> str | None:
        """Resolve a user-facing document ID or title at the persistence boundary."""
        reference = reference.strip()
        if not reference:
            return None
        rows = self.db.query(
            "SELECT id FROM documents WHERE id=? OR title=? LIMIT 1",
            (reference, reference),
        )
        return rows[0]["id"] if rows else None

    def search_scoped(
        self,
        query: str,
        limit: int = 20,
        *,
        entity_types: Iterable[str] | None = None,
        brand_id: str | None = None,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a bounded search with already-resolved application filters."""
        query = query.strip()
        limit = max(1, limit)
        entity_clauses = ["e.status = 'active'"]
        entity_params: list[Any] = []
        if query:
            pattern = f"%{query}%"
            entity_clauses.append("(e.name LIKE ? OR e.type LIKE ?)")
            entity_params.extend((pattern, pattern))
        types = sorted({str(value) for value in (entity_types or ()) if value})
        if types:
            placeholders = ",".join("?" for _ in types)
            entity_clauses.append(f"e.type IN ({placeholders})")
            entity_params.extend(types)
        if brand_id is not None:
            entity_clauses.append("(e.brand_id = ? OR (e.type = 'brand' AND e.name = ?))")
            entity_params.extend((brand_id, brand_id))
        if document_id is not None:
            source_pattern = f'%"source_document_id": "{document_id}"%'
            entity_clauses.append(
                "(e.properties_json LIKE ? "
                "OR EXISTS (SELECT 1 FROM relations r "
                "WHERE r.document_id=? AND (r.source_id=e.id OR r.target_id=e.id)) "
                "OR EXISTS (SELECT 1 FROM statements s "
                "WHERE s.document_id=? AND s.subject_id=e.id))"
            )
            entity_params.extend((source_pattern, document_id, document_id))
        entities = self.db.query(
            "SELECT e.id,e.type,e.name,e.layer,e.brand_id,e.properties_json "
            "FROM entities e WHERE " + " AND ".join(entity_clauses) +
            " ORDER BY e.updated_at DESC LIMIT ?",
            tuple(entity_params + [limit]),
        )

        statement_clauses = ["1=1"]
        statement_params: list[Any] = []
        if query:
            statement_clauses = ["s.statement_text LIKE ?"]
            statement_params.append(f"%{query}%")
        if brand_id is not None:
            statement_clauses.append("(e.name = ? OR e.brand_id = ?)")
            statement_params.extend((brand_id, brand_id))
        if document_id is not None:
            statement_clauses.append("s.document_id = ?")
            statement_params.append(document_id)
        statements = self.db.query(
            "SELECT s.id,s.document_id,s.properties_json,s.statement_text,s.statement_class,e.name AS subject_name "
            "FROM statements s LEFT JOIN entities e ON e.id=s.subject_id WHERE " +
            " AND ".join(statement_clauses) +
            " ORDER BY s.created_at DESC LIMIT ?",
            tuple(statement_params + [limit]),
        )
        return self._attach_search_citations([
            {"kind": "entity", "id": row["id"], "title": row["name"], "type": row["type"],
             "layer": row["layer"], "snippet": f"{row['type']} 路 {row['name']}"}
            for row in entities
        ] + [
            {"kind": "statement", "id": row["id"], "title": row["subject_name"] or "闄堣堪",
             "type": row["statement_class"], "snippet": row["statement_text"]}
            for row in statements
        ], entities, statements)

    def _workspace_overview(
        self,
        query: str,
        limit: int,
        *,
        entity_types: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a small, intent-aware snapshot when exact search is empty.

        This is deliberately a bounded keyword fallback, not a replacement for
        semantic or vector retrieval. It gives broad workspace questions useful
        local context while keeping unrelated questions empty.
        """
        limit = max(1, limit)
        entity_limit = max(1, limit // 2)
        relation_limit = max(1, limit // 4) if entity_types is not None or any(
            marker in query for marker in ("知识库", "数据库", "总结", "概括", "关系", "服务")
        ) else 0
        statement_limit = max(0, limit - entity_limit - relation_limit)
        types = sorted({str(value) for value in (entity_types or ()) if value})
        type_filter = ""
        type_params: tuple[Any, ...] = ()
        if types:
            placeholders = ",".join("?" for _ in types)
            type_filter = f" AND type IN ({placeholders})"
            type_params = tuple(types)
        entities = self.db.query(
            "SELECT id,type,name,layer,brand_id,properties_json FROM entities "
            "WHERE status = 'active'" + type_filter +
            " ORDER BY updated_at DESC LIMIT ?",
            type_params + (entity_limit,),
        )
        items: list[dict[str, Any]] = [
            {"kind": "entity", "id": row["id"], "title": row["name"], "type": row["type"],
             "layer": row["layer"], "snippet": f"{row['type']} · {row['name']}"}
            for row in entities
        ]
        for item, row in zip(items, entities):
            item["citations"] = self._citations_for_properties(
                json_loads(row["properties_json"], {})
            )
        if relation_limit:
            relations = self.db.query(
                "SELECT r.id,r.relation_type,r.confidence,r.created_at,r.document_id,r.properties_json, "
                "s.id AS source_id,s.name AS source_name,s.layer AS source_layer, "
                "t.name AS target_name "
                "FROM relations r "
                "JOIN entities s ON s.id=r.source_id "
                "JOIN entities t ON t.id=r.target_id "
                "ORDER BY r.created_at DESC LIMIT ?",
                (relation_limit,),
            )
            items.extend(
                {
                    "kind": "relation",
                    "id": row["id"],
                    "title": f"{row['source_name']} → {row['target_name']}",
                    "type": row["relation_type"],
                    "layer": row["source_layer"],
                    "snippet": (
                        f"{row['source_name']} -[{row['relation_type']}]-> "
                        f"{row['target_name']}"
                    ),
                    "citations": self._citations_for_properties(
                        json_loads(row["properties_json"], {}),
                        document_id=row["document_id"],
                    ),
                }
                for row in relations
            )
        if statement_limit:
            statements = self.db.query(
                "SELECT s.id,s.document_id,s.properties_json,s.statement_text,s.statement_class,e.name AS subject_name "
                "FROM statements s LEFT JOIN entities e ON e.id=s.subject_id "
                "ORDER BY s.created_at DESC LIMIT ?",
                (statement_limit,),
            )
            items.extend(
                {
                    "kind": "statement",
                    "id": row["id"],
                    "title": row["subject_name"] or "陈述",
                    "type": row["statement_class"],
                    "snippet": row["statement_text"],
                    "citations": self._citations_for_properties(
                        json_loads(row["properties_json"], {}),
                        document_id=row["document_id"],
                    ),
                }
                for row in statements
            )
        return items[:limit]

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


class ChatRepository:
    """Atomic persistence boundary for one user/assistant chat exchange."""

    def __init__(self, db: LocalDatabase):
        self.db = db

    def save_exchange(
        self,
        user_message: dict[str, Any],
        assistant_message: dict[str, Any],
    ) -> None:
        """Save both messages in one transaction or persist neither."""
        with self.db.transaction() as conn:
            for message in (user_message, assistant_message):
                conn.execute(
                    "INSERT INTO chat_messages"
                    "(id,role,content,citations_json,mode,created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        message["id"],
                        message["role"],
                        message["content"],
                        self.db.json(message.get("citations", [])),
                        message.get("mode", "unknown"),
                        message["created_at"],
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
