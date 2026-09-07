"""Knowledge graph construction metrics (OPTIMIZATION_TECH_PLAN.md §7/Phase 6).

Computes pipeline health metrics from PostgreSQL:
  - LLM call cost / doc (requires an llm_call log; falls back to extraction_run)
  - extraction acceptance rate
  - entity duplicate / merge rate
  - evidence verification outcome distribution

Usage:
    python -m legacy.core.metrics [--db-check] [--json]
"""
from __future__ import annotations

import json
import sys
from typing import Any

from legacy.core.db import DB


def compute_metrics(db: DB) -> dict[str, Any]:
    m: dict[str, Any] = {}

    # --- Document counts ---
    docs = db.query("SELECT count(*) AS c FROM document")[0]["c"]
    units = db.query("SELECT count(*) AS c FROM evidence_units")[0]["c"]
    spans = db.query("SELECT count(*) AS c FROM evidence_spans")[0]["c"]
    m["documents"] = docs
    m["evidence_spans"] = spans
    m["evidence_units"] = units

    # --- Extraction / candidates ---
    cand = db.query("SELECT count(*) AS c FROM knowledge_candidates")[0]["c"]
    cand_by_type = db.query(
        "SELECT candidate_type, count(*) AS c FROM knowledge_candidates "
        "GROUP BY candidate_type"
    )
    m["extraction_candidates"] = cand
    m["extraction_candidates_by_type"] = {r["candidate_type"]: r["c"] for r in cand_by_type}

    # --- Gate candidates (fusion output）---
    gate_k = db.query("SELECT count(*) AS c FROM gate_candidate_knowledge")[0]["c"]
    gate_e = db.query("SELECT count(*) AS c FROM gate_candidate_entities")[0]["c"]
    m["gate_candidate_entities"] = gate_e
    m["gate_candidate_knowledge"] = gate_k

    # --- Entity counts & dedup effectiveness ---
    entities = db.query("SELECT count(*) AS c FROM entity WHERE status='active'")[0]["c"]
    dups = db.query("SELECT count(*) AS c FROM entity WHERE status='deprecated'")[0]["c"]
    m["active_entities"] = entities
    m["deprecated_entities"] = dups
    m["entity_duplicate_rate"] = round(dups / (dups + entities + 1e-9), 4) if (dups + entities) else 0.0

    # --- Relations / assertions ---
    relations = db.query("SELECT count(*) AS c FROM relation WHERE status='active'")[0]["c"]
    assertions = db.query("SELECT count(*) AS c FROM assertion")[0]["c"]
    m["active_relations"] = relations
    m["assertions"] = assertions

    # --- Evidence verification outcomes ---
    verif = db.query(
        "SELECT support_status, count(*) AS c FROM assertion_evidence GROUP BY support_status"
    )
    m["evidence_verification"] = {r["support_status"]: r["c"] for r in verif}

    # --- Review queue ---
    review = db.query("SELECT count(*) AS c FROM review_queue WHERE status='pending'")[0]["c"]
    m["pending_review_items"] = review

    # --- Review / promotion outcomes ---
    promoted = db.query("SELECT count(*) AS c FROM assertion WHERE status='active'")[0]["c"]
    m["promoted_assertions"] = promoted

    # --- Embeddings coverage ---
    emb = db.query("SELECT count(*) AS c FROM entity_embedding")[0]["c"]
    cand_emb = db.query("SELECT count(*) AS c FROM candidate_embedding")[0]["c"]
    m["entity_embeddings"] = emb
    m["candidate_embeddings"] = cand_emb

    return m


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="KG construction metrics")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--db-check", action="store_true", help="Check DB connectivity first")
    args = parser.parse_args()

    from legacy.core.db import check_connection

    if args.db_check and not check_connection():
        print("PostgreSQL unreachable", file=sys.stderr)
        return 1

    with DB() as db:
        m = compute_metrics(db)

    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2, default=str))
    else:
        print("Brand Atlas KG — construction metrics")
        print(f"  documents: {m['documents']}, evidence_spans: {m['evidence_spans']}, "
              f"evidence_units: {m['evidence_units']}")
        print(f"  knowledge candidates: {m['extraction_candidates']} "
              f"(by type: {m['extraction_candidates_by_type']})")
        print(f"  gate candidates: entities={m['gate_candidate_entities']}, "
              f"knowledge={m['gate_candidate_knowledge']}")
        print(f"  active entities: {m['active_entities']}, deprecated: {m['deprecated_entities']} "
              f"(dup rate {m['entity_duplicate_rate']})")
        print(f"  active relations: {m['active_relations']}, assertions: {m['assertions']} "
              f"(promoted: {m['promoted_assertions']})")
        print(f"  evidence verification: {m['evidence_verification']}")
        print(f"  entity embeddings: {m['entity_embeddings']}, "
              f"candidate embeddings: {m['candidate_embeddings']}, "
              f"pending review: {m['pending_review_items']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())