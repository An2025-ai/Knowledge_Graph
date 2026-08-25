"""L3 pipeline: Candidate Extraction (core).

Per brand_knowledge/pipelines/candidate_extraction.yaml, this is the core step
that turns chunked brand docs into structured candidates. For each Evidence Span
chunk it calls ``extract_entities_relations(client, text)`` to obtain
``entities`` / ``relations`` / ``statements`` and routes them:

  - entities   -> ``entity`` table (resolved via :func:`upsert_entity`, so exact
    canonical-name matches in the tenant are reused),
  - relations  -> ``relation`` table,
  - statements -> ``assertion`` table (per L3, NOT the L2 ``statement`` table).

Every created assertion records an evidence reference (the source
``document_chunk`` UUID and quote) in its ``scope`` so ``evidence_verification``
can link it back.

``--dry-run`` still runs the LLM but prints instead of writing.
"""
from __future__ import annotations

import json
from typing import Any

from runtime.db import DB
from runtime.extract import load_llm, extract_entities_relations, normalize_entity_id
from runtime.brand.pipelines._helpers import resolve_brand_context, upsert_entity, now_iso

# Defaults refined by later pipelines (assertion_classification, review_promotion).
DEFAULT_ASSERTION_KIND = "internal_fact"
STATUS_CANDIDATE = "candidate"
RELATION_DEFAULT_CLASS = "fact"
MENTION_PREDICATE = "mentions"


def _insert_assertion(
    db: DB,
    ctx: dict,
    *,
    subject_id: str,
    predicate: str,
    statement_text: str,
    statement_class: str,
    object_entity_id: str | None = None,
    object_value: Any = None,
    confidence: float | None = None,
    evidence_span_id: str | None = None,
    evidence_quote: str = "",
) -> str:
    """Insert one assertion row and return its UUID."""
    scope = {
        "evidence_span_id": evidence_span_id,
        "evidence_quote": evidence_quote,
        "extracted_at": now_iso(),
        "product_version": "1.0.0",
    }
    aid = db.insert_returning_id(
        "INSERT INTO assertion "
        "(id, tenant_id, brand_id, subject_id, predicate, object_entity_id, "
        " object_value, statement_text, statement_class, assertion_kind, "
        " verification_status, publication_status, access_level, confidence, "
        " scope, limitations, status) "
        "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, "
        " 'pending_verification', 'draft', %s, %s, %s::jsonb, %s::jsonb, %s) "
        "RETURNING id",
        (
            ctx["tenant_id"], ctx["brand_id"], subject_id, predicate,
            object_entity_id, json.dumps(object_value, ensure_ascii=False)
            if object_value is not None else None,
            statement_text, statement_class, DEFAULT_ASSERTION_KIND,
            ctx.get("access_level", "internal"), confidence,
            json.dumps(scope, ensure_ascii=False), json.dumps([], ensure_ascii=False),
            STATUS_CANDIDATE,
        ),
    )
    return aid


def _load_client() -> Any:
    try:
        return load_llm()
    except Exception as exc:  # pragma: no cover - LLM unavailable
        print(f"[candidate_extraction] LLM unavailable: {exc}")
        return None


def _write_assertion_embedding(db: DB, assertion_id: str | None, text: str, tenant_id) -> None:
    """Persist an assertion's vector (optional, non-fatal) for semantic retrieval."""
    if not assertion_id or not text:
        return
    try:
        from runtime.embeddings import write_embedding

        write_embedding(db, "assertion_embedding", assertion_id, text, tenant_id)
    except Exception:  # noqa: BLE001 - optional vector layer
        pass


def run(db: DB, args) -> dict[str, Any]:
    """Extract entities/relations/assertions from evidence spans."""
    ctx = resolve_brand_context(db, args)
    ctx["access_level"] = getattr(args, "access_level", None) or "internal"
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]
    document_id = getattr(args, "document_id", None)
    if not document_id:
        raise ValueError("candidate_extraction requires --document-id")

    doc_rows = db.query("SELECT id FROM document WHERE document_id = %s LIMIT 1", (document_id,))
    if not doc_rows:
        raise ValueError(f"document not found: {document_id}. Run source_registration first.")
    doc_uuid = doc_rows[0]["id"]

    spans = db.query(
        "SELECT id, chunk_index, heading_path, text FROM document_chunk "
        "WHERE document_id = %s AND chunk_type = 'evidence_span' ORDER BY chunk_index",
        (doc_uuid,),
    )
    if not spans:
        raise ValueError(f"no evidence_span chunks for {document_id}. Run semantic_chunking first.")

    client = _load_client()
    dry_run = bool(getattr(args, "dry_run", False))
    stats = {"entities": 0, "relations": 0, "assertions": 0, "spans": len(spans)}

    if client is None:
        print("[candidate_extraction] ERROR: LLM not configured; cannot extract candidates.")
        return {**ctx, "pipeline": "candidate_extraction", "document_id": document_id,
                "error": "LLM not available", "stats": stats}

    for span in spans:
        try:
            result = extract_entities_relations(client, span["text"], profile_id="l3_brand")
        except Exception as exc:  # pragma: no cover
            print(f"[candidate_extraction] LLM failed on chunk {span['chunk_index']}: {exc}")
            continue

        entities = result.get("entities", [])
        relations = result.get("relations", [])
        statements = result.get("statements", [])

        # --- normalize entity ids in-process: ext_id -> (uuid, entity_id) ---
        ent_map: dict[str, tuple[str, str]] = {}
        used_ids: set[str] = set()
        for e in entities:
            etype = e.get("type", "topic")
            ename = e.get("canonical_name") or e.get("text") or e.get("id", "unnamed")
            ext_id = e.get("id") or f"ent_{etype}_{ename}"
            if ext_id in ent_map:
                continue
            if dry_run:
                ent_map[ext_id] = (None, normalize_entity_id(etype, ename, used_ids))
                stats["entities"] += 1
                continue
            ent_map[ext_id] = upsert_entity(db, tenant_id, brand_id, etype, ename,
                                            e.get("aliases") or [])
            stats["entities"] += 1

        name_of = {}
        for e in entities:
            ext = e.get("id") or f"ent_{e.get('type', 'topic')}_{e.get('canonical_name', 'unnamed')}"
            name_of[ext] = e.get("canonical_name") or e.get("text", ext)

        # --- relations -> relation rows + assertion rows ---
        for r in relations:
            sub_ext = r.get("subject")
            obj_ext = r.get("object")
            rtype = r.get("relation")
            if sub_ext not in ent_map or obj_ext not in ent_map or not rtype:
                continue
            sub_uuid, _ = ent_map[sub_ext]
            obj_uuid, _ = ent_map[obj_ext]
            stmt_text = f"{name_of.get(sub_ext, sub_ext)} {rtype} {name_of.get(obj_ext, obj_ext)}"
            if dry_run:
                stats["relations"] += 1
                stats["assertions"] += 1
                print(f"[candidate_extraction][dry] rel+assertion: {stmt_text}")
                continue
            db.execute(
                "INSERT INTO relation "
                "(id, subject_id, relation_type, object_id, tenant_id, confidence, "
                " verification_status, status) "
                "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, 'pending', 'active')",
                (sub_uuid, rtype, obj_uuid, tenant_id, r.get("confidence")),
            )
            stats["relations"] += 1
            aid = _insert_assertion(
                db, ctx,
                subject_id=sub_uuid, predicate=rtype, statement_text=stmt_text,
                statement_class=RELATION_DEFAULT_CLASS,
                object_entity_id=obj_uuid,
                confidence=r.get("confidence"),
                evidence_span_id=span["id"], evidence_quote=span["text"],
            )
            _write_assertion_embedding(db, aid, stmt_text, tenant_id)
            stats["assertions"] += 1

        # --- statements -> assertion rows (subject = brand, predicate = mentions) ---
        for s in statements:
            stext = s.get("text", "")
            sclass = s.get("statement_class", "inference")
            if not stext:
                continue
            if dry_run:
                stats["assertions"] += 1
                print(f"[candidate_extraction][dry] assertion: ({sclass}) {stext}")
                continue
            aid = _insert_assertion(
                db, ctx,
                subject_id=brand_id, predicate=MENTION_PREDICATE,
                statement_text=stext, statement_class=sclass,
                object_value={"text": stext},
                evidence_span_id=span["id"], evidence_quote=span["text"],
            )
            _write_assertion_embedding(db, aid, stext, tenant_id)
            stats["assertions"] += 1

    print(f"[candidate_extraction] stats={json.dumps(stats, ensure_ascii=False)}")
    return {**ctx, "pipeline": "candidate_extraction", "document_id": document_id,
            "dry_run": dry_run, "stats": stats}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 candidate extraction pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--document-id", required=True, help="document_id from source_registration")
    parser.add_argument("--dry-run", action="store_true", help="Run LLM but do not write")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2))
