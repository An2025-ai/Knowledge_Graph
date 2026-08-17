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


def _find_l2_entity(
    db: DB, tenant_id: str, entity_type: str, canonical_name: str
) -> dict | None:
    """Find an active cross-tenant L2 entity by canonical name or alias."""
    # L2 is the cross-tenant industry layer.  Its entities are written with a
    # NULL tenant_id; tenant_id is accepted only to preserve the pipeline API.
    # Filtering L2 by the L3 tenant made every real shared entity invisible.
    rows = db.query(
        "SELECT id, canonical_name FROM entity "
        "WHERE tenant_id IS NULL AND entity_type = %s "
        "AND owner_brand IS NULL AND scope = 'shared' AND canonical_name = %s "
        "AND status = 'active' LIMIT 1",
        (entity_type, canonical_name),
    )
    if rows:
        return {"entity": rows[0], "via": "canonical_name"}
    alias_rows = db.query(
        "SELECT e.id, e.canonical_name FROM entity_alias a "
        "JOIN entity e ON e.id = a.entity_id "
        "WHERE e.tenant_id IS NULL AND e.entity_type = %s "
        "AND e.owner_brand IS NULL AND e.scope = 'shared' AND e.status = 'active' "
        "AND a.alias_name = %s LIMIT 1",
        (entity_type, canonical_name),
    )
    if alias_rows:
        return {"entity": alias_rows[0], "via": "alias"}
    return None


def _find_l2_capability(db: DB, tenant_id: str, canonical_name: str) -> dict | None:
    """Backward-compatible capability-specific L2 lookup."""
    return _find_l2_entity(db, tenant_id, "capability", canonical_name)


def run(db: DB, args) -> dict[str, Any]:
    """Optionally map L3 brand capabilities onto shared L2 capabilities."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    mappings = []

    def record(local_id, local_name, target, mapping_type, note=""):
        if not target:
            return
        exact = target["via"] == "canonical_name"
        mt = mapping_type if mapping_type else ("exactMatch" if exact else "closeMatch")
        confidence = 1.0 if exact else 0.6
        review_status = "approved" if exact else "pending"
        mapping_note = note or f"matched via {target['via']}"
        if not getattr(args, "dry_run", False):
            db.execute(
                "INSERT INTO brand_mapping "
                "(id, tenant_id, brand_id, local_entity_id, l2_entity_id, mapping_type, "
                " confidence, mapping_note, review_status, mapper_version) "
                "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, local_entity_id, l2_entity_id, mapping_type) "
                "DO UPDATE SET review_status = EXCLUDED.review_status, "
                "confidence = EXCLUDED.confidence",
                (tenant_id, brand_id, local_id, target["entity"]["id"], mt,
                 confidence, mapping_note, review_status, MAPPER_VERSION),
            )
        mappings.append({
            "local_entity_id": local_id,
            "local_name": local_name,
            "l2_entity_id": target["entity"]["id"],
            "l2_name": target["entity"]["canonical_name"],
            "mapping_type": mt,
            "confidence": confidence,
            "review_status": review_status,
        })

    # resident entities created earlier
    capabilities = db.query(
        "SELECT id, canonical_name FROM entity "
        "WHERE tenant_id = %s AND entity_type = 'capability' AND owner_brand = %s "
        "AND status = 'active'",
        (tenant_id, brand_id),
    )
    for cap in capabilities:
        match = _find_l2_capability(db, tenant_id, cap["canonical_name"])
        record(cap["id"], cap["canonical_name"], match,
               mapping_type=None, note=f"capability -> shared capability")

    candidates = len(capabilities)

    if getattr(args, "dry_run", False):
        print(f"[l2_mapping] DRY-RUN: {candidates} candidates, {len(mappings)} mappings")
        for m in mappings[:10]:
            print(f"  {m['local_name']} [{m['mapping_type']}] -> {m['l2_name']}")
        return {**ctx, "pipeline": "l2_mapping", "dry_run": True,
                "candidate_count": candidates, "mapping_count": len(mappings),
                "mappings": mappings}

    print(f"[l2_mapping] {len(mappings)} brand_mapping rows created "
          f"({candidates} candidates)")
    return {**ctx, "pipeline": "l2_mapping",
            "candidate_count": candidates, "mapping_count": len(mappings),
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
