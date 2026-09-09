from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.application.services.agent import AgentService
from backend.app.application.services.retrieval import RetrievalService
from backend.app.config import RuntimeSettings
from backend.app.infrastructure.database import LocalDatabase
from backend.app.infrastructure.providers.llm import OpenAICompatibleClient
from backend.app.infrastructure.repositories import KnowledgeRepository


class AgentRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = LocalDatabase(Path(self.temp_dir.name) / "knowledge.db")
        self.database.initialize()
        self.repository = KnowledgeRepository(self.database)
        self.database.execute(
            """INSERT INTO entities
            (id,type,name,normalized_name,layer,properties_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("brand-1", "brand", "Acme", "acme", "l3_brand", "{}", "1", "1"),
        )
        self.database.execute(
            """INSERT INTO entities
            (id,type,name,normalized_name,layer,properties_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("product-1", "product", "CRM 平台", "crm平台", "l3_brand", "{}", "1", "2"),
        )
        self.database.execute(
            """INSERT INTO relations
            (id,source_id,target_id,relation_type,confidence,created_at)
            VALUES (?,?,?,?,?,?)""",
            ("relation-1", "brand-1", "product-1", "offers", 0.9, "2"),
        )
        self.database.execute(
            """INSERT INTO statements
            (id,subject_id,statement_text,statement_class,created_at)
            VALUES (?,?,?,?,?)""",
            ("statement-1", "brand-1", "Acme 提供 CRM 平台。", "observation", "2"),
        )
        self.retrieval = RetrievalService(self.repository)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_workspace_overview_returns_local_context_for_generic_question(self):
        items = self.retrieval.search("你是否知晓数据库中的内容", limit=8)

        self.assertTrue(items)
        self.assertIn("Acme", {item["title"] for item in items})
        self.assertTrue(any(item["kind"] == "relation" for item in items))
        self.assertTrue(any(item["kind"] == "statement" for item in items))

    def test_product_intent_returns_product_entities_without_exact_match(self):
        items = self.retrieval.search("当前知识库有哪些产品？", limit=8)

        self.assertTrue(any(item["title"] == "CRM 平台" for item in items))
        self.assertTrue(all(item["type"] in {"product", "solution", "service"}
                            for item in items if item["kind"] == "entity"))

    def test_unrelated_question_does_not_dump_the_workspace(self):
        self.assertEqual(self.retrieval.search("你知道量子计算吗？", limit=8), [])
        self.assertEqual(self.retrieval.search("量子计算的历史", limit=8), [])
        self.assertEqual(
            self.retrieval.search("当前知识库中有量子计算吗？", limit=8), []
        )

    def test_unrelated_brand_constraint_does_not_fall_back_to_overview(self):
        self.assertEqual(
            self.retrieval.search("不存在品牌的产品有哪些？", limit=8), []
        )

    def test_unmatched_document_constraint_does_not_fall_back_to_overview(self):
        self.assertEqual(
            self.retrieval.search("文档 missing-doc 中有哪些产品？", limit=8), []
        )

    def test_generic_question_sends_local_overview_to_llm(self):
        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.invalid/v1",
            llm_model="test-model",
        )
        with patch.object(OpenAICompatibleClient, "chat", return_value="知道") as chat:
            result = AgentService(self.repository, settings).answer(
                "你是否知晓数据库中的内容"
            )

        self.assertEqual(result["mode"], "external_llm")
        self.assertTrue(result["sources"])
        messages = chat.call_args.args[0]
        context = messages[-2]["content"]
        self.assertIn("Acme", context)
        self.assertIn("offers", context)
        self.assertIn("Acme 提供 CRM 平台。", context)


if __name__ == "__main__":
    unittest.main()
