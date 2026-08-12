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


# Only the L1-constrained entity types the extraction prompt may emit are
# persisted. Anything outside this set is dropped (type_constraint blocking).
VALID_ENTITY_TYPES = {
    "brand", "product", "industry", "category", "audience", "use_case",
    "problem", "topic", "competitor", "capability", "decision_factor",
    "job_to_be_done", "outcome", "organization", "product_version",
}

VALID_RELATION_TYPES = {
    "belongs_to", "operates_in", "serves", "supports_use_case", "solves",
    "has_capability", "competes_with", "alternative_to", "has_topic",
    "covers", "targets", "mentions", "has_problem", "has_decision_factor",
    "capability_supports_use_case", "requires_capability", "produces_outcome",
    "achieves_outcome", "owns_brand", "offers", "version_of", "supersedes",
}


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


def _upsert_entity(db: DB, ent: dict, existing: set[str], dry_run: bool) -> str | None:
    """Upsert one entity; return its entity_id. Returns None if type invalid."""
    etype = ent.get("type") or ent.get("entity_type") or "topic"
    if etype not in VALID_ENTITY_TYPES:
        return None
    canonical = ent.get("canonical_name") or ent.get("name")
    if not canonical:
        return None

    entity_id = normalize_entity_id(etype, canonical, existing)
    row = {
        "entity_id": entity_id,
        "entity_type": etype,
        "canonical_name": canonical,
        "semantic_subtype": ent.get("semantic_subtype"),
        "attributes": ent.get("properties") or ent.get("attributes") or {},
        "confidence": ent.get("confidence"),
        "status": "active",
    }
    if not dry_run:
        db.upsert("entity", row, key_field="entity_id")
        for alias in ent.get("aliases") or []:
            db.execute(
                "INSERT INTO entity_alias (entity_id, alias_name, alias_type) "
                "SELECT id, %s, %s FROM entity WHERE entity_id = %s "
                "ON CONFLICT (entity_id, alias_name) DO NOTHING",
                (alias, "alt_label", entity_id),
            )
        print(f"  entity  {entity_id} ({etype})")
    else:
        print(f"  [dry] entity {entity_id} ({etype}) canonical={canonical}")
    return entity_id


def run(db: DB, args) -> dict[str, Any]:
    """Extract entities/relations/statements from a report (or raw text)."""
    report_id = getattr(args, "report_id", None)
    report_path = getattr(args, "report", None)
    dry_run = getattr(args, "dry_run", False)

    # Decide the text source: raw text arg > report file > report_candidate rows.
    text_source = getattr(args, "text", None)
    if text_source is None and report_path and os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            text_source = f.read()

    chunks: list[str] = []
    if text_source is not None:
        chunks = _chunk_texts(text_source)
    elif report_id:
        rows = db.query(
            "SELECT statement FROM report_candidate rc "
            "JOIN research_report rr ON rr.id = rc.report_id "
            "WHERE rr.report_id = %s AND rc.status != 'rejected'",
            (report_id,),
        )
        chunks = [r["statement"] for r in rows if r["statement"]]
    else:
        raise ValueError(
            "No input: pass --report <file.md>, --report-id, or --text <raw>"
        )

    client = load_llm()
    model = client.config.model
    run_id = getattr(args, "run_id", None) or f"ext_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"

    existing: set[str] = set()
    stats = {"entities": 0, "relations": 0, "statements": 0, "chunks": len(chunks)}

    for chunk in chunks:
        if not chunk.strip():
            continue
        result = extract_entities_relations(client, chunk)

        # --- entities ---
        for ent in result.get("entities", []):
            if _upsert_entity(db, ent, existing, dry_run):
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
                if stmt_class in ("fact", "claim", "observation", "inference")
                else "observation",
                # The statement CHECK requires object_entity_id OR object_value;
                # free-text statements carry their text as a JSON object_value.
                "object_value": {"statement": text},
                "confidence": stmt.get("confidence"),
                "status": "active",
            }
            if not dry_run:
                db.upsert("statement", row, key_field="statement_id")
            stats["statements"] += 1
            print(f"  {'[dry] ' if dry_run else ''}statement {stmt_id} [{row['statement_class']}]")

        # --- relations ---
        for rel in result.get("relations", []):
            rel_type = rel.get("relation")
            if rel_type not in VALID_RELATION_TYPES:
                continue
            subj_id = rel.get("subject")
            obj_id = rel.get("object")
            row = {
                "subject_id": subj_id,   # entity_id string; mapped to UUID below
                "relation_type": rel_type,
                "object_id": obj_id,
                "confidence": rel.get("confidence"),
                "status": "active",
            }
            if not dry_run:
                # Map subject/object entity_id strings to the authoritative UUIDs.
                subj_uuid = _entity_uuid(db, subj_id) if subj_id else None
                obj_uuid = _entity_uuid(db, obj_id) if obj_id else None
                if subj_uuid and obj_uuid:
                    # relation has no natural unique key; insert explicitly.
                    db.execute(
                        "INSERT INTO relation (subject_id, relation_type, object_id, "
                        "confidence, status) VALUES (%s, %s, %s, %s, %s)",
                        (subj_uuid, rel_type, obj_uuid, row["confidence"], "active"),
                    )
            stats["relations"] += 1
            print(f"  {'[dry] ' if dry_run else ''}relation {rel_type} {subj_id} -> {obj_id}")

    # --- extraction_run log ---
    if not dry_run:
        db.upsert(
            "extraction_run",
            {
                "run_id": run_id,
                "extraction_profile": getattr(args, "profile", None) or "l2_llm_extraction",
                "model": model,
                "prompt_version": "l2-extraction-v1.2.0",
                "inputs": {"report_id": report_id, "chunks": len(chunks)},
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 knowledge extraction pipeline")
    parser.add_argument("--report", help="Path to markdown report to extract from")
    parser.add_argument("--report-id", help="research_report.report_id to pull candidates from")
    parser.add_argument("--text", help="Raw text to extract from")
    parser.add_argument("--run-id", help="Optional explicit extraction run id")
    parser.add_argument("--dry-run", action="store_true",
                        help="Call LLM but print instead of writing to DB")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))