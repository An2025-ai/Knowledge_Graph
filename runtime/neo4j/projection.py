"""PostgreSQL → Neo4j projection service.

PostgreSQL is the single source of truth; Neo4j is a rebuildable query projection.
Reads from the `graph_outbox` event queue (or a full snapshot) and idempotently
MERGEs nodes/relationships into Neo4j.

Usage:
    python -m runtime.neo4j.projection --init            # apply cypher_init.cypher
    python -m runtime.neo4j.projection --full            # full resync from PG
    python -m runtime.neo4j.projection --process-outbox  # incremental from outbox
    python -m runtime.neo4j.projection --check           # connectivity check
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from neo4j import GraphDatabase

    HAS_NEO4J = True
except ImportError:  # pragma: no cover
    GraphDatabase = None
    HAS_NEO4J = False


NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j_admin_password")
CYPHER_INIT = Path(__file__).resolve().parent / "cypher_init.cypher"

# L1 白名单：实体类型 → Neo4j label 后缀
ENTITY_LABEL_MAP = {
    "industry": "Industry",
    "category": "Category",
    "audience": "Audience",
    "problem": "Problem",
    "use_case": "UseCase",
    "capability": "Capability",
    "decision_factor": "DecisionFactor",
    "topic": "Topic",
    "brand": "Brand",
    "product": "Product",
    "organization": "Organization",
    "product_version": "ProductVersion",
}

# L1 白名单：关系类型 → Neo4j 关系类型
RELATION_LABEL_MAP = {
    "belongs_to": "BELONGS_TO",
    "operates_in": "OPERATES_IN",
    "serves": "SERVES",
    "has_problem": "HAS_PROBLEM",
    "solves": "SOLVES",
    "has_capability": "HAS_CAPABILITY",
    "supports_use_case": "SUPPORTS_USE_CASE",
    "has_decision_factor": "HAS_DECISION_FACTOR",
    "competes_with": "COMPETES_WITH",
    "covers": "COVERS",
    "offers": "OFFERS",
    "owns_brand": "OWNS_BRAND",
    "version_of": "VERSION_OF",
    "supersedes": "SUPERSEDES",
    "targets": "TARGETS",
    "has_topic": "HAS_TOPIC",
    "mentions": "MENTIONS",
    "expresses_intent": "EXPRESSES_INTENT",
    "cites": "CITES",
    "supports": "SUPPORTS",
    "contradicts": "CONTRADICTS",
    "derived_from": "DERIVED_FROM",
    "recommended_for": "RECOMMENDED_FOR",
    "has_content_gap": "HAS_CONTENT_GAP",
    "alternative_to": "ALTERNATIVE_TO",
    "partner_of": "PARTNER_OF",
    "has_decision_factor": "HAS_DECISION_FACTOR",
    "capability_supports_use_case": "CAPABILITY_SUPPORTS_USE_CASE",
    "requires_capability": "REQUIRES_CAPABILITY",
    "performs": "PERFORMS",
    "produces_outcome": "PRODUCES_OUTCOME",
    "achieves_outcome": "ACHIEVES_OUTCOME",
}


class ProjectionService:
    def __init__(self, uri=None, user=None, password=None):
        if not HAS_NEO4J:
            raise RuntimeError("neo4j driver not installed. Run: pip install neo4j")
        self.driver = GraphDatabase.driver(
            uri or NEO4J_URI, auth=(user or NEO4J_USER, password or NEO4J_PASSWORD)
        )

    def close(self):
        if self.driver:
            self.driver.close()

    def check(self) -> bool:
        try:
            with self.driver.session() as session:
                session.run("RETURN 1").consume()
            return True
        except Exception as e:
            print(f"[neo4j] connection failed: {e}")
            return False

    def run(self, cypher: str, params: dict | None = None):
        with self.driver.session() as session:
            session.run(cypher, params or {}).consume()

    def init_schema(self):
        if not CYPHER_INIT.exists():
            raise FileNotFoundError(f"cypher_init.cypher not found: {CYPHER_INIT}")
        cypher = "\n".join(
            line for line in CYPHER_INIT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("//")
        )
        statements = [s.strip() for s in cypher.split(";") if s.strip()]
        for stmt in statements:
            self.run(stmt)
        print("[neo4j] schema initialized")

    # ------------------------------------------------------------------
    # Entity projection
    # ------------------------------------------------------------------
    def merge_entity(self, entity_id, entity_type, canonical_name, tenant_id=None, scope=None, status=None):
        labels = "Entity"
        if entity_type in ENTITY_LABEL_MAP:
            labels += ":" + ENTITY_LABEL_MAP[entity_type]
        self.run(
            f"MERGE (n:{labels} {{id: $id}}) "
            f"SET n.entity_type = $type, n.canonical_name = $name, "
            f"n.tenant_id = $tenant, n.scope = $scope, n.status = $status",
            {"id": str(entity_id), "type": entity_type, "name": canonical_name,
             "tenant": tenant_id and str(tenant_id), "scope": scope, "status": status},
        )

    def merge_relation(self, relation_id, subject_id, relation_type, object_id,
                       tenant_id=None, confidence=None, verification_status=None):
        rel = RELATION_LABEL_MAP.get(relation_type, relation_type.upper())
        self.run(
            f"MATCH (a:Entity {{id: $sid}}), (b:Entity {{id: $oid}}) "
            f"MERGE (a)-[r:{rel} {{id: $rid}}]->(b) "
            f"SET r.relation_type = $rtype, r.tenant_id = $tenant, "
            f"r.confidence = $confidence, r.verification_status = $verification",
            {"rid": str(relation_id), "sid": str(subject_id), "oid": str(object_id),
             "rtype": relation_type, "tenant": tenant_id and str(tenant_id),
             "confidence": float(confidence) if confidence is not None else None,
             "verification": verification_status},
        )

    def merge_assertion(self, assertion_id, subject_id, object_id, predicate,
                        statement_text, statement_class, tenant_id=None, access_level=None,
                        source_table="statement"):
        self.run(
            "MERGE (n:Assertion {id: $id}) "
            "SET n.predicate = $predicate, n.statement_text = $text, "
            "n.statement_class = $cls, n.tenant_id = $tenant, n.access_level = $access, "
            "n.source_table = $source_table",
            {"id": str(assertion_id), "predicate": predicate, "text": statement_text,
             "cls": statement_class, "tenant": tenant_id and str(tenant_id),
             "access": access_level, "source_table": source_table},
        )
        # SUBJECT / OBJECT links
        if subject_id:
            self.run(
                "MATCH (a:Assertion {id: $aid}), (e:Entity {id: $eid}) "
                "MERGE (a)-[:SUBJECT]->(e)",
                {"aid": str(assertion_id), "eid": str(subject_id)},
            )
        if object_id:
            self.run(
                "MATCH (a:Assertion {id: $aid}), (e:Entity {id: $eid}) "
                "MERGE (a)-[:OBJECT]->(e)",
                {"aid": str(assertion_id), "eid": str(object_id)},
            )

    def merge_evidence(self, evidence_id, source_id=None, quote=None):
        self.run(
            "MERGE (n:Evidence {id: $id}) SET n.quote = $quote",
            {"id": str(evidence_id), "quote": quote},
        )
        if source_id:
            self.run(
                "MATCH (e:Evidence {id: $eid}), (s:Source {id: $sid}) "
                "MERGE (e)-[:FROM_SOURCE]->(s)",
                {"eid": str(evidence_id), "sid": str(source_id)},
            )

    def merge_source(self, source_id, title=None, url=None):
        self.run(
            "MERGE (n:Source {id: $id}) SET n.title = $title, n.url = $url",
            {"id": str(source_id), "title": title, "url": url},
        )

    def merge_report(self, report_id, title=None):
        self.run(
            "MERGE (n:Report {id: $id}) SET n.title = $title",
            {"id": str(report_id), "title": title},
        )

    def delete_aggregate(self, aggregate_type, aggregate_id):
        labels = {
            "entity": "Entity",
            "statement": "Assertion",
            "assertion": "Assertion",
            "evidence": "Evidence",
            "source": "Source",
            "report": "Report",
        }
        if aggregate_type == "relation":
            self.run("MATCH ()-[r {id: $id}]->() DELETE r", {"id": str(aggregate_id)})
            return
        label = labels.get(aggregate_type)
        if label:
            self.run(
                f"MATCH (n:{label} {{id: $id}}) DETACH DELETE n",
                {"id": str(aggregate_id)},
            )


def full_resync(pg_db, proj: ProjectionService):
    """Full rebuild from PostgreSQL (entity + relation + statement/assertion)."""
    proj.run(
        "MATCH (n) WHERE any(label IN labels(n) WHERE label IN "
        "['Entity','Assertion','Evidence','Source','Report','Content','Conflict']) "
        "DETACH DELETE n"
    )
    print("[projection] cleared previous projection")
    entities = pg_db.query(
        "SELECT id, entity_type, canonical_name, tenant_id, scope, status FROM entity WHERE status='active'"
    )
    for e in entities:
        proj.merge_entity(e["id"], e["entity_type"], e["canonical_name"],
                          e.get("tenant_id"), e.get("scope"), e.get("status"))
    print(f"[projection] merged {len(entities)} entities")

    relations = pg_db.query(
        "SELECT id, subject_id, relation_type, object_id, tenant_id, confidence, verification_status "
        "FROM relation WHERE status='active'"
    )
    for r in relations:
        proj.merge_relation(r["id"], r["subject_id"], r["relation_type"], r["object_id"],
                            r.get("tenant_id"), r.get("confidence"), r.get("verification_status"))
    print(f"[projection] merged {len(relations)} relations")

    statements = pg_db.query(
        "SELECT id, subject_entity_id, object_entity_id, predicate, statement_text, "
        "statement_class, tenant_id, access_level FROM statement WHERE status='active'"
    )
    for s in statements:
        proj.merge_assertion(s["id"], s.get("subject_entity_id"), s.get("object_entity_id"),
                             s.get("predicate"), s.get("statement_text"),
                             s.get("statement_class"), s.get("tenant_id"), s.get("access_level"),
                             source_table="statement")

    brand_assertions = pg_db.query(
        "SELECT id, subject_id, object_entity_id, predicate, statement_text, "
        "statement_class, tenant_id, access_level FROM assertion WHERE status='active'"
    )
    for a in brand_assertions:
        proj.merge_assertion(a["id"], a.get("subject_id"), a.get("object_entity_id"),
                             a.get("predicate"), a.get("statement_text"),
                             a.get("statement_class"), a.get("tenant_id"), a.get("access_level"),
                             source_table="assertion")
    print(f"[projection] merged {len(statements) + len(brand_assertions)} assertions")


def process_outbox(pg_db, proj: ProjectionService, limit: int = 100):
    """Incremental sync from graph_outbox events."""
    events = pg_db.query(
        "SELECT id, aggregate_type, aggregate_id, event_type, payload FROM graph_outbox "
        "WHERE processed_at IS NULL ORDER BY created_at LIMIT %s",
        (limit,),
    )
    for ev in events:
        agg_type = ev["aggregate_type"]
        agg_id = ev["aggregate_id"]
        payload = ev.get("payload") or {}
        try:
            if ev.get("event_type") == "delete":
                proj.delete_aggregate(agg_type, agg_id)
            elif agg_type == "entity":
                proj.merge_entity(agg_id, payload.get("entity_type"), payload.get("canonical_name"),
                                  payload.get("tenant_id"), payload.get("scope"), payload.get("status"))
            elif agg_type == "relation":
                proj.merge_relation(agg_id, payload.get("subject_id"), payload.get("relation_type"),
                                    payload.get("object_id"), payload.get("tenant_id"),
                                    payload.get("confidence"), payload.get("verification_status"))
            elif agg_type == "statement":
                proj.merge_assertion(agg_id, payload.get("subject_entity_id"), payload.get("object_entity_id"),
                                     payload.get("predicate"), payload.get("statement_text"),
                                     payload.get("statement_class"), payload.get("tenant_id"),
                                     payload.get("access_level"), source_table="statement")
            elif agg_type == "assertion":
                proj.merge_assertion(agg_id, payload.get("subject_id"), payload.get("object_entity_id"),
                                     payload.get("predicate"), payload.get("statement_text"),
                                     payload.get("statement_class"), payload.get("tenant_id"),
                                     payload.get("access_level"), source_table="assertion")
            elif agg_type == "evidence":
                proj.merge_evidence(agg_id, payload.get("source_id"), payload.get("quote"))
            elif agg_type == "source":
                proj.merge_source(agg_id, payload.get("title"), payload.get("url"))
            elif agg_type == "report":
                proj.merge_report(agg_id, payload.get("title"))
            else:
                continue
            pg_db.execute("UPDATE graph_outbox SET processed_at = NOW() WHERE id = %s", (ev["id"],))
        except Exception as e:
            pg_db.execute(
                "UPDATE graph_outbox SET retry_count = retry_count + 1, error = %s WHERE id = %s",
                (str(e)[:500], ev["id"]),
            )
    print(f"[projection] processed {len(events)} outbox events")


def main() -> int:
    parser = argparse.ArgumentParser(description="PG → Neo4j projection service")
    parser.add_argument("--init", action="store_true", help="apply cypher_init.cypher")
    parser.add_argument("--full", action="store_true", help="full resync from PG")
    parser.add_argument("--process-outbox", action="store_true", help="incremental outbox sync")
    parser.add_argument("--check", action="store_true", help="connectivity check")
    args = parser.parse_args()

    if not HAS_NEO4J:
        print("[neo4j] neo4j driver not installed. Run: pip install -r runtime/requirements.txt")
        return 1

    proj = ProjectionService()
    try:
        if args.check:
            connected = proj.check()
            print("[neo4j] OK" if connected else "[neo4j] FAILED")
            return 0 if connected else 1
        if args.init:
            proj.init_schema()
        if args.full or args.process_outbox:
            from runtime.db import DB

            with DB() as pg_db:
                if args.full:
                    full_resync(pg_db, proj)
                if args.process_outbox:
                    process_outbox(pg_db, proj)
        print("[projection] done")
        return 0
    finally:
        proj.close()


if __name__ == "__main__":
    sys.exit(main())
