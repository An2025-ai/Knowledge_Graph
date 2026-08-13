"""L3 pipeline: L2 Mapping.

Per brand_knowledge/pipelines/l2_mapping.yaml, this maps L3 brand entities to the
L2 generic industry-knowledge layer. The executor focuses on the capability path
(the most important one): for each L3 ``capability`` entity owned by the brand it
looks for a matching L2 ``capability`` entity in the shared layer (same
canonical_name, or an alias from ``entity_alias``) and upserts a ``brand_mapping``
row.

``mapping_type`` is ``exactMatch`` (exact canonical name) or ``closeMatch``
(alias match). ``closeMatch`` mappings are marked ``review_status='pending'`` so
they are never treated as fully equivalent downstream. Each row records
``mapping_type``, ``confidence``, ``mapper_version``, ``review_status`` and a
``mapping_note``.
"""
from __future__ import annotations

from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context

MAPPER_VERSION = "l2_mapping.v1.0.0"


def _find_l2_capability(db: DB, tenant_id: str, canonical_name: str) -> dict | None:
    """Find a shared L2 capability entity by canonical_name or alias."""
    rows = db.query(
        "SELECT id, canonical_name FROM entity "
        "WHERE tenant_id = %s AND entity_type = 'capability' "
        "AND owner_brand IS NULL AND canonical_name = %s "
        "AND status = 'active' LIMIT 1",
        (tenant_id, canonical_name),
    )
    if rows:
        return {"entity": rows[0], "via": "canonical_name"}
    alias_rows = db.query(
        "SELECT e.id, e.canonical_name FROM entity_alias a "
        "JOIN entity e ON e.id = a.entity_id "
        "WHERE e.tenant_id = %s AND e.entity_type = 'capability' "
        "AND e.owner_brand IS NULL AND e.status = 'active' "
        "AND a.alias_name = %s LIMIT 1",
        (tenant_id, canonical_name),
    )
    if alias_rows:
        return {"entity": alias_rows[0], "via": "alias"}
    return None


def run(db: DB, args) -> dict[str, Any]:
    """Map L3 brand capability entities onto L2 capability entities."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    capabilities = db.query(
        "SELECT id, canonical_name FROM entity "
        "WHERE tenant_id = %s AND entity_type = 'capability' AND owner_brand = %s "
        "AND status = 'active'",
        (tenant_id, brand_id),
    )

    mappings = []
    for cap in capabilities:
        match = _find_l2_capability(db, tenant_id, cap["canonical_name"])
        if not match:
            continue
        exact = match["via"] == "canonical_name"
        mapping_type = "exactMatch" if exact else "closeMatch"
        confidence = 1.0 if exact else 0.6
        review_status = "approved" if exact else "pending"
        mapping_note = f"matched via {match['via']}"

        if not getattr(args, "dry_run", False):
            db.execute(
                "INSERT INTO brand_mapping "
                "(id, tenant_id, brand_id, local_entity_id, l2_entity_id, mapping_type, "
                " confidence, mapping_note, review_status, mapper_version) "
                "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, local_entity_id, l2_entity_id, mapping_type) "
                "DO UPDATE SET review_status = EXCLUDED.review_status, "
                "confidence = EXCLUDED.confidence",
                (tenant_id, brand_id, cap["id"], match["entity"]["id"], mapping_type,
                 confidence, mapping_note, review_status, MAPPER_VERSION),
            )
        mappings.append({
            "local_entity_id": cap["id"],
            "local_name": cap["canonical_name"],
            "l2_entity_id": match["entity"]["id"],
            "l2_name": match["entity"]["canonical_name"],
            "mapping_type": mapping_type,
            "confidence": confidence,
            "review_status": review_status,
        })

    if getattr(args, "dry_run", False):
        print(f"[l2_mapping] DRY-RUN: {len(capabilities)} capability candidates, "
              f"{len(mappings)} mappings")
        for m in mappings[:10]:
            print(f"  {m['local_name']} [{m['mapping_type']}] -> {m['l2_name']}")
        return {**ctx, "pipeline": "l2_mapping", "dry_run": True,
                "candidate_count": len(capabilities), "mapping_count": len(mappings),
                "mappings": mappings}

    print(f"[l2_mapping] {len(mappings)} brand_mapping rows created "
          f"({len(capabilities)} capability candidates)")
    return {**ctx, "pipeline": "l2_mapping",
            "candidate_count": len(capabilities), "mapping_count": len(mappings),
            "mappings": mappings}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 L2 mapping pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
