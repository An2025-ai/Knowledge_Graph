from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date

from runtime.core.db import DB, json_dumps
from runtime.industry.executor import _propagate_result, ALL_ORDER as L2_ORDER
from runtime.extraction.candidate_extraction import (
    pre_extract,
    ner_candidates,
    build_candidate_rows,
    _NER_TYPE_MAP,
)
from runtime.brand.pipelines._helpers import resolve_brand_context, update_assertion
from runtime.brand.pipelines.sensitive_content_warning import scan_risks
from runtime.clients.ner_client import _clean_span, _map_ner_type, _SCHEMA_ZH
from runtime.migrations.__main__ import main as migration_main
from runtime.neo4j.consistency import count_assertions_pg, count_entity_edges
from runtime.neo4j.projection import ProjectionService
from runtime.common.prompt_builder import build_extraction_prompt
from runtime.common.policy_engine import load_promotion_policy
from runtime.common.registry import get_common_registry
from runtime.ontology.ontology_validator import validate_ontology
from runtime.brand.executor import DEFAULT_PIPELINES as L3_ORDER
from runtime.promotion.promotion_service import (
    evaluate_instance,
    disposition,
    NEAR_DUPLICATE_THRESHOLD,
)
from runtime.fusion.fusion_service import group_and_emit, resolve_entities, load_candidates
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

    def _json(self, value):
        import json as _json

        return _json.dumps(value, ensure_ascii=False)

    def upsert(self, table, row, key_field="id"):
        self.inserts.append((table, row))

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext()


def _fake_policy():
    return load_promotion_policy("l2_industry", 0.5)


class RuntimeRegressionTests(unittest.TestCase):
    # ------------------------------------------------------------------
    # 新链路协调（executor 传播 + 管道顺序）
    # ------------------------------------------------------------------

    def test_executor_propagates_document_uuid(self):
        args = argparse.Namespace(document_uuid=None, document_id=None)
        _propagate_result(
            "content_parsing",
            {"document_uuid": "uuid-1", "document_id": "doc_crm"},
            args,
        )
        self.assertEqual(args.document_uuid, "uuid-1")
        self.assertEqual(args.document_id, "doc_crm")

    def test_l2_pipeline_order_matches_plan_s11_1(self):
        self.assertEqual(
            L2_ORDER,
            [
                "article_registration",
                "content_parsing",
                "evidence_unit_merge",
                "candidate_extraction",
                "candidate_normalization",
                "candidate_vectorization",
                "knowledge_fusion",
                "promotion",
            ],
        )

    def test_l3_pipeline_has_no_l2_mapping(self):
        self.assertNotIn("l2_mapping", L3_ORDER)
        self.assertEqual(
            L3_ORDER,
            [
                "document_registration",
                "sensitive_content_warning",
                "content_parsing",
                "evidence_unit_merge",
                "candidate_extraction",
                "candidate_normalization",
                "candidate_vectorization",
                "knowledge_fusion",
                "promotion",
            ],
        )

    def test_nested_dates_are_json_serializable(self):
        encoded = json_dumps({"published": [date(2026, 8, 12)]})
        self.assertEqual(json.loads(encoded), {"published": ["2026-08-12"]})

    # ------------------------------------------------------------------
    # L1 契约 / policy / prompt（稳定支撑）
    # ------------------------------------------------------------------

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

    def test_induced_subgraph_requires_both_relation_endpoints(self):
        db = RecordingDB(query_results=[[]])
        _relations_for_entity_ids(db, ["a", "b"])
        sql, params = db.queries[0]
        self.assertIn("subject_id IN", sql)
        self.assertIn("object_id IN", sql)
        self.assertIn(" AND object_id", sql)
        self.assertEqual(params, ("a", "b", "a", "b"))

    def test_export_all_does_not_read_cross_layer_mappings(self):
        db = RecordingDB(query_results=[[], [], [], []])
        with patch("runtime.visualize.export.write_output", side_effect=lambda graph, out_path=None: graph):
            export_all(db, out_path=None)
        sql = " ".join(query[0] for query in db.queries)
        self.assertNotIn("FROM brand_mapping", sql)

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

    def test_l1_unknown_profile_fails_fast_not_global_fallback(self):
        registry = get_common_registry()
        with self.assertRaises(ValueError):
            registry.profile("l2_industryy")
        with self.assertRaises(ValueError):
            registry.entity_types("l2_industryy")
        with self.assertRaises(ValueError):
            registry.relation_types("l2_industryy")
        with self.assertRaises(ValueError):
            registry.statement_classes("l2_industryy")
        with self.assertRaises(ValueError):
            registry.require_profile("nope")
        with self.assertRaises(ValueError):
            registry.require_profile(None)

    def test_l1_none_profile_is_rejected(self):
        registry = get_common_registry()
        for value in (None, ""):
            with self.assertRaises(ValueError):
                registry.profile(value)
            with self.assertRaises(ValueError):
                registry.entity_types(value)
            with self.assertRaises(ValueError):
                registry.relation_types(value)

    def test_l1_known_profiles_resolve_to_their_whitelist(self):
        registry = get_common_registry()
        self.assertEqual(registry.profile("l2_industry").profile_id, "l2_industry")
        self.assertIn("industry", registry.entity_types("l2_industry"))
        self.assertIn("brand", registry.entity_types("l3_brand"))
        self.assertNotIn("observation", registry.entity_types("l3_brand"))

    def test_l1_validate_profile_reports_unknown_not_raises(self):
        registry = get_common_registry()
        self.assertEqual(registry.validate_profile("nope"), ["unknown profile 'nope'"])

    def test_l1_registry_loads_layer_profiles(self):
        registry = get_common_registry()
        self.assertIn("l2_industry", registry.profiles)
        self.assertIn("l3_brand", registry.profiles)
        self.assertEqual(set(registry.profiles), {"l2_industry", "l3_brand"})
        self.assertIn("industry", registry.entity_types("l2_industry"))
        self.assertIn("brand", registry.entity_types("l3_brand"))
        self.assertNotIn("observation", registry.entity_types("l3_brand"))

    def test_l1_profiles_are_self_consistent(self):
        registry = get_common_registry()
        self.assertEqual(registry.validate_profiles(), [])

    def test_l1_all_allowed_types_have_owner_metadata(self):
        registry = get_common_registry()
        for profile_id, profile in registry.profiles.items():
            miss_e = (profile.allowed_entity_types - set(profile.entity_type_metadata))
            miss_r = (profile.allowed_relation_types - set(profile.relation_type_metadata))
            self.assertFalse(
                miss_e,
                f"{profile_id}: allowed entity types lack owner metadata {sorted(miss_e)}",
            )
            self.assertFalse(
                miss_r,
                f"{profile_id}: allowed relation types lack owner metadata {sorted(miss_r)}",
            )

    def test_l1_profile_metadata_keeps_relations_inside_profile(self):
        registry = get_common_registry()
        meta = registry.relation_metadata("offers", "l3_brand")
        self.assertEqual(meta["owner_layer"], "l3")
        self.assertNotIn("from_layer", meta)
        self.assertNotIn("to_layer", meta)

    def test_l1_promotion_policy_reads_profile_defaults(self):
        policy = load_promotion_policy("l3_brand", 0.9)
        self.assertEqual(policy.confidence_threshold, 0.5)
        self.assertTrue(policy.direct_stable_promotion)
        self.assertFalse(policy.source_authority_ok("low"))
        self.assertTrue(policy.source_authority_ok("high"))
        self.assertTrue(policy.evidence_ok("crawled", "directly_supports"))

    def test_extraction_prompt_is_profile_driven(self):
        prompt = build_extraction_prompt("l3_brand")
        self.assertIn("当前 schema profile: l3_brand", prompt)
        self.assertIn("organization", prompt)
        self.assertIn("offers", prompt)
        self.assertIn("禁止读取或推断其他层本体", prompt)
        self.assertIn("模块化实体/关系/指标维度", prompt)
        self.assertIn("l3_brand_value_proof", prompt)
        self.assertIn("品牌自述", prompt)
        self.assertIn("metric_name", prompt)

    def test_profile_validator_blocks_runtime_records_as_graph_types(self):
        payload = {
            "entities": [
                {"id": "ent_brand_acme", "type": "brand", "canonical_name": "Acme", "aliases": []},
                {"id": "ent_source_report", "type": "source", "canonical_name": "Report", "aliases": []},
            ],
            "relations": [
                {
                    "subject": "ent_brand_acme",
                    "relation": "cites",
                    "object": "ent_source_report",
                    "confidence": 0.8,
                }
            ],
            "statements": [],
        }
        result = validate_ontology(payload, profile_id="l3_brand")
        self.assertFalse(result.ok)
        self.assertTrue(any("unknown entity type 'source'" in error for error in result.errors))
        self.assertTrue(any("unknown relation type 'cites'" in error for error in result.errors))

    # ------------------------------------------------------------------
    # 候选抽取（L1-aware，证据优先）
    # ------------------------------------------------------------------

    def test_pre_extract_without_ner_client_is_unchanged(self):
        text = "DeepCleer 支持自动对账，获得 ISO 27001 认证。"
        candidates = pre_extract(text)
        self.assertTrue(candidates)
        self.assertFalse([c for c in candidates if c["generator"].startswith("paddlenlp:")])

    def test_ner_type_mapping_whitelists_and_drops(self):
        self.assertEqual(_NER_TYPE_MAP["organization"], "organization")
        self.assertEqual(_NER_TYPE_MAP["org"], "organization")
        self.assertEqual(_NER_TYPE_MAP["product_name"], "product")
        self.assertEqual(_NER_TYPE_MAP["cert"], "certification")
        # person maps to a valid L1 brand-customer entity rather than being dropped
        self.assertEqual(_NER_TYPE_MAP["person"], "customer")
        # Unknown / non-domain generic labels are not mapped and never become candidates.
        self.assertNotIn("location", _NER_TYPE_MAP)
        self.assertNotIn("", _NER_TYPE_MAP)

    def test_ner_layer_builds_candidates_and_ids_generator(self):
        class FakeNER:
            def named_entities(self, text):
                return [
                    {"type": "organization", "text": "上海智云图科技有限公司", "score": 0.95},
                    {"type": "capability", "text": "自动对账", "score": 0.85},
                    {"type": "person", "text": "张三", "score": 0.9},  # -> customer
                ]

        candidates = ner_candidates("sample", FakeNER())
        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(c["generator"].startswith("paddlenlp:ner:")
                            for c in candidates))
        org = next(c for c in candidates if c["candidate_payload"]["entity_type"] == "organization")
        self.assertEqual(org["candidate_payload"]["name"], "上海智云图科技有限公司")
        self.assertEqual(org["confidence"], 0.95)
        # person is mapped to customer (valid L1 brand type), not dropped
        cust = next(c for c in candidates if c["candidate_payload"]["entity_type"] == "customer")
        self.assertEqual(cust["candidate_payload"]["name"], "张三")

    def test_build_candidate_rows_requires_evidence_text(self):
        context = {
            "document_uuid": "duuid", "document_id": "doc1", "profile_id": "l2_industry",
            "layer": "l2_industry",
        }
        ev_unit = {"unit_id": "EU1", "source_span_ids": ["ES1"], "text": "营收 12 亿元。"}
        rows = build_candidate_rows(
            context, ev_unit,
            [{"candidate_type": "metric", "candidate_payload": {"value": "12", "name": "营收"},
              "confidence": 0.85, "generator": "regex:numeric_metric"}],
        )
        self.assertEqual(rows[0]["evidence_text"], "营收 12 亿元。")
        self.assertTrue(rows[0]["schema_valid"])
        self.assertEqual(rows[0]["document_id" if rows[0].get("document_id") else "document_uuid"],
                         rows[0]["document_uuid"])
        # 实体预筛本身不落成知识候选（否则噪音）
        entity_rows = build_candidate_rows(
            context, ev_unit,
            [{"candidate_type": "entity",
              "candidate_payload": {"name": "Acme", "entity_type": "organization"},
              "confidence": 0.9, "generator": "paddlenlp:ner:organization"}],
        )
        self.assertEqual(entity_rows, [])

    def test_pre_extract_with_ner_client_appends_ner_candidates(self):
        class FakeNER:
            def named_entities(self, text):
                return [{"type": "product", "text": "AI 业财平台", "score": 0.9}]

        candidates = pre_extract("提供 AI 业财平台，支持自动对账。", ner_client=FakeNER(),
                                 profile_id="l3_brand")
        ners = [c for c in candidates if c["generator"].startswith("paddlenlp:")]
        self.assertTrue(ners)
        self.assertEqual(ners[0]["candidate_payload"]["name"], "AI 业财平台")

    def test_ner_entity_error_degrades_to_empty(self):
        class BrokenNER:
            def named_entities(self, text):
                raise RuntimeError("model init failed")

        self.assertEqual(ner_candidates("any text", BrokenNER()), [])

    def test_ner_chinese_schema_label_mapping(self):
        self.assertEqual(_SCHEMA_ZH["organization"], "公司")
        self.assertEqual(_SCHEMA_ZH["certification"], "认证")
        self.assertEqual(_map_ner_type("公司"), "organization")
        self.assertEqual(_map_ner_type("产品"), "product")
        self.assertEqual(_map_ner_type("能力"), "capability")

    def test_ner_span_cleaning_trims_dangling_brackets(self):
        self.assertEqual(_clean_span("DeepCleer 深澈智算（上海智云图科技有限公司"),
                         "DeepCleer 深澈智算（上海智云图科技有限公司")
        self.assertEqual(_clean_span("（智能风控大脑）"), "（智能风控大脑）")
        self.assertEqual(_clean_span("「智能风控大脑"), "智能风控大脑")
        self.assertEqual(_clean_span("  X  "), "X")
        self.assertEqual(_clean_span(""), "")

    # ------------------------------------------------------------------
    # 融合（knowledge_fusion：实体消解 / 冲突 / 融合）
    # ------------------------------------------------------------------

    def test_fusion_resolves_entities_by_type_and_name(self):
        db = RecordingDB()
        candidates = [
            {"candidate_id": "KC1", "subject": {"name": "Acme", "entity_type": "brand"},
             "confidence": 0.8, "evidence_unit_id": "EU1"},
            {"candidate_id": "KC2", "subject": {"name": "Acme", "entity_type": "brand"},
             "confidence": 0.7, "evidence_unit_id": "EU2"},
        ]
        entities = resolve_entities(db, candidates, profile_id="l3_brand",
                                    layer="l3_brand", tenant_id=None)
        self.assertEqual(len(entities), 1)
        ent = next(iter(entities.values()))
        self.assertEqual(ent["confidence"], 0.8)  # max aggregated
        self.assertEqual(len(ent["source_candidate_ids"]), 2)
        self.assertEqual(len(ent["evidence_refs"]), 2)

    def test_fusion_conflicts_split_different_objects(self):
        db = RecordingDB()
        candidates = [
            {"candidate_id": "KC1", "candidate_type": "relation",
             "subject": {"name": "Acme", "entity_type": "brand"},
             "predicate": {"type": "offers"},
             "object": {"name": "产品A"}, "confidence": 0.8,
             "evidence_text": "Acme 提供产品A。", "evidence_unit_id": "EU1"},
            {"candidate_id": "KC2", "candidate_type": "relation",
             "subject": {"name": "Acme", "entity_type": "brand"},
             "predicate": {"type": "offers"},
             "object": {"name": "产品B"}, "confidence": 0.8,
             "evidence_text": "Acme 提供产品B。", "evidence_unit_id": "EU2"},
        ]
        entities = resolve_entities(db, candidates, profile_id="l3_brand",
                                    layer="l3_brand", tenant_id=None)
        stats = group_and_emit(db, candidates, entities, profile_id="l3_brand",
                               layer="l3_brand", tenant_id=None)
        self.assertEqual(stats["conflict_groups"], 1)
        self.assertEqual(stats["conflicted"], 2)
        self.assertEqual(stats["emitted"], 2)

    def test_fusion_fuses_same_object(self):
        db = RecordingDB()
        candidates = [
            {"candidate_id": "KC1", "candidate_type": "relation",
             "subject": {"name": "Acme", "entity_type": "brand"},
             "predicate": {"type": "offers"},
             "object": {"name": "产品A"}, "confidence": 0.8,
             "evidence_text": "Acme 提供产品A。", "evidence_unit_id": "EU1"},
            {"candidate_id": "KC2", "candidate_type": "relation",
             "subject": {"name": "Acme", "entity_type": "brand"},
             "predicate": {"type": "offers"},
             "object": {"name": "产品A"}, "confidence": 0.7,
             "evidence_text": "Acme 提供产品A 认证。", "evidence_unit_id": "EU2"},
        ]
        entities = resolve_entities(db, candidates, profile_id="l3_brand",
                                    layer="l3_brand", tenant_id=None)
        stats = group_and_emit(db, candidates, entities, profile_id="l3_brand",
                               layer="l3_brand", tenant_id=None)
        self.assertEqual(stats["conflict_groups"], 0)
        self.assertEqual(stats["fused"], 1)  # 1 extra merged
        self.assertEqual(stats["emitted"], 1)

    def test_load_candidates_queries_by_profile(self):
        db = RecordingDB(query_results=[[]])
        load_candidates(db, "l3_brand")
        self.assertIn("knowledge_candidates", db.queries[0][0])
        self.assertIn("profile_id=%s", db.queries[0][0])

    # ------------------------------------------------------------------
    # 门禁（promotion：L1 eval + disposition）
    # ------------------------------------------------------------------

    def test_gate_evidence_requires_direct_support(self):
        db = RecordingDB()
        k = {
            "knowledge_id": "GK1", "knowledge_type": "statement",
            "subject_entity_id": "ent_brand_acme", "confidence": 0.9,
            "evidence_refs": [{"access_status": "ok",
                               "support_status": "directly_supports"}],
        }
        results = evaluate_instance(db, k, profile_id="l2_industry", policy=_fake_policy())
        gate = next(r for r in results if r["gate_id"] == "gate_evidence")
        self.assertTrue(gate["passed"])

    def test_gate_evidence_rejects_unsupported_evidence(self):
        db = RecordingDB()
        k = {
            "knowledge_id": "GK1", "knowledge_type": "statement",
            "subject_entity_id": "ent_brand_acme", "confidence": 0.9,
            "evidence_refs": [{"access_status": "ok",
                               "support_status": "contradicts"}],
        }
        results = evaluate_instance(db, k, profile_id="l2_industry", policy=_fake_policy())
        gate = next(r for r in results if r["gate_id"] == "gate_evidence")
        self.assertFalse(gate["passed"])

    def test_zero_confidence_fails_quality_gate(self):
        db = RecordingDB()
        k = {
            "knowledge_id": "GK1", "knowledge_type": "statement",
            "subject_entity_id": "ent_brand_acme", "confidence": 0,
            "evidence_refs": [{"access_status": "ok",
                               "support_status": "directly_supports"}],
        }
        results = evaluate_instance(db, k, profile_id="l2_industry", policy=_fake_policy())
        conf_gate = next(r for r in results if r["gate_id"] == "gate_confidence")
        self.assertEqual(conf_gate["detail"], "confidence=0 threshold=0.5")
        decision, decisive = disposition(results)
        self.assertEqual(decision, "review")
        self.assertEqual(decisive["gate_id"], "gate_confidence")

    def test_hard_gate_failure_takes_priority_over_review(self):
        results = [
            {"gate_id": "gate_ontology", "passed": False,
             "detail": "missing", "action": "reject"},
            {"gate_id": "gate_confidence", "passed": False,
             "detail": "low", "action": "review"},
        ]
        decision, decisive = disposition(results)
        self.assertEqual(decision, "reject")
        self.assertEqual(decisive["gate_id"], "gate_ontology")

    def test_all_gates_pass_promotes(self):
        db = RecordingDB()
        k = {
            "knowledge_id": "GK1", "knowledge_type": "statement",
            "subject_entity_id": "ent_brand_acme", "confidence": 0.95,
            "evidence_refs": [{"access_status": "ok",
                               "support_status": "directly_supports"}],
        }
        results = evaluate_instance(db, k, profile_id="l2_industry", policy=_fake_policy())
        self.assertTrue(all(r["passed"] for r in results))
        self.assertEqual(disposition(results)[0], "promote")

    # ------------------------------------------------------------------
    # 敏感内容提醒（L3 §10.2）
    # ------------------------------------------------------------------

    def test_sensitive_content_warning_grades_severity(self):
        high = scan_risks("本项目是行业唯一，获得 ISO 27001 认证，ROI 提升 30%。")
        types = {w["warning_type"]: w["severity"] for w in high}
        self.assertEqual(types.get("absolute_claim"), 2)
        self.assertEqual(types.get("certification_claim"), 2)
        self.assertEqual(types.get("financial_kpi"), 2)
        self.assertTrue(all(w["severity"] >= 2 for w in high))

    def test_sensitive_content_warning_marks_blocked_false(self):
        # 只提醒不阻断（§10.2）
        self.assertEqual(scan_risks("普通产品介绍。"), [])
        from runtime.brand.pipelines.sensitive_content_warning import _render_action
        self.assertEqual(_render_action(2), "review_before_publication")
        self.assertEqual(_render_action(1), "flag_for_disclosure")


if __name__ == "__main__":
    unittest.main()