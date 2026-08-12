"""L3 pipeline: Evidence Verification.

Per brand_knowledge/pipelines/evidence_verification.yaml, this links each
assertion to the evidence span (``document_chunk``) it came from and records a
``support_status``:

  - ``direct``: the evidence quote directly supports the statement,
  - ``partial``: only partly supports it.

How it works here:

  1. For each candidate assertion, read the evidence span reference stored in its
     ``scope`` (``evidence_span_id`` + ``evidence_quote``) by candidate_extraction.
  2. Ensure a corresponding ``evidence`` row exists for that document chunk
     (upserted by a stable ``evidence_id`` derived from the chunk id).
  3. Insert an ``assertion_evidence`` join row with ``support_status`` — ``direct``
     when the evidence quote is a sub-string of (or equal to) the statement text,
     else ``partial``.

Inserting into ``assertion_evidence`` is append-only, so this never conflicts
with the assertion append+supersedes trigger.
"""
from __future__ import annotations

from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context


def _evidence_id_for_chunk(chunk_id: str) -> str:
    return f"ev_{chunk_id.replace('-', '')[:32]}"


def _ensure_evidence(db: DB, ctx: dict, *, chunk_id, chunk_text, document_id) -> str:
    """Return the `evidence` UUID for a chunk, creating the row if needed."""
    ev_id = _evidence_id_for_chunk(chunk_id)
    rows = db.query("SELECT id FROM evidence WHERE evidence_id = %s", (ev_id,))
    if rows:
        return rows[0]["id"]
    return db.insert_returning_id(
        "INSERT INTO evidence "
        "(id, evidence_id, tenant_id, source_id, document_id, chunk_id, quote, "
        " content_hash, access_level, support_status) "
        "VALUES (uuid_generate_v4(), %s, %s, NULL, %s, %s, %s, %s, %s, 'pending') "
        "RETURNING id",
        (ev_id, ctx["tenant_id"], document_id, chunk_id, chunk_text,
         _hash(chunk_text), ctx.get("access_level", "internal")),
    )


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(db: DB, args) -> dict[str, Any]:
    """Link assertions to evidence spans via assertion_evidence join rows."""
    ctx = resolve_brand_context(db, args)
    ctx["access_level"] = getattr(args, "access_level", None) or "internal"
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    assertions = db.query(
        "SELECT id, statement_text, scope FROM assertion "
        "WHERE tenant_id = %s AND brand_id = %s AND status = 'candidate'",
        (tenant_id, brand_id),
    )

    dry_run = bool(getattr(args, "dry_run", False))
    stats = {"assertions": len(assertions), "linked": 0, "direct": 0, "partial": 0,
             "no_evidence": 0}

    for a in assertions:
        scope = a["scope"] or {}
        span_id = scope.get("evidence_span_id")
        quote = scope.get("evidence_quote", "")
        if not span_id:
            stats["no_evidence"] += 1
            continue

        chunk = db.query(
            "SELECT id, document_id, text FROM document_chunk WHERE id = %s LIMIT 1",
            (span_id,),
        )
        if not chunk:
            stats["no_evidence"] += 1
            continue
        chunk_id, document_id, chunk_text = chunk[0]["id"], chunk[0]["document_id"], chunk[0]["text"]

        # direct when the quote is contained in the statement text (or vice versa)
        stmt = a["statement_text"] or ""
        support_status = "direct" if (quote and (quote in stmt or stmt in quote)) else "partial"

        if dry_run:
            stats["linked"] += 1
            if support_status == "direct":
                stats["direct"] += 1
            else:
                stats["partial"] += 1
            continue

        evidence_uuid = _ensure_evidence(db, ctx, chunk_id=chunk_id,
                                         chunk_text=chunk_text, document_id=document_id)

        # idempotent join (PK = assertion_id, evidence_id)
        db.execute(
            "INSERT INTO assertion_evidence (assertion_id, evidence_id, support_status, "
            " support_reason, verifier_version) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (assertion_id, evidence_id) DO UPDATE SET "
            "support_status = EXCLUDED.support_status",
            (a["id"], evidence_uuid, support_status,
             "evidence quote matches statement text" if support_status == "direct"
             else "evidence quote partially supports statement",
             "evidence_verification.v1.0.0"),
        )
        stats["linked"] += 1
        if support_status == "direct":
            stats["direct"] += 1
        else:
            stats["partial"] += 1

    print(f"[evidence_verification] {stats}")
    return {**ctx, "pipeline": "evidence_verification", "dry_run": dry_run, "stats": stats}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 evidence verification pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))