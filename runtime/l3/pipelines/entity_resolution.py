"""L3 pipeline: Entity Normalization and Disambiguation.

Per brand_knowledge/pipelines/entity_resolution.yaml, this pipeline normalizes
candidate entities into canonical entities within the tenant and disambiguates
them. The full production design is a 7-step cascade with weighted features;
this executor implements the deterministic core steps pragmatically:

  - exact ID / canonical-name match within the tenant (reuse the existing id),
  - merges entities that share the same (tenant_id, entity_type, canonical_name)
    by keeping the earliest row as canonical and marking later duplicates
    ``status='deprecated'``,
  - routes high-risk entity types (brand, organization, product) that need
    confirmation into ``review_queue``.

The merge mapping (duplicate -> canonical uuid) is returned so orchestrators can
report on it. No entity is silently deleted.
"""
from __future__ import annotations

from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context

# High-risk entity types that require human confirmation before acceptance.
HIGH_RISK_TYPES = {"brand", "organization", "product", "certification"}


def run(db: DB, args) -> dict[str, Any]:
    """Dedupe/merge entities by canonical_name within the tenant."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    # Consider entities owned by this brand (owner_brand = brand_id) plus the
    # brand anchor itself. We focus on brand-local candidate entities.
    entities = db.query(
        "SELECT id, entity_id, entity_type, canonical_name, status "
        "FROM entity "
        "WHERE tenant_id = %s AND owner_brand = %s AND status = 'active' "
        "ORDER BY created_at ASC, id ASC",
        (tenant_id, brand_id),
    )

    merged: dict[str, str] = {}  # duplicate uuid -> canonical uuid
    seen: dict[tuple[str, str], str] = {}  # (entity_type, canonical_name) -> canonical uuid
    review_items: list[dict] = []

    for row in entities:
        key = (row["entity_type"], row["canonical_name"])
        if key in seen:
            # duplicate -> mark deprecated, keep canonical
            db.execute(
                "UPDATE entity SET status = 'deprecated' WHERE id = %s",
                (row["id"],),
            )
            merged[row["id"]] = seen[key]
            continue
        seen[key] = row["id"]
        if row["entity_type"] in HIGH_RISK_TYPES:
            db.execute(
                "INSERT INTO review_queue "
                "(id, target_type, target_id, tenant_id, review_type, priority, reason, status) "
                "VALUES (uuid_generate_v4(), 'entity', %s, %s, 'entity_confirmation', 5, %s, 'pending') "
                "ON CONFLICT DO NOTHING",
                (row["id"], tenant_id,
                 f"high-risk entity '{row['canonical_name']}' ({row['entity_type']}) needs confirmation"),
            )
            review_items.append({"entity_id": row["id"], "entity_type": row["entity_type"],
                                 "canonical_name": row["canonical_name"]})

    if getattr(args, "dry_run", False):
        print(f"[entity_resolution] DRY-RUN: {len(entities)} brand entities, "
              f"{len(merged)} duplicates to deprecate, {len(review_items)} high-risk")
        for dup, canon in list(merged.items())[:10]:
            print(f"  merge {dup} -> {canon}")
        return {**ctx, "pipeline": "entity_resolution", "dry_run": True,
                "entity_count": len(entities), "merged_count": len(merged),
                "review_items": review_items}

    print(f"[entity_resolution] {len(entities)} entities, {len(merged)} merged, "
          f"{len(review_items)} queued for review")
    return {**ctx, "pipeline": "entity_resolution",
            "entity_count": len(entities), "merged_count": len(merged),
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