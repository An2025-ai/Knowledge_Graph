"""L2 pipeline: Knowledge Extraction (THE core pipeline).

Per industry_knowledge/pipelines/extraction.yaml, this pipeline turns report
candidates (or raw report text) into structured entities / relations /
statements via the shared LLM extraction helper `extract_entities_relations`.

For each chunk of text this executor:
  1. Calls extract_entities_relations(client, text) to get normalized JSON
  2. Upserts entities into `entity` (via normalize_entity_id + entity_id),
     aliases into `entity_alias`, relations into `relation`, statements into
     `statement`
  3. Records an `extraction_run` row carrying the model name + output summary

Supports `--dry-run`: the LLM is still called (extraction is the expensive
step) but nothing is written to the DB and the planned inserts are printed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from runtime.db import DB
from runtime.extract import extract_entities_relations, load_llm, normalize_entity_id
from runtime.l1.registry import get_l1_registry


DEFAULT_PROFILE_ID = "l2_industry"


def _profile_id(args: Any | None = None) -> str:
    return getattr(args, "profile_id", None) or getattr(args, "schema_profile", None) or DEFAULT_PROFILE_ID


def _valid_entity_types(profile_id: str = DEFAULT_PROFILE_ID) -> set[str]:
    return get_l1_registry().entity_types(profile_id, extractable_only=True)


def _valid_relation_types(profile_id: str = DEFAULT_PROFILE_ID) -> set[str]:
    return get_l1_registry().relation_types(profile_id, extractable_only=True)


def _valid_statement_classes(profile_id: str = DEFAULT_PROFILE_ID) -> set[str]:
    """Authoritative statement classes from L1 ontology (profile.statement_classes)."""
    classes = get_l1_registry().statement_classes(profile_id)
    return classes or {"fact", "claim", "observation", "inference"}


# Backward-compatible module constants for callers that import the old names.
VALID_ENTITY_TYPES = _valid_entity_types()
VALID_RELATION_TYPES = _valid_relation_types()


def _chunk_texts(report_text: str, size: int = 2000) -> list[str]:
    """Split report text into LLM-friendly chunks on paragraph boundaries."""
    paragraphs = [p for p in report_text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > size and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para) if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks or [report_text]


def _upsert_entity(
    db: DB,
    ent: dict,
    existing_ids: set[str],
    entity_registry: dict[tuple[str, str], str],
    candidate_uuid: str | None,
    industry_id: str | None,
    dry_run: bool,
    profile_id: str = DEFAULT_PROFILE_ID,
) -> str | None:
    """Upsert one entity; return its entity_id. Returns None if type invalid."""
    etype = ent.get("type") or ent.get("entity_type") or "topic"
    if etype not in _valid_entity_types(profile_id):
        return None
    canonical = ent.get("canonical_name") or ent.get("name")
    if not canonical:
        return None

    key = (etype, canonical.strip().casefold())
    if key in entity_registry:
        entity_id = entity_registry[key]
        if candidate_uuid and not dry_run:
            _add_entity_candidate(db, entity_id, candidate_uuid)
        return entity_id
    entity_id = normalize_entity_id(etype, canonical, existing_ids)
    entity_registry[key] = entity_id
    row = {
        "entity_id": entity_id,
        "entity_type": etype,
        "canonical_name": canonical,
        "semantic_subtype": ent.get("semantic_subtype"),
        "industry_id": industry_id,
        "attributes": {
            **(ent.get("properties") or ent.get("attributes") or {}),
            **({"report_candidate_ids": [candidate_uuid]} if candidate_uuid else {}),
        },
        "confidence": ent.get("confidence"),
        "status": "candidate" if candidate_uuid else "active",
    }
    if not dry_run:
        rows = db.query(
            "SELECT id, status FROM entity WHERE entity_id = %s LIMIT 1",
            (entity_id,),
        )
        if rows:
            if candidate_uuid:
                _add_entity_candidate(db, entity_id, candidate_uuid)
        else:
            db.upsert("entity", row, key_field="entity_id")
        for alias in ent.get("aliases") or []:
            db.execute(
                "INSERT INTO entity_alias (entity_id, alias_name, alias_type) "
                "SELECT id, %s, %s FROM entity WHERE entity_id = %s "
                "ON CONFLICT (entity_id, alias_name) DO NOTHING",
                (alias, "alt_label", entity_id),
            )
        # Persist the entity vector (optional, non-fatal) so entity_embedding can
        # be used for semantic retrieval/dedup downstream.
        try:
            from runtime.embeddings import write_embedding

            uuid_rows = db.query(
                "SELECT id, tenant_id FROM entity WHERE entity_id = %s LIMIT 1",
                (entity_id,),
            )
            if uuid_rows:
                write_embedding(
                    db, "entity_embedding", uuid_rows[0]["id"], canonical,
                    uuid_rows[0].get("tenant_id"),
                )
        except Exception:  # noqa: BLE001 - optional vector layer
            pass
        print(f"  entity  {entity_id} ({etype})")
    else:
        print(f"  [dry] entity {entity_id} ({etype}) canonical={canonical}")
    return entity_id


def run(db: DB, args) -> dict[str, Any]:
    """Extract entities/relations/statements from a report (or raw text)."""
    report_id = getattr(args, "report_id", None)
    report_path = getattr(args, "report", None)
    dry_run = getattr(args, "dry_run", False)
    profile_id = _profile_id(args)
    # Fail fast on a typo'd/unknown profile instead of silently degrading the
    # strict profile whitelist into the global (all-types-open) set.
    get_l1_registry().require_profile(profile_id)

    # Prefer report candidates when a report_id exists so every extracted item
    # can retain the candidate lineage needed by promotion.
    text_source = getattr(args, "text", None)
    chunk_items: list[tuple[str, str | None]] = []
    if text_source is not None:
        chunk_items = [(chunk, None) for chunk in _chunk_texts(text_source)]
    elif report_id:
        rows = db.query(
            "SELECT rc.id, rc.statement FROM report_candidate rc "
            "JOIN research_report rr ON rr.id = rc.report_id "
            "WHERE rr.report_id = %s AND rc.status != 'rejected'",
            (report_id,),
        )
        chunk_items = [
            (r["statement"], str(r["id"])) for r in rows if r["statement"]
        ]
    elif report_path and os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            text_source = f.read()
        chunk_items = [(chunk, None) for chunk in _chunk_texts(text_source)]
    else:
        raise ValueError(
            "No input: pass --report <file.md>, --report-id, or --text <raw>"
        )

    client = load_llm()
    model = client.config.model
    run_id = getattr(args, "run_id", None) or f"ext_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"

    existing_ids: set[str] = set()
    entity_registry: dict[tuple[str, str], str] = {}
    external_entity_ids: dict[str, str] = {}
    counted_entities: set[str] = set()
    stats = {"entities": 0, "relations": 0, "statements": 0, "chunks": len(chunk_items)}

    for chunk, candidate_uuid in chunk_items:
        if not chunk.strip():
            continue
        result = extract_entities_relations(client, chunk, profile_id=profile_id)
        industry_id = _candidate_industry(db, candidate_uuid) if candidate_uuid else None

        # --- entities ---
        entity_map = external_entity_ids
        for ent in result.get("entities", []):
            entity_id = _upsert_entity(
                db, ent, existing_ids, entity_registry, candidate_uuid, industry_id, dry_run,
                profile_id=profile_id,
            )
            if entity_id:
                external_id = ent.get("id") or entity_id
                entity_map[external_id] = entity_id
                entity_map[entity_id] = entity_id
                # Link the entity back to this report candidate so promotion's
                # gate_2_entity_type (entity.attributes->'report_candidate_ids')
                # can find it and the candidate passes the type gate.
                if candidate_uuid and not dry_run:
                    _add_entity_candidate(db, external_id, str(candidate_uuid))
                if entity_id not in counted_entities:
                    counted_entities.add(entity_id)
                    stats["entities"] += 1

        # --- statements ---
        for stmt in result.get("statements", []):
            text = stmt.get("text") or stmt.get("statement_text")
            stmt_class = stmt.get("statement_class") or stmt.get("statement_type")
            if not text:
                continue
            stmt_id = stmt.get("statement_id") or (
                f"st_{run_id}_{stats['statements'] + 1}"
            )
            row = {
                "statement_id": stmt_id,
                "statement_text": text,
                "statement_class": stmt_class
                if stmt_class in _valid_statement_classes(profile_id)
                else "observation",
                # The statement CHECK requires object_entity_id OR object_value;
                # free-text statements carry their text as a JSON object_value.
                "object_value": {"statement": text},
                "confidence": stmt.get("confidence"),
                "scope": {
                    "report_id": report_id,
                    "report_candidate_id": candidate_uuid,
                    "industry_id": industry_id,
                },
                "status": "candidate" if candidate_uuid else "active",
            }
            if not dry_run:
                if candidate_uuid:
                    statement_uuid = db.insert_returning_id(
                        "INSERT INTO statement (statement_id, statement_text, statement_class, "
                        "object_value, confidence, scope, status) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT ((scope->>'report_candidate_id'), statement_text) "
                        "WHERE scope->>'report_candidate_id' IS NOT NULL DO UPDATE SET "
                        "statement_class=EXCLUDED.statement_class, object_value=EXCLUDED.object_value, "
                        "confidence=EXCLUDED.confidence RETURNING id",
                        (stmt_id, row["statement_text"], row["statement_class"],
                         db._json(row["object_value"]), row["confidence"],
                         db._json(row["scope"]), row["status"]),
                    )
                    _link_statement_evidence_uuid(db, statement_uuid, candidate_uuid)
                else:
                    db.upsert("statement", row, key_field="statement_id")
            stats["statements"] += 1
            print(f"  {'[dry] ' if dry_run else ''}statement {stmt_id} [{row['statement_class']}]")

        # --- relations ---
        for rel in result.get("relations", []):
            rel_type = rel.get("relation")
            if rel_type not in _valid_relation_types(profile_id):
                continue
            subj_id = entity_map.get(rel.get("subject"))
            obj_id = entity_map.get(rel.get("object"))
            if not subj_id or not obj_id:
                continue
            row = {
                "subject_id": subj_id,   # entity_id string; mapped to UUID below
                "relation_type": rel_type,
                "object_id": obj_id,
                "confidence": rel.get("confidence"),
                "status": "candidate" if candidate_uuid else "active",
            }
            if not dry_run:
                # Map subject/object entity_id strings to the authoritative UUIDs.
                subj_uuid = _entity_uuid(db, subj_id) if subj_id else None
                obj_uuid = _entity_uuid(db, obj_id) if obj_id else None
                if subj_uuid and obj_uuid:
                    # relation has no natural unique key; insert explicitly.
                    relation_uuid = db.insert_returning_id(
                        "INSERT INTO relation (subject_id, relation_type, object_id, "
                        "confidence, status, scope) VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (subject_id, relation_type, object_id, "
                        "(scope->>'report_candidate_id')) "
                        "WHERE scope->>'report_candidate_id' IS NOT NULL DO UPDATE SET "
                        "confidence=EXCLUDED.confidence RETURNING id",
                        (subj_uuid, rel_type, obj_uuid, row["confidence"], row["status"],
                         db._json({"report_id": report_id,
                                   "report_candidate_id": candidate_uuid,
                                   "industry_id": industry_id})),
                    )
                    _link_relation_evidence(db, relation_uuid, candidate_uuid)
                else:
                    continue
            stats["relations"] += 1
            print(f"  {'[dry] ' if dry_run else ''}relation {rel_type} {subj_id} -> {obj_id}")

        if candidate_uuid and not dry_run:
            confidence_values = [
                item.get("confidence")
                for group in (result.get("entities", []), result.get("relations", []),
                              result.get("statements", []))
                for item in group
                if item.get("confidence") is not None
            ]
            statement_classes = [
                item.get("statement_class") or item.get("statement_type")
                for item in result.get("statements", [])
            ]
            statement_class = next(
                (value for value in statement_classes
                 if value in _valid_statement_classes(profile_id)),
                "observation",
            )
            confidence = (
                sum(confidence_values) / len(confidence_values)
                if confidence_values else None
            )
            db.execute(
                "UPDATE report_candidate SET candidate_type = %s, confidence = %s "
                "WHERE id = %s",
                (statement_class, confidence, candidate_uuid),
            )

    # --- extraction_run log ---
    if not dry_run:
        db.upsert(
            "extraction_run",
            {
                "run_id": run_id,
                "extraction_profile": getattr(args, "profile", None) or "l2_llm_extraction",
                "model": model,
                "prompt_version": "l2-extraction-v1.2.0",
                "inputs": {"report_id": report_id, "chunks": len(chunk_items), "profile_id": profile_id},
                "outputs_summary": stats,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc),
            },
            key_field="run_id",
        )
    print(f"[extraction] run {run_id} model={model}: {json.dumps(stats, ensure_ascii=False)}")

    return {
        "pipeline": "extraction",
        "run_id": run_id,
        "model": model,
        "report_id": report_id,
        "chunk_count": stats["chunks"],
        "entity_count": stats["entities"],
        "relation_count": stats["relations"],
        "statement_count": stats["statements"],
        "dry_run": dry_run,
    }


def _entity_uuid(db: DB, entity_id: str) -> Any | None:
    rows = db.query("SELECT id FROM entity WHERE entity_id = %s LIMIT 1", (entity_id,))
    return rows[0]["id"] if rows else None


def _candidate_industry(db: DB, candidate_uuid: str) -> str | None:
    rows = db.query(
        "SELECT ir.industry_id FROM report_candidate rc "
        "JOIN research_report rr ON rr.id = rc.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id = rr.requirement_id "
        "WHERE rc.id = %s LIMIT 1",
        (candidate_uuid,),
    )
    return rows[0].get("industry_id") if rows else None


def _add_entity_candidate(db: DB, entity_id: str, candidate_uuid: str) -> None:
    db.execute(
        "UPDATE entity SET attributes = jsonb_set("
        "COALESCE(attributes, '{}'::jsonb), '{report_candidate_ids}', "
        "COALESCE(attributes->'report_candidate_ids', '[]'::jsonb) || to_jsonb(%s::text), true) "
        "WHERE entity_id = %s AND NOT COALESCE(attributes->'report_candidate_ids', '[]'::jsonb) "
        "@> to_jsonb(%s::text)",
        (candidate_uuid, entity_id, candidate_uuid),
    )


def _candidate_evidence(db: DB, candidate_uuid: str | None) -> list[dict]:
    if not candidate_uuid:
        return []
    return db.query(
        "SELECT evidence_id, support_status, support_reason, verifier_version "
        "FROM citation_resolution WHERE report_candidate_id = %s "
        "AND evidence_id IS NOT NULL",
        (candidate_uuid,),
    )


def _link_statement_evidence(db: DB, statement_id: str, candidate_uuid: str | None) -> None:
    rows = db.query("SELECT id FROM statement WHERE statement_id = %s", (statement_id,))
    if not rows:
        return
    for evidence in _candidate_evidence(db, candidate_uuid):
        db.execute(
            "INSERT INTO statement_evidence "
            "(statement_id, evidence_id, support_status, support_reason, verifier_version) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (statement_id, evidence_id) DO UPDATE SET "
            "support_status=EXCLUDED.support_status, support_reason=EXCLUDED.support_reason, "
            "verifier_version=EXCLUDED.verifier_version",
            (rows[0]["id"], evidence["evidence_id"], evidence.get("support_status"),
             evidence.get("support_reason"), evidence.get("verifier_version")),
        )


def _link_statement_evidence_uuid(
    db: DB, statement_uuid: str | None, candidate_uuid: str | None
) -> None:
    if not statement_uuid:
        return
    for evidence in _candidate_evidence(db, candidate_uuid):
        db.execute(
            "INSERT INTO statement_evidence "
            "(statement_id, evidence_id, support_status, support_reason, verifier_version) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (statement_id, evidence_id) DO UPDATE SET "
            "support_status=EXCLUDED.support_status, support_reason=EXCLUDED.support_reason, "
            "verifier_version=EXCLUDED.verifier_version",
            (statement_uuid, evidence["evidence_id"], evidence.get("support_status"),
             evidence.get("support_reason"), evidence.get("verifier_version")),
        )


def _link_relation_evidence(db: DB, relation_uuid: str | None, candidate_uuid: str | None) -> None:
    if not relation_uuid:
        return
    for evidence in _candidate_evidence(db, candidate_uuid):
        db.execute(
            "INSERT INTO relation_evidence "
            "(relation_id, evidence_id, support_status, support_reason, verifier_version) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (relation_id, evidence_id) DO UPDATE SET "
            "support_status=EXCLUDED.support_status, support_reason=EXCLUDED.support_reason, "
            "verifier_version=EXCLUDED.verifier_version",
            (relation_uuid, evidence["evidence_id"], evidence.get("support_status"),
             evidence.get("support_reason"), evidence.get("verifier_version")),
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 knowledge extraction pipeline")
    parser.add_argument("--report", help="Path to markdown report to extract from")
    parser.add_argument("--report-id", help="research_report.report_id to pull candidates from")
    parser.add_argument("--text", help="Raw text to extract from")
    parser.add_argument("--run-id", help="Optional explicit extraction run id")
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID,
                        help="L1 schema profile controlling extraction")
    parser.add_argument("--dry-run", action="store_true",
                        help="Call LLM but print instead of writing to DB")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
