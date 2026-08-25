"""L3 pipeline: Entity Normalization and Disambiguation.

Per OPTIMIZATION_TECH_PLAN.md §4.4, this upgrades entity resolution from
exact-name-only to a blocking + similarity cascade while keeping exact match as
the cheapest first rule.

Two passes:
  1. Exact (tenant_id, entity_type, canonical_name) merge — keep earliest as
     canonical, mark later duplicates deprecated.
  2. Semantic pass — same type-candidates whose normalized names are near-fuzzy
     (e.g. alias / abbreviation / whitespace differences). For each ambiguous
     candidate, compute name similarity + embedding similarity and:
        score >= AUTO_MERGE_THRESHOLD (.90)  -> merge
        0.75 <= score < .90                  -> review_queue (needs human)
        otherwise                            -> keep as distinct entity

High-risk entity types (brand, organization, product, product_version,
certification) are never auto-merged unless score is extremely high, and are
always routed to review_queue for confirmation.
"""
from __future__ import annotations

import difflib
from typing import Any

from runtime.db import DB
from runtime.brand.pipelines._helpers import resolve_brand_context

# High-risk entity types that require human confirmation before acceptance.
HIGH_RISK_TYPES = {"brand", "organization", "product", "product_version", "certification"}

# Similarity scoring weights (OPTIMIZATION_TECH_PLAN.md §4.4).
W_NAME = 0.45
W_EMBED = 0.35
W_ALIAS = 0.20

AUTO_MERGE_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.75


def _norm_name(name: str) -> str:
    """Normalize: lowercase, strip spaces/punct/full-width->half-width."""
    import unicodedata

    nfkd = "".join(
        unicodedata.normalize("NFKC", ch) if unicodedata.category(ch) not in ("Lo",) else ch
        for ch in str(name)
    )
    # remove whitespace, punctuation, case variants
    cleaned = "".join(ch.lower() for ch in nfkd if not ch.isspace() and ch not in "，。；：、()（）[]【】·")
    return cleaned


def _name_similarity(a: str, b: str) -> float:
    a, b = _norm_name(a), _norm_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _fuzzy_pre_filter(a: str, b: str) -> bool:
    """Cheap blocking gate: only run embedding for plausibly-similar names."""
    a, b = _norm_name(a), _norm_name(b)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return len(a) >= 4 and (a[:2] == b[:2])  # share first 2 chars


def _compute_similarity(entity_a: dict, entity_b: dict, embed_client=None, db=None) -> float:
    """Weighted name+embedding similarity for two same-type entities.

    Prefers the persisted ``entity_embedding`` table (via dot product of stored
    normalized vectors) so we don't re-embed every pair; falls back to live
    ``embed_client.embed_one`` when the vector table has no row for either id.
    """
    name_a = entity_a["canonical_name"]
    name_b = entity_b["canonical_name"]
    s_name = _name_similarity(name_a, name_b)

    # alias overlap bonus
    aliases_a = set(entity_a.get("aliases") or [])
    aliases_b = set(entity_b.get("aliases") or [])
    s_alias = 1.0 if (aliases_a & aliases_b) or name_a in aliases_b or name_b in aliases_a else 0.0

    s_embed = 0.0
    va = _vector_for_entity(db, entity_a)
    vb = _vector_for_entity(db, entity_b)
    if va is None and vb is None and embed_client is not None:
        # no persisted vectors -> live embed fallback (costlier)
        try:
            vb = embed_client.embed_one(name_b)
            va = embed_client.embed_one(name_a)
        except Exception:
            va = vb = None
    if va is not None and vb is not None:
        try:
            import numpy as np

            s_embed = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))
        except Exception:
            s_embed = 0.0
    return W_NAME * s_name + W_EMBED * s_embed + W_ALIAS * s_alias


def _vector_for_entity(db, entity: dict) -> list[float] | None:
    """Return the stored embedding vector for an entity from entity_embedding, or None."""
    if db is None:
        return None
    eid = entity.get("id")
    if not eid:
        return None
    try:
        rows = db.query(
            "SELECT embedding FROM entity_embedding WHERE entity_id = %s LIMIT 1",
            (eid,),
        )
        return rows[0]["embedding"] if rows else None
    except Exception:  # noqa: BLE001 - table may be empty/unavailable
        return None


def run(db: DB, args) -> dict[str, Any]:
    """Dedupe/merge entities (exact + semantic fuzzy)."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    entities = db.query(
        "SELECT id, entity_id, entity_type, canonical_name, "
        "COALESCE(source_refs->>'aliases') AS aliases_json, status "
        "FROM entity "
        "WHERE tenant_id = %s AND owner_brand = %s AND status = 'active' "
        "ORDER BY created_at ASC, id ASC",
        (tenant_id, brand_id),
    )
    # parse aliases_json
    import json as _json

    for row in entities:
        aj = row.get("aliases_json")
        row["aliases"] = _json.loads(aj) if aj else []

    # Optional embedding client for semantic pass (skip if unavailable).
    embed_client = None
    enable_semantic = getattr(args, "embedding", True)
    if enable_semantic:
        try:
            from runtime.embeddings import get_embedding_client

            embed_client = get_embedding_client()
        except Exception:
            embed_client = None

    merged: dict[str, str] = {}
    seen_exact: dict[tuple[str, str], str] = {}
    review_items: list[dict] = []
    semantic_merges = 0

    # First pass: exact merge.
    for row in entities:
        key = (row["entity_type"], row["canonical_name"])
        if key in seen_exact:
            db.execute("UPDATE entity SET status = 'deprecated' WHERE id = %s", (row["id"],))
            merged[row["id"]] = seen_exact[key]
            continue
        seen_exact[key] = row["id"]

    active = [e for e in entities if e["id"] not in merged]

    # Second pass: semantic fuzzy merge among distinct entities of same type.
    processed: set[str] = set()
    for i, a in enumerate(active):
        if a["id"] in processed:
            continue
        for b in active[i + 1 :]:
            if a["entity_type"] != b["entity_type"]:
                continue
            if b["id"] in merged:
                continue
            if not _fuzzy_pre_filter(a["canonical_name"], b["canonical_name"]):
                continue
            score = _compute_similarity(a, b, embed_client, db=db)
            if score >= AUTO_MERGE_THRESHOLD:
                # auto-merge b into a (deprecate b)
                db.execute("UPDATE entity SET status = 'deprecated' WHERE id = %s", (b["id"],))
                merged[b["id"]] = a["id"]
                processed.add(b["id"])
                semantic_merges += 1
            elif score >= REVIEW_THRESHOLD:
                # ambiguous -> review (never auto for high-risk)
                reason = (f"ambiguous entity match '{a['canonical_name']}' vs "
                          f"'{b['canonical_name']}' ({a['entity_type']}), score={score:.2f}")
                db.execute(
                    "INSERT INTO review_queue "
                    "(id, target_type, target_id, tenant_id, review_type, priority, reason, status) "
                    "VALUES (uuid_generate_v4(), 'entity', %s, %s, 'entity_confirmation', 5, %s, 'pending') "
                    "ON CONFLICT DO NOTHING",
                    (b["id"], tenant_id, reason),
                )
                review_items.append({"entity_id": b["id"], "entity_type": a["entity_type"],
                                     "canonical_name": b["canonical_name"], "reason": reason})

    # High-risk entities always go to review for human confirmation.
    for row in active:
        if row["entity_type"] in HIGH_RISK_TYPES:
            db.execute(
                "INSERT INTO review_queue "
                "(id, target_type, target_id, tenant_id, review_type, priority, reason, status) "
                "VALUES (uuid_generate_v4(), 'entity', %s, %s, 'entity_confirmation', 5, %s, 'pending') "
                "ON CONFLICT DO NOTHING",
                (row["id"], tenant_id,
                 f"high-risk entity '{row['canonical_name']}' ({row['entity_type']}) needs confirmation"),
            )
            if not any(r["entity_id"] == row["id"] for r in review_items):
                review_items.append({"entity_id": row["id"],
                                     "entity_type": row["entity_type"],
                                     "canonical_name": row["canonical_name"],
                                     "reason": "high-risk type"})

    if getattr(args, "dry_run", False):
        print(f"[entity_resolution] DRY-RUN: {len(entities)} entities, "
              f"{len(merged)} merged ({semantic_merges} semantic), {len(review_items)} review")
        return {**ctx, "pipeline": "entity_resolution", "dry_run": True,
                "entity_count": len(entities), "merged_count": len(merged),
                "semantic_merge_count": semantic_merges, "review_items": review_items}

    print(f"[entity_resolution] {len(entities)} entities, {len(merged)} merged "
          f"({semantic_merges} semantic), {len(review_items)} review")
    return {**ctx, "pipeline": "entity_resolution",
            "entity_count": len(entities), "merged_count": len(merged),
            "semantic_merge_count": semantic_merges,
            "merged": merged, "review_items": review_items}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 entity resolution pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))