from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.application.services.agent import AgentService
from backend.app.config import RuntimeSettings
from backend.app.infrastructure.database import LocalDatabase
from backend.app.infrastructure.providers.llm import OpenAICompatibleClient
from backend.app.infrastructure.repositories import KnowledgeRepository


class EvidenceCitationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = LocalDatabase(Path(self.temp_dir.name) / "knowledge.db")
        self.database.initialize()
        self.repository = KnowledgeRepository(self.database)
        self.database.execute(
            """INSERT INTO documents
            (id,title,content,source_type,layer,content_hash,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "document-1", "Acme 产品说明", "Acme 提供 CRM 平台。",
                "text", "l3_brand", "hash-1", "active", "1", "1",
            ),
        )
        self.database.execute(
            """INSERT INTO evidence_spans
            (id,document_id,span_type,text,heading_path_json,order_index,char_start,char_end,locator_json)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                "span-1", "document-1", "paragraph", "Acme 提供 CRM 平台。",
                json.dumps(["产品"], ensure_ascii=False), 0, 0, 13, "{}",
            ),
        )
        self.database.execute(
            """INSERT INTO evidence_units
            (id,document_id,source_span_ids_json,text,heading_path_json,merge_reason_json,token_count)
            VALUES (?,?,?,?,?,?,?)""",
            (
                "unit-1", "document-1", json.dumps(["span-1"]),
                "Acme 提供 CRM 平台。", json.dumps(["产品"], ensure_ascii=False), "[]", 8,
            ),
        )
        self.database.execute(
            """INSERT INTO entities
            (id,type,name,normalized_name,layer,properties_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                "brand-1", "brand", "Acme", "acme", "l3_brand",
                json.dumps({"evidence_refs": [{"evidence_unit_id": "unit-1", "quote": "Acme 提供 CRM 平台。"}]}),
                "1", "1",
            ),
        )
        self.database.execute(
            """INSERT INTO entities
            (id,type,name,normalized_name,layer,properties_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("product-1", "product", "CRM 平台", "crm 平台", "l3_brand", "{}", "1", "2"),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unit_reference_expands_to_original_span(self):
        citations = self.repository.evidence_citations(
            [{"evidence_unit_id": "unit-1", "quote": "Acme 提供 CRM 平台。"}]
        )

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["document_title"], "Acme 产品说明")
        self.assertEqual(citations[0]["evidence_span_ids"], ["span-1"])
        self.assertEqual(citations[0]["span_texts"], ["Acme 提供 CRM 平台。"])
        self.assertEqual(citations[0]["heading_path"], ["产品"])
        self.assertEqual(citations[0]["char_start"], 0)

    def test_search_and_graph_include_relation_and_entity_citations(self):
        self.database.execute(
            """INSERT INTO relations
            (id,source_id,target_id,relation_type,document_id,properties_json,confidence,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                "relation-1", "brand-1", "product-1", "offers", "document-1",
                json.dumps({"evidence_refs": [{"evidence_unit_id": "unit-1"}]}),
                0.9, "2",
            ),
        )

        search_items = self.repository.search("Acme")
        entity = next(item for item in search_items if item["kind"] == "entity")
        self.assertEqual(entity["citations"][0]["evidence_unit_id"], "unit-1")

        graph = self.repository.graph()
        self.assertEqual(graph["edges"][0]["citations"][0]["evidence_span_ids"], ["span-1"])

    def test_statement_source_span_is_returned_as_citation(self):
        self.database.execute(
            """INSERT INTO statements
            (id,subject_id,document_id,statement_text,statement_class,properties_json,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (
                "statement-1", "brand-1", "document-1", "Acme 提供 CRM 平台。", "observation",
                json.dumps({"source_span_id": "span-1"}), "2",
            ),
        )

        items = self.repository.search("提供 CRM")
        statement = next(item for item in items if item["kind"] == "statement")
        self.assertEqual(statement["citations"][0]["evidence_span_ids"], ["span-1"])

    def test_document_filter_does_not_resolve_a_foreign_span(self):
        citations = self.repository.evidence_citations(
            [{"evidence_unit_id": "unit-1"}], document_id="other-document"
        )

        self.assertEqual(citations, [])

    def test_agent_sends_evidence_quote_to_llm_context(self):
        class FakeRetrieval:
            def search(self, query: str, limit: int = 8):
                return [{
                    "kind": "relation",
                    "id": "relation-1",
                    "title": "Acme offers CRM",
                    "snippet": "Acme -[offers]-> CRM 平台",
                    "citations": [{
                        "id": "document-1:unit-1",
                        "document_id": "document-1",
                        "quote": "Acme 提供 CRM 平台。",
                        "evidence_span_ids": ["span-1"],
                        "span_texts": ["Acme 提供 CRM 平台。"],
                    }],
                }]

        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.invalid/v1",
            llm_model="test-model",
        )
        with patch.object(OpenAICompatibleClient, "chat", return_value="ok") as chat:
            result = AgentService(
                object(), settings, retrieval_service=FakeRetrieval()
            ).answer("这条关系来自哪里？")

        context = chat.call_args.args[0][-2]["content"]
        self.assertIn("Acme 提供 CRM 平台。", context)
        self.assertEqual(result["sources"][0]["citations"][0]["evidence_span_ids"], ["span-1"])


if __name__ == "__main__":
    unittest.main()
