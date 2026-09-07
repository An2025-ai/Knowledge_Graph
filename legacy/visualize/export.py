"""Export knowledge graph results from PostgreSQL to JSON for visualization.

Usage:
    python -m legacy.visualize.export --layer L1 --out legacy/visualize/output/l1.json
    python -m legacy.visualize.export --layer L2 --out legacy/visualize/output/l2.json
    python -m legacy.visualize.export --layer L3 --out legacy/visualize/output/l3.json
    python -m legacy.visualize.export --all --out legacy/visualize/output/all.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _query_rows(db, sql, params=None):
    return db.query(sql, params)


def _layer_for(e: dict) -> str:
    """Infer L1/L2/L3 layer for runtime entity rows."""
    owner = e.get("owner_brand")
    brand_id = e.get("brand_id") or (e.get("attributes") or {}).get("brand_id")
    if owner or brand_id:
        return "L3"
    if e.get("industry_id") or (e.get("attributes") or {}).get("industry_id"):
        return "L2"
    return "L1"


def build_graph(entities, relations, statements=None):
    """Convert DB rows into {nodes, edges, statements, stats}."""
    nodes = []
    for e in entities:
        nodes.append({
            "id": str(e.get("id")),
            "entity_id": e.get("entity_id"),
            "label": e.get("canonical_name") or "?",
            "type": e.get("entity_type") or "entity",
            "canonical_name": e.get("canonical_name"),
            "status": e.get("status"),
            "scope": e.get("scope"),
            "layer": _layer_for(e),
            "brand_id": e.get("brand_id"),
            "industry_id": e.get("industry_id"),
            "market": e.get("market"),
        })

    edges = []
    for r in relations:
        edges.append({
            "id": str(r.get("id")),
            "relation_id": r.get("id"),
            "subject_id": str(r.get("subject_id")),
            "object_id": str(r.get("object_id")),
            "type": r.get("relation_type") or r.get("relation"),
            "confidence": float(r.get("confidence")) if r.get("confidence") is not None else None,
            "verification_status": r.get("verification_status"),
        })

    stmts = []
    for s in (statements or []):
        stmts.append({
            "id": str(s.get("id")),
            "text": s.get("statement_text") or s.get("text"),
            "class": s.get("statement_class") or s.get("assertion_kind"),
            "status": s.get("status"),
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "statements": stmts,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "statements": len(stmts),
        },
    }


def _relations_for_entity_ids(db, entity_ids):
    """Return the induced relation subgraph for a selected entity set."""
    ids = [str(value) for value in entity_ids]
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    return _query_rows(
        db,
        f"SELECT id, subject_id, relation_type, object_id, confidence, verification_status "
        f"FROM relation WHERE status='active' "
        f"AND subject_id IN ({placeholders}) AND object_id IN ({placeholders})",
        tuple(ids + ids),
    )


def _active_entities(db):
    return _query_rows(
        db,
        "SELECT id, entity_id, canonical_name, entity_type, status, scope, "
        "owner_brand, brand_id, industry_id, market, attributes FROM entity "
        "WHERE status='active' ORDER BY entity_type",
    )


def _statements_for_entity_ids(db, ids, include_assertions=False):
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    statements = _query_rows(
        db,
        "SELECT id, statement_text, statement_class, status FROM statement "
        f"WHERE status='active' AND (subject_entity_id IN ({placeholders}) "
        f"OR object_entity_id IN ({placeholders})) LIMIT 500",
        tuple(ids + ids),
    )
    if include_assertions:
        statements.extend(_query_rows(
            db,
            "SELECT id, statement_text, statement_class, status FROM assertion "
            f"WHERE status='active' AND (subject_id IN ({placeholders}) "
            f"OR object_entity_id IN ({placeholders})) LIMIT 500",
            tuple(ids + ids),
        ))
    return statements


def export_layer(db, layer: str, out_path=None) -> dict:
    """Export one logical layer only."""
    layer = layer.upper()
    if layer == "L1":
        entity_types = _query_rows(
            db,
            "SELECT type_code AS id, type_code AS entity_id, canonical_name, "
            "'entity_type' AS entity_type, status, 'definition' AS scope "
            "FROM entity_type WHERE status='active' ORDER BY type_code",
        )
        relation_types = _query_rows(
            db,
            "SELECT relation_code AS id, relation_code AS entity_id, relation_code AS canonical_name, "
            "'relation_type' AS entity_type, status, 'definition' AS scope "
            "FROM relation_type WHERE status='active' ORDER BY relation_code",
        )
        graph = build_graph(entity_types + relation_types, [])
        for node in graph["nodes"]:
            node["layer"] = "L1"
        return write_output(graph, out_path)

    if layer not in {"L2", "L3"}:
        raise ValueError("--layer must be one of: L1, L2, L3")
    entities = [e for e in _active_entities(db) if _layer_for(e) == layer]
    ids = [str(e["id"]) for e in entities]
    relations = _relations_for_entity_ids(db, ids)
    statements = _statements_for_entity_ids(db, ids, include_assertions=(layer == "L3"))
    return write_output(build_graph(entities, relations, statements), out_path)


def export_industry(db, industry_id=None, out_path=None) -> dict:
    """Export entities/relations tagged to an industry (L2)."""
    where = " WHERE status='active'"
    params = None
    if industry_id:
        where += " AND (industry_id = %s OR attributes->>'industry_id' = %s)"
        params = (industry_id, industry_id)
    entities = _query_rows(
        db,
        "SELECT id, entity_id, canonical_name, entity_type, status, scope, "
        "owner_brand, brand_id, industry_id, market, attributes FROM entity"
        + where + " ORDER BY entity_type",
        params,
    )
    ids = [str(e["id"]) for e in entities]
    relations = _relations_for_entity_ids(db, ids)
    statements = _statements_for_entity_ids(db, ids)
    return write_output(build_graph(entities, relations, statements), out_path)


def export_brand(db, brand_id, tenant_id=None, out_path=None) -> dict:
    """Export entities/relations for a specific brand (L3)."""
    brand_params = [brand_id, brand_id, brand_id]
    tenant_clause = ""
    if tenant_id:
        tenant_clause = " AND tenant_id::text = %s"
        brand_params.append(tenant_id)
    brands = _query_rows(
        db,
        "SELECT id FROM entity WHERE entity_type='brand' "
        "AND (id::text = %s OR entity_id = %s OR canonical_name = %s)"
        + tenant_clause + " LIMIT 1",
        tuple(brand_params),
    )
    if not brands:
        raise ValueError(f"brand not found: {brand_id}")

    brand_uuid = str(brands[0]["id"])
    entity_params = [brand_uuid, brand_uuid, brand_uuid]
    entity_tenant_clause = ""
    if tenant_id:
        entity_tenant_clause = " AND tenant_id::text = %s"
        entity_params.append(tenant_id)
    entities = _query_rows(
        db,
        "SELECT id, entity_id, canonical_name, entity_type, status, scope, "
        "owner_brand, brand_id, industry_id, market, attributes "
        "FROM entity WHERE status='active' AND (id::text = %s OR owner_brand = %s::uuid "
        "OR attributes->>'brand_id' = %s)" + entity_tenant_clause
        + " ORDER BY entity_type",
        tuple(entity_params),
    )
    ids = [str(e["id"]) for e in entities]
    relations = _relations_for_entity_ids(db, ids)
    statements = _statements_for_entity_ids(db, ids, include_assertions=True)
    return write_output(build_graph(entities, relations, statements), out_path)


def export_all(db, out_path=None) -> dict:
    entities = _active_entities(db)
    relations = _query_rows(
        db,
        "SELECT id, subject_id, relation_type, object_id, confidence, verification_status "
        "FROM relation WHERE status='active'",
    )
    statements = _query_rows(
        db,
        "SELECT id, statement_text, statement_class, status FROM statement "
        "WHERE status='active' LIMIT 500",
    )
    statements.extend(_query_rows(
        db,
        "SELECT id, statement_text, statement_class, status FROM assertion "
        "WHERE status='active' LIMIT 500",
    ))
    return write_output(build_graph(entities, relations, statements), out_path)


def write_output(graph: dict, out_path=None) -> dict:
    path = Path(out_path) if out_path else Path(__file__).resolve().parent / "output" / "knowledge_graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export] wrote {path} ({graph['stats']})")
    return graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Export PG knowledge graph to JSON for visualization.")
    parser.add_argument("--out", default=None, help="output JSON path")
    parser.add_argument("--industry", default=None, help="filter to an industry tree")
    parser.add_argument("--brand", default=None, help="filter to a brand id/name")
    parser.add_argument("--tenant", default=None, help="tenant id for brand export")
    parser.add_argument("--all", dest="all_", action="store_true", help="export everything")
    parser.add_argument("--layer", choices=["L1", "L2", "L3", "l1", "l2", "l3"], help="export one layer only")
    args = parser.parse_args()

    from legacy.core.db import DB

    with DB() as db:
        if args.layer:
            export_layer(db, args.layer, args.out)
        elif args.brand:
            export_brand(db, args.brand, args.tenant, args.out)
        elif args.industry:
            export_industry(db, args.industry, args.out)
        else:
            export_all(db, args.out)
    print("[export] done - open the notebook to visualize")
    return 0


if __name__ == "__main__":
    sys.exit(main())
