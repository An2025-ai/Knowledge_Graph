from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.app.application.services.knowledge_pipeline import KnowledgeBuildPipeline
from backend.app.config import RuntimeSettings
from backend.app.infrastructure.providers.llm import OpenAICompatibleClient


class RelationEndpointNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.test/v1",
            llm_model="test-model",
        )
        self.pipeline = KnowledgeBuildPipeline(self.settings)

    def _extract_relation(self, subject, object_):
        response = json.dumps(
            {
                "entities": [
                    {"id": "entity-brand", "type": "brand", "canonical_name": "Acme"},
                    {"id": "entity-product", "type": "product", "canonical_name": "CRM"},
                ],
                "relations": [
                    {
                        "subject": subject,
                        "relation": "offers",
                        "object": object_,
                        "confidence": 0.9,
                    }
                ],
                "statements": [],
            },
            ensure_ascii=False,
        )
        with patch.object(OpenAICompatibleClient, "chat", return_value=response):
            candidates = self.pipeline._llm_extract(
                "Acme offers CRM.", "l3_brand", self.settings
            )
        relations = [
            candidate
            for candidate in candidates
            if candidate.get("candidate_type") == "relation"
        ]
        self.assertEqual(len(relations), 1)
        return relations[0]

    def test_id_endpoints_are_accepted(self):
        relation = self._extract_relation("entity-brand", "entity-product")
        self.assertEqual(relation["candidate_payload"]["subject_name"], "Acme")
        self.assertEqual(relation["candidate_payload"]["object_name"], "CRM")

    def test_name_endpoints_are_equivalent_to_ids(self):
        relation = self._extract_relation("Acme", "CRM")
        self.assertEqual(relation["candidate_payload"]["subject_name"], "Acme")
        self.assertEqual(relation["candidate_payload"]["object_name"], "CRM")

    def test_nested_object_endpoints_are_equivalent_to_ids(self):
        relation = self._extract_relation(
            {"canonical_name": "Acme", "entity_type": "brand"},
            {"name": "CRM", "type": "product"},
        )
        self.assertEqual(relation["candidate_payload"]["subject_name"], "Acme")
        self.assertEqual(relation["candidate_payload"]["object_name"], "CRM")


if __name__ == "__main__":
    unittest.main()
