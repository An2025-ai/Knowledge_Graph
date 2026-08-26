"""PostgreSQL ↔ Neo4j consistency check.

Usage:
    python -m engine.neo4j.consistency        # full counts comparison + orphan check
    python -m engine.neo4j.consistency --sample 5  # plus sample assertion spot-check
"""
from __future__ import annotations

import argparse
import sys

from engine.neo4j.projection import ProjectionService


def count_entities_pg(conn):
    return conn.query("SELECT count(*) AS c FROM entity WHERE status='active'")[0]["c"]


def count_relations_pg(conn):
    return conn.query("SELECT count(*) AS c FROM relation WHERE status='active'")[0]["c"]


def count_assertions_pg(conn):
    return conn.query(
        "SELECT (SELECT count(*) FROM statement WHERE status='active') + "
        "(SELECT count(*) FROM assertion WHERE status='active') AS c"
    )[0]["c"]


def count_entity_edges(proj):
    return proj.driver.execute_query(
        "MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c"
    ).records[0]["c"]


def count_label(proj, label):
    try:
        result = proj.driver.execute_query(f"MATCH (n:{label}) RETURN count(n) AS c").records[0]
        return result["c"]
    except Exception as e:  # pragma: no cover
        return f"error: {e}"


def orphan_entities(proj):
    """Entities not connected to any relation (potential orphan)."""
    result = proj.driver.execute_query(
        "MATCH (n:Entity) WHERE NOT (n)--() RETURN count(n) AS c"
    ).records[0]
    return result["c"]


def main() -> int:
    parser = argparse.ArgumentParser(description="PG ↔ Neo4j consistency")
    parser.add_argument("--sample", type=int, default=0, help="sample N assertions to spot-check")
    parser.add_argument("--counts-only", action="store_true", help="only compare counts")
    args = parser.parse_args()

    from engine.core.db import DB
    from engine.neo4j import projection

    if not projection.HAS_NEO4J:
        print("[consistency] neo4j driver not installed")
        return 1

    proj = ProjectionService()
    try:
        with DB() as pg_db:
            pe = count_entities_pg(pg_db)
            pr = count_relations_pg(pg_db)
            pa = count_assertions_pg(pg_db)
        ne = count_label(proj, "Entity")
        nr = count_entity_edges(proj)
        na = count_label(proj, "Assertion")
        orphan = orphan_entities(proj)

        print(f"{'':18} PG    Neo4j")
        print(f"{'entities':18} {pe:5} {ne}")
        print(f"{'relations':18} {pr:5} {nr}")
        print(f"{'assertions':18} {pa:5} {na}")
        print(f"{'orphan entities':18} {'—':5} {orphan}")

        ok = True
        # Counts comparison applies in both modes.
        counts_match = (pe == ne) and (pr == nr) and (pa == na)
        if counts_match:
            print("\n[consistency] counts match (PG == Neo4j)")
        else:
            print("\n[consistency] MISMATCH — counts differ between PG and Neo4j")
            ok = False

        # Optional sample spot-check (only when not counts-only).
        if not args.counts_only and counts_match and args.sample:
            with DB() as pg_db:
                rows = pg_db.query(
                    "SELECT id FROM ("
                    " SELECT id FROM statement WHERE status='active' "
                    " UNION ALL SELECT id FROM assertion WHERE status='active'"
                    ") projected_assertion LIMIT %s", (args.sample,),
                )
            if rows:
                missing = 0
                for r in rows:
                    found = proj.driver.execute_query(
                        "MATCH (n:Assertion {id: $id}) RETURN count(n) AS c",
                        {"id": str(r["id"])},
                    ).records[0]["c"]
                    if not found:
                        missing += 1
                print(f"\nsample check: {len(rows)} sampled, {missing} missing in Neo4j")
                if missing:
                    ok = False

        print("[consistency] OK" if ok else "[consistency] INCONSISTENT")
        return 0 if ok else 1
    finally:
        proj.close()


if __name__ == "__main__":
    sys.exit(main())
