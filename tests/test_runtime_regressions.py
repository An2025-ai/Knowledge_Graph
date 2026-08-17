from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date

from runtime.db import DB, json_dumps
from runtime.l2.executor import _propagate_result
from runtime.l2.pipelines.geo_research_report_job import _build_research_package
from runtime.l2.pipelines.source_discovery import discover_sources
from runtime.l2.search.providers import SearchResult
from runtime.l2.pipelines.extraction import _upsert_entity
from runtime.l2.pipelines.promotion import _disposition, _evaluate_gates
from runtime.l3.pipelines.candidate_pre_extraction import (
    _ner_type_to_candidate,
    _ner_entities,
    pre_extract,
)
from runtime.l3.pipelines._helpers import resolve_brand_context, update_assertion
from runtime.ner_client import _clean_span, _map_ner_type, _SCHEMA_ZH
from runtime.l3.pipelines.l2_mapping import _find_l2_capability
from runtime.migrations.__main__ import main as migration_main
from runtime.neo4j.consistency import count_assertions_pg, count_entity_edges
from runtime.neo4j.projection import ProjectionService
from runtime.l3.executor import DEFAULT_PIPELINES
from runtime.visualize.export import _relations_for_entity_ids, export_all, export_layer


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

    def test_executor_propagates_research_package_outputs(self):
        args = argparse.Namespace(source_list=None, research_package=None, evidence=None)
        _propagate_result(
            "geo_research_report_job",
            {
                "source_list": "sources.json",
                "research_package": "package",
                "evidence_path": "package/evidence_index.json",
            },
            args,
        )
        self.assertEqual(args.source_list, "sources.json")
        self.assertEqual(args.research_package, "package")
        self.assertEqual(args.evidence, "package/evidence_index.json")

    def test_source_discovery_offline_builds_candidate_list(self):
        payload = discover_sources(
            "CRM软件",
            "CN",
            [{"dimension_code": "capabilities", "expected_fields": ["capability_name"]}],
            ["中国信通院"],
            max_results_per_query=1,
            use_provider=False,
        )
        self.assertEqual(payload["stats"]["dimensions"], 1)
        self.assertGreaterEqual(payload["stats"]["sources"], 1)
        self.assertIn("query_plan", payload)
        self.assertEqual(payload["sources"][0]["approval_status"], "pending")

    def test_source_discovery_prefers_trusted_dimension_sources(self):
        results = [
            SearchResult(
                title="Vendor blog",
                url="https://random-vendor.example/blog/crm",
                snippet="CRM marketing page",
                rank=1,
            ),
            SearchResult(
                title="CAICT CRM capability report",
                url="https://www.caict.ac.cn/report/crm-capability",
                snippet="CRM capability function module research report",
                rank=2,
            ),
        ]
        with patch("runtime.l2.pipelines.source_discovery.provider_status", return_value={"provider": "searxng", "searxng_available": True}), \
                patch("runtime.l2.pipelines.source_discovery.search", return_value=results):
            payload = discover_sources(
                "CRM",
                "CN",
                [{"dimension_code": "capabilities", "expected_fields": ["capability_name"]}],
                [],
                max_results_per_query=2,
                trusted_domains=["caict.ac.cn"],
                max_sources_per_dimension=1,
                strict_authority=True,
            )
        self.assertEqual(payload["stats"]["sources"], 1)
        self.assertIn("caict.ac.cn", payload["sources"][0]["url"])
        self.assertEqual(payload["sources"][0]["accepted_for_research"], True)
        self.assertGreater(payload["sources"][0]["authority_score"], 0.8)

    def test_research_package_skips_rejected_source_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_list = Path(tmp) / "sources.json"
            package_dir = Path(tmp) / "package"
            source_list.write_text(json.dumps({
                "industry": "CRM",
                "market": "CN",
                "sources": [
                    {
                        "source_id": "src_ok",
                        "title": "Accepted Source",
                        "url": "https://www.caict.ac.cn/report/crm",
                        "snippet": "CRM capability report",
                        "source_class": "industry_research",
                        "source_type": "web",
                        "dimension_codes": ["capabilities"],
                        "accepted_for_research": True,
                    },
                    {
                        "source_id": "src_bad",
                        "title": "Rejected Source",
                        "url": "https://random-vendor.example/blog",
                        "snippet": "Generic blog",
                        "source_class": "reliable_media",
                        "source_type": "web",
                        "dimension_codes": ["capabilities"],
                        "accepted_for_research": False,
                    },
                ],
            }, ensure_ascii=False), encoding="utf-8")
            built = _build_research_package(str(source_list), str(package_dir), fetch=False)
            self.assertEqual(built["manifest"]["stats"]["sources"], 1)
            evidence = json.loads((package_dir / "evidence_index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(evidence["sources"]), 1)
            self.assertEqual(evidence["sources"][0]["source_id"], "src_ok")

    def test_research_package_contains_report_and_evidence_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_list = Path(tmp) / "sources.json"
            package_dir = Path(tmp) / "package"
            source_list.write_text(json.dumps({
                "industry": "CRM软件",
                "market": "CN",
                "sources": [{
                    "source_id": "src_demo",
                    "title": "Demo Source",
                    "url": "https://www.google.com/search?q=crm",
                    "snippet": "CRM software capability evidence",
                    "source_class": "industry_research",
                    "source_type": "web",
                    "dimension_codes": ["capabilities"],
                }],
            }, ensure_ascii=False), encoding="utf-8")
            built = _build_research_package(str(source_list), str(package_dir), fetch=False)
            self.assertTrue((package_dir / "manifest.json").exists())
            self.assertTrue((package_dir / "report.md").exists())
            self.assertTrue((package_dir / "evidence_index.json").exists())
            self.assertTrue((package_dir / "coverage_ledger.json").exists())
            self.assertEqual(built["manifest"]["stats"]["evidence"], 1)

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
        self.assertIn("tenant_id IS NULL", sql)
        self.assertNotIn("tenant_id = %s", sql)
        self.assertIn("owner_brand IS NULL", sql)
        self.assertNotIn("COALESCE(owner_brand, '')", sql)
        self.assertEqual(db.queries[0][1], ("capability", "Analytics"))

    def test_induced_subgraph_requires_both_relation_endpoints(self):
        db = RecordingDB(query_results=[[]])
        _relations_for_entity_ids(db, ["a", "b"])
        sql, params = db.queries[0]
        self.assertIn("subject_id IN", sql)
        self.assertIn("object_id IN", sql)
        self.assertIn(" AND object_id", sql)
        self.assertEqual(params, ("a", "b", "a", "b"))

    def test_l3_default_all_pipeline_excludes_l2_mapping(self):
        self.assertNotIn("l2_mapping", DEFAULT_PIPELINES)

    def test_export_all_does_not_include_mappings_by_default(self):
        db = RecordingDB(query_results=[[], [], [], []])
        with patch("runtime.visualize.export.write_output", side_effect=lambda graph, out_path=None: graph):
            export_all(db, out_path=None)
        sql = " ".join(query[0] for query in db.queries)
        self.assertNotIn("FROM brand_mapping", sql)

    def test_export_all_can_include_mappings_explicitly(self):
        db = RecordingDB(query_results=[[], [], [], [], []])
        with patch("runtime.visualize.export.write_output", side_effect=lambda graph, out_path=None: graph):
            export_all(db, out_path=None, include_mappings=True)
        sql = " ".join(query[0] for query in db.queries)
        self.assertIn("FROM brand_mapping", sql)

    def test_export_layer_l1_reads_registry_tables(self):
        db = RecordingDB(query_results=[
            [{"id": "brand", "entity_id": "brand", "canonical_name": "Brand",
              "entity_type": "entity_type", "status": "active", "scope": "definition"}],
            [{"id": "offers", "entity_id": "offers", "canonical_name": "offers",
              "entity_type": "relation_type", "status": "active", "scope": "definition"}],
        ])
        with patch("runtime.visualize.export.write_output", side_effect=lambda graph, out_path=None: graph):
            graph = export_layer(db, "L1", out_path=None)
        self.assertEqual(graph["stats"]["nodes"], 2)
        self.assertTrue(all(node["layer"] == "L1" for node in graph["nodes"]))

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

    # --- PaddleNLP NER candidate layer ---

    def test_ner_type_mapping_whitelists_and_drops(self):
        self.assertEqual(_ner_type_to_candidate("organization"), "organization")
        self.assertEqual(_ner_type_to_candidate("ORG"), "organization")
        self.assertEqual(_ner_type_to_candidate("product_name"), "product")
        self.assertEqual(_ner_type_to_candidate("cert"), "certification")
        # Unknown / non-domain generic labels are dropped (not candidates).
        self.assertIsNone(_ner_type_to_candidate("person"))
        self.assertIsNone(_ner_type_to_candidate("location"))
        self.assertIsNone(_ner_type_to_candidate(""))

    def test_pre_extract_without_ner_client_is_unchanged(self):
        # No ner_client -> no paddlenlp generator candidates appear.
        text = "DeepCleer 支持自动对账，获得 ISO 27001 认证。"
        candidates = pre_extract(text)
        self.assertTrue(candidates)
        self.assertFalse([c for c in candidates if c["generator"].startswith("paddlenlp:")])

    def test_ner_layer_builds_candidates_and_ids_generator(self):
        class FakeNER:
            def named_entities(self, text):
                return [
                    {"type": "organization", "text": "上海智云图科技有限公司", "score": 0.95},
                    {"type": "capability", "text": "自动对账", "score": 0.85},
                    {"type": "person", "text": "张三", "score": 0.9},  # dropped by mapping
                ]

        candidates = _ner_entities("sample", FakeNER())
        ners = [c for c in candidates if c["generator"].startswith("paddlenlp:")]
        self.assertEqual(len(ners), 2)
        self.assertTrue(all(c["generator"] == "paddlenlp:ner:%s" % c["candidate_type"]
                            for c in ners))
        org = next(c for c in ners if c["candidate_type"] == "organization")
        self.assertEqual(org["candidate_payload"]["name"], "上海智云图科技有限公司")
        self.assertEqual(org["confidence"], 0.95)
        # A dropped label never becomes a candidate.
        self.assertNotIn("person", [c["candidate_type"] for c in ners])

    def test_pre_extract_with_ner_client_appends_ner_candidates(self):
        class FakeNER:
            def named_entities(self, text):
                return [{"type": "product", "text": "AI 业财平台", "score": 0.9}]

        candidates = pre_extract("提供 AI 业财平台，支持自动对账。", ner_client=FakeNER())
        ners = [c for c in candidates if c["generator"].startswith("paddlenlp:")]
        self.assertTrue(ners)
        self.assertEqual(ners[0]["candidate_payload"]["name"], "AI 业财平台")

    def test_ner_entity_error_degrades_to_empty(self):
        class BrokenNER:
            def named_entities(self, text):
                raise RuntimeError("model init failed")

        # Optional layer must not raise into the caller.
        self.assertEqual(_ner_entities("any text", BrokenNER()), [])

    def test_ner_chinese_schema_label_mapping(self):
        # UIE needs Chinese schema labels for Chinese text; the config keeps
        # English candidate_type, and labels translate both ways.
        self.assertEqual(_SCHEMA_ZH["organization"], "公司")
        self.assertEqual(_SCHEMA_ZH["certification"], "认证")
        # UIE Chinese output labels map back to English candidate_type.
        self.assertEqual(_map_ner_type("公司"), "organization")
        self.assertEqual(_map_ner_type("产品"), "product")
        self.assertEqual(_map_ner_type("能力"), "capability")

    def test_ner_span_cleaning_trims_dangling_brackets(self):
        # UIE sometimes leaves an unclosed opening bracket at a span boundary.
        self.assertEqual(_clean_span("DeepCleer 深澈智算（上海智云图科技有限公司"),
                         "DeepCleer 深澈智算（上海智云图科技有限公司")
        self.assertEqual(_clean_span("（智能风控大脑）"), "（智能风控大脑）")
        self.assertEqual(_clean_span("「智能风控大脑"), "智能风控大脑")
        self.assertEqual(_clean_span("  X  "), "X")
        self.assertEqual(_clean_span(""), "")

    def test_ner_dry_run_does_not_insert(self):
        db = RecordingDB(query_routes={
            "FROM tenant": [],                       # tenant lookup empty
            "FROM entity": [],                       # brand lookup empty
            "FROM document WHERE document_id": [{"id": "doc-uuid"}],
            "FROM document_chunk": [{"id": "chunk-1", "chunk_index": 0,
                                     "text": "提供 AI 业财平台。"}],
        })

        class FakeNER:
            def named_entities(self, text):
                return [{"type": "product", "text": "AI 业财平台", "score": 0.9}]

        args = argparse.Namespace(brand="Acme", tenant="demo", document_id="doc_x",
                                  dry_run=True, skip_ner=False)
        import runtime.l3.pipelines.candidate_pre_extraction as cpe
        with patch.object(cpe, "get_ner_client", lambda: FakeNER()):
            result = cpe.run(db, args)
        # dry-run: counts candidates but writes nothing to extraction_candidate.
        self.assertGreater(result["candidate_count"], 0)
        self.assertGreater(result["ner_count"], 0)
        self.assertTrue(result["ner_enabled"])
        self.assertEqual(db.inserts, [])


if __name__ == "__main__":
    unittest.main()
