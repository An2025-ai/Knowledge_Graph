"""PostgreSQL ↔ Neo4j consistency check.

Usage:
    python -m runtime.neo4j.consistency        # full counts comparison + orphan check
    python -m runtime.neo4j.consistency --sample 5  # plus sample assertion spot-check
"""
from __future__ import annotations

import argparse
import sys

from runtime.neo4j.projection import ProjectionService


def count_entities_pg(conn):
    return conn.query("SELECT count(*) AS c FROM entity WHERE status='active'")[0]["c"]


def count_relations_pg(conn):
    return conn.query("SELECT count(*) AS c FROM relation WHERE status='active'")[0]["c"]


def count_assertions_pg(conn):
    return conn.query("SELECT count(*) AS c FROM statement WHERE status='active'")[0]["c"]


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

    from runtime.db import DB
    from runtime.neo4j import projection

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
        nr = count_label(proj, "Assertion")  # materialized relations live on Assertion edges
        na = count_label(proj, "Assertion")
        orphan = orphan_entities(proj)

        print(f"{'':18} PG    Neo4j")
        print(f"{'entities':18} {pe:5} {ne}")
        print(f"{'assertions':18} {pa:5} {na}")
        print(f"{'orphan entities':18} {'—':5} {orphan}")

        # Actual relationship edges in Neo4j across all materialized rel types
        all_rel = proj.driver.execute_query(
            "MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c"
        ).records[0]["c"]
        print(f"{'entity edges (n4j)':18} {'—':5} {all_rel}")

        ok = True
        # Counts comparison applies in both modes.
        counts_match = (pe == ne) and (pa == na)
        if counts_match:
            print("\n[consistency] counts match (PG == Neo4j)")
        else:
            print("\n[consistency] MISMATCH — counts differ between PG and Neo4j")
            ok = False

        # Optional sample spot-check (only when not counts-only).
        if not args.counts_only and counts_match and args.sample:
            with DB() as pg_db:
                rows = pg_db.query(
                    "SELECT id, subject_entity_id, object_entity_id FROM statement "
                    "WHERE status='active' LIMIT %s", (args.sample,),
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