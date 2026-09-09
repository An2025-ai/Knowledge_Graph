from __future__ import annotations

import unittest

from shared.extraction.candidate_extraction import (
    _NER_TYPE_MAP,
    build_candidate_rows,
    ner_candidates,
    pre_extract,
)
from shared.knowledge.policy_engine import load_promotion_policy
from shared.knowledge.prompt_builder import build_extraction_prompt
from shared.knowledge.registry import get_common_registry
from shared.ontology.ontology_validator import validate_ontology


class SharedKnowledgeTests(unittest.TestCase):
    def test_registry_rejects_unknown_or_missing_profiles(self):
        registry = get_common_registry()
        for profile_id in ("l2_industryy", "nope"):
            with self.assertRaises(ValueError):
                registry.profile(profile_id)
        for value in (None, ""):
            with self.assertRaises(ValueError):
                registry.require_profile(value)
            with self.assertRaises(ValueError):
                registry.entity_types(value)

    def test_registry_profiles_are_loaded_and_self_consistent(self):
        registry = get_common_registry()
        self.assertEqual(set(registry.profiles), {"l2_industry", "l3_brand"})
        self.assertEqual(registry.validate_profiles(), [])
        self.assertIn("industry", registry.entity_types("l2_industry"))
        self.assertIn("brand", registry.entity_types("l3_brand"))
        self.assertNotIn("observation", registry.entity_types("l3_brand"))

    def test_registry_reports_unknown_profile_without_raising(self):
        self.assertEqual(
            get_common_registry().validate_profile("nope"),
            ["unknown profile 'nope'"],
        )

    def test_registry_relation_metadata_stays_inside_profile(self):
        metadata = get_common_registry().relation_metadata("offers", "l3_brand")
        self.assertEqual(metadata["owner_layer"], "l3")
        self.assertNotIn("from_layer", metadata)
        self.assertNotIn("to_layer", metadata)

    def test_promotion_policy_reads_profile_defaults(self):
        policy = load_promotion_policy("l3_brand", 0.9)
        self.assertEqual(policy.confidence_threshold, 0.5)
        self.assertTrue(policy.direct_stable_promotion)
        self.assertFalse(policy.source_authority_ok("low"))
        self.assertTrue(policy.source_authority_ok("high"))
        self.assertTrue(policy.evidence_ok("crawled", "directly_supports"))

    def test_extraction_prompt_is_profile_driven(self):
        prompt = build_extraction_prompt("l3_brand")
        for expected in (
            "当前 schema profile: l3_brand",
            "organization",
            "offers",
            "模块化实体/关系/指标维度",
            "l3_brand_value_proof",
            "metric_name",
        ):
            self.assertIn(expected, prompt)

    def test_ontology_validator_rejects_runtime_types_and_relations(self):
        payload = {
            "entities": [
                {"id": "ent_brand_acme", "type": "brand", "canonical_name": "Acme"},
                {"id": "ent_source_report", "type": "source", "canonical_name": "Report"},
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

    def test_pre_extract_without_ner_client_uses_rules_only(self):
        candidates = pre_extract("DeepCleer 支持自动对账，获得 ISO 27001 认证。")
        self.assertTrue(candidates)
        self.assertFalse(
            [c for c in candidates if c["generator"].startswith("paddlenlp:")]
        )

    def test_ner_type_mapping_builds_domain_candidates(self):
        self.assertEqual(_NER_TYPE_MAP["organization"], "organization")
        self.assertEqual(_NER_TYPE_MAP["product_name"], "product")
        self.assertEqual(_NER_TYPE_MAP["person"], "customer")
        self.assertNotIn("location", _NER_TYPE_MAP)

        class FakeNER:
            def named_entities(self, text):
                return [
                    {"type": "organization", "text": "Acme", "score": 0.95},
                    {"type": "capability", "text": "自动对账", "score": 0.85},
                    {"type": "person", "text": "张三", "score": 0.9},
                ]

        candidates = ner_candidates("sample", FakeNER())
        self.assertEqual(len(candidates), 3)
        self.assertTrue(
            all(c["generator"].startswith("paddlenlp:ner:") for c in candidates)
        )
        customer = next(
            c for c in candidates if c["candidate_payload"]["entity_type"] == "customer"
        )
        self.assertEqual(customer["candidate_payload"]["name"], "张三")

    def test_build_candidate_rows_preserves_evidence_and_skips_entities(self):
        context = {
            "document_uuid": "duuid",
            "document_id": "doc1",
            "profile_id": "l2_industry",
            "layer": "l2_industry",
        }
        ev_unit = {"unit_id": "EU1", "source_span_ids": ["ES1"], "text": "营收 12 亿元。"}
        rows = build_candidate_rows(
            context,
            ev_unit,
            [
                {
                    "candidate_type": "metric",
                    "candidate_payload": {"value": "12", "name": "营收"},
                    "confidence": 0.85,
                    "generator": "regex:numeric_metric",
                }
            ],
        )
        self.assertEqual(rows[0]["evidence_text"], "营收 12 亿元。")
        self.assertTrue(rows[0]["schema_valid"])
        self.assertEqual(rows[0]["document_uuid"], "duuid")
        self.assertEqual(
            build_candidate_rows(
                context,
                ev_unit,
                [
                    {
                        "candidate_type": "entity",
                        "candidate_payload": {"name": "Acme", "entity_type": "organization"},
                        "confidence": 0.9,
                        "generator": "paddlenlp:ner:organization",
                    }
                ],
            ),
            [],
        )

    def test_pre_extract_appends_ner_candidates_for_allowed_profile(self):
        class FakeNER:
            def named_entities(self, text):
                return [{"type": "product", "text": "AI 业财平台", "score": 0.9}]

        candidates = pre_extract(
            "提供 AI 业财平台，支持自动对账。",
            ner_client=FakeNER(),
            profile_id="l3_brand",
        )
        ner_rows = [c for c in candidates if c["generator"].startswith("paddlenlp:")]
        self.assertTrue(ner_rows)
        self.assertEqual(ner_rows[0]["candidate_payload"]["name"], "AI 业财平台")

    def test_broken_ner_client_is_optional(self):
        class BrokenNER:
            def named_entities(self, text):
                raise RuntimeError("model init failed")

        self.assertEqual(ner_candidates("any text", BrokenNER()), [])


if __name__ == "__main__":
    unittest.main()
