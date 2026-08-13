from __future__ import annotations

import argparse
import json
import unittest
from unittest.mock import patch
from datetime import date

from runtime.db import DB, json_dumps
from runtime.l2.executor import _propagate_result
from runtime.l2.pipelines.extraction import _upsert_entity
from runtime.l2.pipelines.promotion import _disposition, _evaluate_gates
from runtime.l3.pipelines._helpers import resolve_brand_context, update_assertion
from runtime.l3.pipelines.l2_mapping import _find_l2_capability
from runtime.migrations.__main__ import main as migration_main
from runtime.neo4j.consistency import count_assertions_pg, count_entity_edges
from runtime.neo4j.projection import ProjectionService
from runtime.visualize.export import _relations_for_entity_ids


class RecordingDB:
    def __init__(self, query_results=None, query_routes=None):
        self.query_results = list(query_results or [])
        self.query_routes = query_routes or {}
        self.queries = []
        self.executions = []
        self.inserts = []

    def query(self, sql, params=None):
        self.queries.append((sql, params))
        for needle, result in self.query_routes.items():
            if needle in sql:
                return result
        return self.query_results.pop(0) if self.query_results else []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def insert_returning_id(self, sql, params=None):
        self.inserts.append((sql, params))
        return "inserted-id"


class RuntimeRegressionTests(unittest.TestCase):
    def test_executor_propagates_pipeline_outputs(self):
        args = argparse.Namespace(requirement_id=None, report_id=None, report=None)
        _propagate_result(
            "geo_research_report_job",
            {
                "requirement_id": "ikr_crm",
                "report_id": "grep_1",
                "report_path": "reports/crm.md",
            },
            args,
        )
        self.assertEqual(args.requirement_id, "ikr_crm")
        self.assertEqual(args.report_id, "grep_1")
        self.assertEqual(args.report, "reports/crm.md")

    def test_nested_dates_are_json_serializable(self):
        encoded = json_dumps({"published": [date(2026, 8, 12)]})
        self.assertEqual(json.loads(encoded), {"published": ["2026-08-12"]})

    def test_entity_id_is_stable_across_chunks(self):
        db = RecordingDB()
        existing_ids = set()
        registry = {}
        entity = {"type": "brand", "canonical_name": "Acme"}
        first = _upsert_entity(db, entity, existing_ids, registry, None, "ind_crm", dry_run=True)
        second = _upsert_entity(db, entity, existing_ids, registry, None, "ind_crm", dry_run=True)
        self.assertEqual(first, "ent_brand_acme")
        self.assertEqual(second, first)
        self.assertEqual(existing_ids, {"ent_brand_acme"})

    def test_l3_dry_run_does_not_insert_context_rows(self):
        db = RecordingDB(query_results=[[], []])
        args = argparse.Namespace(brand="Acme", tenant="demo", dry_run=True)
        context = resolve_brand_context(db, args)
        self.assertEqual(context["brand_key"], "Acme")
        self.assertEqual(db.inserts, [])
        self.assertEqual(len(db.executions), 1)
        self.assertIn("SET app.tenant_id", db.executions[0][0])

    def test_candidate_assertion_update_does_not_disable_triggers(self):
        db = RecordingDB()
        update_assertion(db, "assertion-1", status="active")
        sql, params = db.executions[0]
        self.assertIn("status = 'candidate'", sql)
        self.assertNotIn("session_replication_role", sql)
        self.assertEqual(params, ("active", "assertion-1"))

    def test_l2_mapping_uses_uuid_safe_null_predicate(self):
        db = RecordingDB(query_results=[[]])
        _find_l2_capability(db, "tenant-1", "Analytics")
        sql = " ".join(query[0] for query in db.queries)
        self.assertIn("owner_brand IS NULL", sql)
        self.assertNotIn("COALESCE(owner_brand, '')", sql)

    def test_induced_subgraph_requires_both_relation_endpoints(self):
        db = RecordingDB(query_results=[[]])
        _relations_for_entity_ids(db, ["a", "b"])
        sql, params = db.queries[0]
        self.assertIn("subject_id IN", sql)
        self.assertIn("object_id IN", sql)
        self.assertIn(" AND object_id", sql)
        self.assertEqual(params, ("a", "b", "a", "b"))

    def test_zero_confidence_fails_quality_gate(self):
        db = RecordingDB(query_routes={
            "FROM entity e LEFT JOIN entity_type": [{
                "id": "e1", "entity_type": "brand", "industry_id": "ind_crm",
                "registered_type": "brand",
            }],
            "FROM relation r": [],
            "FROM statement": [{
                "id": "s1", "statement_text": "A supported observation",
                "statement_class": "fact", "scope": {"industry_id": "ind_crm"},
            }],
            "FROM citation_resolution": [{
                "evidence_id": "ev1", "support_status": "directly_supports",
                "access_status": "verified", "source_uuid": "src1",
                "source_class": "industry_research", "source_type": "academic",
                "approval_status": "approved", "l2_enabled": True,
                "authority_level": "high", "policy_status": "active",
            }],
            "other.normalized_statement_hash": [],
            "status='promoted' ORDER BY": [],
        })
        candidate = {
            "candidate_uuid": "candidate-1",
            "statement": "A supported observation",
            "candidate_type": "fact",
            "citation_labels": ["1"],
            "confidence": 0,
            "industry_id": "ind_crm",
            "source_requirements": {"allowed_source_classes": ["industry_research"]},
            "normalized_statement_hash": "hash-1",
        }
        results, failed = _evaluate_gates(db, candidate, threshold=0.5)
        self.assertEqual(failed, "gate_10_quality")
        self.assertEqual(results[-1]["detail"], "confidence=0 threshold=0.5")
        self.assertEqual(_disposition(results)[0], "review")

    def test_hard_gate_failure_takes_priority_over_review(self):
        results = [
            {"gate_id": "gate_1_industry_scope", "passed": False,
             "detail": "missing", "action": "reject"},
            {"gate_id": "gate_10_quality", "passed": False,
             "detail": "low", "action": "review"},
        ]
        disposition, decisive = _disposition(results)
        self.assertEqual(disposition, "reject")
        self.assertEqual(decisive["gate_id"], "gate_1_industry_scope")

    def test_transaction_commits_or_rolls_back_and_restores_autocommit(self):
        class Connection:
            def __init__(self):
                self.autocommit = True
                self.commits = 0
                self.rollbacks = 0

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        connection = Connection()
        db = object.__new__(DB)
        db._conn = connection
        db._transaction_depth = 0
        with db.transaction():
            self.assertFalse(connection.autocommit)
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.autocommit)
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with db.transaction():
                raise RuntimeError("boom")
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.autocommit)

    def test_consistency_counts_only_projectable_assertions_and_entity_edges(self):
        pg = RecordingDB(query_results=[[{"c": 4}]])
        self.assertEqual(count_assertions_pg(pg), 4)
        self.assertIn("FROM assertion WHERE status='active'", pg.queries[0][0])

        class Result:
            records = [{"c": 7}]

        class Driver:
            def execute_query(self, query):
                self.query = query
                return Result()

        projection = argparse.Namespace(driver=Driver())
        self.assertEqual(count_entity_edges(projection), 7)
        self.assertIn("(:Entity)-[r]->(:Entity)", projection.driver.query)

    def test_projection_delete_handles_nodes_and_relation_edges(self):
        calls = []
        projection = object.__new__(ProjectionService)
        projection.run = lambda cypher, params=None: calls.append((cypher, params))
        projection.delete_aggregate("entity", "entity-1")
        projection.delete_aggregate("relation", "relation-1")
        self.assertIn("DETACH DELETE n", calls[0][0])
        self.assertIn("DELETE r", calls[1][0])
        self.assertEqual(calls[1][1], {"id": "relation-1"})

    def test_migration_module_entrypoint_is_importable(self):
        with patch("sys.argv", ["runtime.migrations", "--check"]):
            self.assertEqual(migration_main(), 0)


if __name__ == "__main__":
    unittest.main()
