"""L3 pipeline: Semantic Evidence Verification.

Per OPTIMIZATION_TECH_PLAN.md §4.5, this upgrades evidence verification from
pure string containment to a semantic support judgment:

  - ``direct_support``: evidence directly supports the statement,
  - ``partial_support``: only partly supports it,
  - ``insufficient``: evidence is too thin / unrelated,
  - ``contradicted``: evidence contradicts the statement.

Method (routed by assertion risk):
  1. String containment / exact quote match  -> strong direct (cheap fast path).
  2. Embedding similarity (bge-m3) between evidence text and statement  ->
     direct / partial / insufficient.
  3. LLM verifier for high-risk categories (certification, ROI, absolute
     claims, SLA, competitor comparison) -> judgment + reason.

The verifier result (support_status, confidence, reason, unsupported_parts,
verifier_version) is stored on the ``assertion_evidence`` join row — confidence
and details are packed into ``support_reason`` (JSON) since that table has no
dedicated columns.
"""
from __future__ import annotations

import json
from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context

VERIFIER_VERSION = "semantic_evidence_verifier.v1.0.0"

# High-risk markers that should route to the LLM verifier.
HIGH_RISK_MARKERS = [
    "首次", "唯一", "首个", "领先", "最全", "最准", "最好", "最佳",
    "ROI", "投资回报", "节省", "提升", "百分比", "%", "认证", "资质",
    "ISO", "等保", "SLA", "响应", "竞品", "对比", "第一名", "第一",
]

# support classes the pipeline distinguishes
SUPPORT_STATUSES = ("direct_support", "partial_support", "insufficient", "contradicted")


def _evidence_id_for_chunk(chunk_id: str) -> str:
    return f"ev_{chunk_id.replace('-', '')[:32]}"


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ensure_evidence(db: DB, ctx: dict, *, chunk_id, chunk_text, document_id) -> str:
    """Return the `evidence` UUID for a chunk, creating the row if needed."""
    ev_id = _evidence_id_for_chunk(chunk_id)
    rows = db.query("SELECT id FROM evidence WHERE evidence_id = %s", (ev_id,))
    if rows:
        return rows[0]["id"]
    evidence_uuid = db.insert_returning_id(
        "INSERT INTO evidence "
        "(id, evidence_id, tenant_id, source_id, document_id, chunk_id, quote, "
        " content_hash, access_level, support_status) "
        "VALUES (uuid_generate_v4(), %s, %s, NULL, %s, %s, %s, %s, %s, 'pending') "
        "RETURNING id",
        (ev_id, ctx["tenant_id"], document_id, chunk_id, chunk_text,
         _hash(chunk_text), ctx.get("access_level", "internal")),
    )
    # Persist the evidence vector (optional, non-fatal) for semantic verification.
    try:
        from runtime.embeddings import write_embedding

        write_embedding(db, "evidence_embedding", evidence_uuid, chunk_text,
                        ctx["tenant_id"])
    except Exception:  # noqa: BLE001 - optional vector layer
        pass
    return evidence_uuid


def _is_high_risk(stmt: str) -> bool:
    s = stmt or ""
    return any(marker in s for marker in HIGH_RISK_MARKERS)


def _embed_similarity(text_a: str, text_b: str, embed_client) -> float | None:
    """Cosine similarity of two texts via embedding client; None on failure."""
    try:
        import numpy as np

        v1 = embed_client.embed_one(text_a)
        v2 = embed_client.embed_one(text_b)
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    except Exception:
        return None


def _semantic_gate(quote: str, stmt: str, embed_client) -> str:
    """Judge support from string containment + embedding similarity alone."""
    if quote and (quote in stmt or stmt in quote):
        return "direct_support"
    sim = _embed_similarity(stmt, quote, embed_client) if embed_client else None
    if sim is None:
        # Embedding unavailable -> fall back to a weak containment heuristic.
        if quote and stmt:
            shared = set(quote) & set(stmt)
            return "partial_support" if len(shared) > 8 else "insufficient"
        return "insufficient"
    if sim >= 0.75:
        return "direct_support"
    if sim >= 0.50:
        return "partial_support"
    return "insufficient"


def _llm_verify(client, quote: str, stmt: str) -> dict[str, Any]:
    """Use the LLM to judge entailment for high-risk statements."""
    from runtime.extract import extract_json

    system = (
        "你是证据支持核验器。判断证据引言是否支持/部分支持/不足/矛盾于给定陈述。"
        "只输出 JSON: {\"support_status\": \"direct_support|partial_support|insufficient|contradicted\","
        " \"confidence\": 0.0-1.0, \"reason\": \"...\", \"unsupported_parts\": []}"
    )
    user = f"证据引言:\n{quote}\n\n陈述:\n{stmt}"
    try:
        payload = extract_json(client, system, user, max_tokens=300)
    except Exception:
        # LLM unavailable -> degrade to semantic gate
        return {"support_status": _semantic_gate(quote, stmt, None),
                "confidence": 0.5, "reason": "llm unavailable, heuristic", "unsupported_parts": []}
    status = payload.get("support_status")
    if status not in SUPPORT_STATUSES:
        status = _semantic_gate(quote, stmt, None)
    return {
        "support_status": status,
        "confidence": float(payload.get("confidence") or 0.5),
        "reason": payload.get("reason", ""),
        "unsupported_parts": payload.get("unsupported_parts", []),
    }


def run(db: DB, args) -> dict[str, Any]:
    """Semantically verify assertion evidence support."""
    ctx = resolve_brand_context(db, args)
    ctx["access_level"] = getattr(args, "access_level", None) or "internal"
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    assertions = db.query(
        "SELECT id, statement_text, scope FROM assertion "
        "WHERE tenant_id = %s AND brand_id = %s AND status = 'candidate'",
        (tenant_id, brand_id),
    )

    # Lazy-load embedding client (bge-m3) for semantic scoring.
    embed_client = None
    try:
        from runtime.embeddings import get_embedding_client

        embed_client = get_embedding_client()
    except Exception:
        embed_client = None

    dry_run = bool(getattr(args, "dry_run", False))
    stats = {"assertions": len(assertions), "linked": 0, "no_evidence": 0}
    for s in SUPPORT_STATUSES:
        stats[s] = 0

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
        stmt = a["statement_text"] or ""

        # Route: high-risk -> LLM verifier; else semantic embedding gate.
        if _is_high_risk(stmt):
            try:
                from runtime.extract import load_llm

                client = load_llm()
            except Exception:
                client = None
            result = _llm_verify(client, chunk_text, stmt) if client else {
                "support_status": _semantic_gate(chunk_text, stmt, embed_client),
                "confidence": None,
                "reason": "llm unavailable, semantic gate fallback",
                "unsupported_parts": [],
            }
            status = result["support_status"]
            verifier = "llm|semantic_evidence_verifier.v1"
        else:
            status = _semantic_gate(chunk_text, stmt, embed_client)
            result = {"support_status": status, "confidence": None,
                      "reason": f"semantic gate sim-based", "unsupported_parts": []}
            verifier = "semantic_evidence_verifier.v1"

        stats["linked"] += 1
        if status in stats:
            stats[status] += 1

        if dry_run:
            continue

        evidence_uuid = _ensure_evidence(db, ctx, chunk_id=chunk_id,
                                         chunk_text=chunk_text, document_id=document_id)
        reason_json = {
            "support_status": status,
            "confidence": result.get("confidence"),
            "reason": result.get("reason", ""),
            "unsupported_parts": result.get("unsupported_parts", []),
        }
        db.execute(
            "INSERT INTO assertion_evidence (assertion_id, evidence_id, support_status, "
            " support_reason, verifier_version) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (assertion_id, evidence_id) DO UPDATE SET "
            "support_status = EXCLUDED.support_status, "
            "support_reason = EXCLUDED.support_reason, "
            "verifier_version = EXCLUDED.verifier_version",
            (a["id"], evidence_uuid, status,
             json.dumps(reason_json, ensure_ascii=False), verifier),
        )

    print(f"[evidence_verification] {stats}")
    return {**ctx, "pipeline": "evidence_verification", "dry_run": dry_run, "stats": stats}


def _evidence_id_for_chunk(chunk_id: str) -> str:
    return f"ev_{chunk_id.replace('-', '')[:32]}"


def _ensure_evidence(db: DB, ctx: dict, *, chunk_id, chunk_text, document_id) -> str:
    """Return the `evidence` UUID for a chunk, creating the row if needed."""
    ev_id = _evidence_id_for_chunk(chunk_id)
    rows = db.query("SELECT id FROM evidence WHERE evidence_id = %s", (ev_id,))
    if rows:
        return rows[0]["id"]
    evidence_uuid = db.insert_returning_id(
        "INSERT INTO evidence "
        "(id, evidence_id, tenant_id, source_id, document_id, chunk_id, quote, "
        " content_hash, access_level, support_status) "
        "VALUES (uuid_generate_v4(), %s, %s, NULL, %s, %s, %s, %s, %s, 'pending') "
        "RETURNING id",
        (ev_id, ctx["tenant_id"], document_id, chunk_id, chunk_text,
         _hash(chunk_text), ctx.get("access_level", "internal")),
    )
    # Persist the evidence vector (optional, non-fatal) for semantic verification.
    try:
        from runtime.embeddings import write_embedding

        write_embedding(db, "evidence_embedding", evidence_uuid, chunk_text,
                        ctx["tenant_id"])
    except Exception:  # noqa: BLE001 - optional vector layer
        pass
    return evidence_uuid


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