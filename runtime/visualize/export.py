"""Export knowledge graph results from PostgreSQL to a JSON file for Jupyter visualization.

Usage:
    python -m runtime.visualize.export --out runtime/visualize/output/graph.json
    python -m runtime.visualize.export --industry <industry_id> --out out.json
    python -m runtime.visualize.export --brand <brand_id> --tenant <tenant_id> --out out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _query_rows(db, sql, params=None):
    return db.query(sql, params)


def build_graph(entities, relations, statements=None):
    """Convert DB rows into {nodes, edges, stats} for pyvis/networkx."""
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
    if statements:
        for s in statements:
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


def export_industry(db, industry_id=None, out_path=None) -> dict:
    """Export entities/relations tagged to an industry (L2)."""
    where = ""
    params = None
    if industry_id:
        where = " WHERE (industry_id = %s OR attributes->>'industry_id' = %s)"
        params = (industry_id, industry_id)
    entities = _query_rows(
        db,
        "SELECT id, entity_id, canonical_name, entity_type, status, scope "
        "FROM entity" + where + " ORDER BY entity_type",
        params,
    )
    relations = _relations_for_entity_ids(db, [e["id"] for e in entities])
    return write_output(build_graph(entities, relations), out_path)


def export_brand(db, brand_id, tenant_id=None, out_path=None) -> dict:
    """Export entities/relations for a specific brand (L3)."""
    # Resolve UUID, business entity_id, or canonical brand name first. This
    # avoids casting arbitrary user input to UUID.
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
        "SELECT id, entity_id, canonical_name, entity_type, status, scope "
        "FROM entity WHERE (id::text = %s OR owner_brand = %s::uuid "
        "OR attributes->>'brand_id' = %s)" + entity_tenant_clause
        + " ORDER BY entity_type",
        tuple(entity_params),
    )
    ids = [str(e["id"]) for e in entities]
    relations = _relations_for_entity_ids(db, ids)
    statements = []
    if ids:
        placeholders = ", ".join(["%s"] * len(ids))
        statements = _query_rows(
            db,
            "SELECT id, statement_text, statement_class, status FROM statement "
            f"WHERE status='active' AND (subject_entity_id IN ({placeholders}) "
            f"OR object_entity_id IN ({placeholders})) LIMIT 200",
            tuple(ids + ids),
        )
    assertions = _query_rows(
        db,
        "SELECT id, statement_text, statement_class, status FROM assertion "
        "WHERE status='active' AND brand_id = %s::uuid "
        + ("AND tenant_id::text = %s " if tenant_id else "")
        + "LIMIT 200",
        (brand_uuid, tenant_id) if tenant_id else (brand_uuid,),
    )
    statements.extend(assertions)
    return write_output(build_graph(entities, relations, statements), out_path)


def export_all(db, out_path=None) -> dict:
    entities = _query_rows(
        db,
        "SELECT id, entity_id, canonical_name, entity_type, status, scope FROM entity ORDER BY entity_type",
    )
    relations = _query_rows(
        db,
        "SELECT id, subject_id, relation_type, object_id, confidence, verification_status "
        "FROM relation WHERE status='active'",
    )
    statements = _query_rows(
        db, "SELECT id, statement_text, statement_class, status FROM statement WHERE status='active' LIMIT 500"
    )
    return write_output(build_graph(entities, relations, statements), out_path)


def write_output(graph: dict, out_path=None) -> dict:
    path = Path(out_path) if out_path else Path(__file__).resolve().parent / "output" / "knowledge_graph.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[export] wrote {path} ({graph['stats']})")
    return graph


def main() -> int:
    parser = argparse.ArgumentParser(description="Export PG knowledge graph to JSON for Jupyter.")
    parser.add_argument("--out", default=None, help="output JSON path (default runtime/visualize/output/knowledge_graph.json)")
    parser.add_argument("--industry", default=None, help="filter to an industry tree")
    parser.add_argument("--brand", default=None, help="filter to a brand id")
    parser.add_argument("--tenant", default=None, help="tenant id for brand export")
    parser.add_argument("--all", dest="all_", action="store_true", help="export everything")
    args = parser.parse_args()

    from runtime.db import DB

    with DB() as db:
        if args.brand:
            export_brand(db, args.brand, args.tenant, args.out)
        elif args.industry:
            export_industry(db, args.industry, args.out)
        else:
            export_all(db, args.out)
    print("[export] done — open the notebook to visualize")
    return 0


if __name__ == "__main__":
    sys.exit(main())
