"""Smoke tests for the local-first application boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.config import AppPaths
from backend.app.config import RuntimeSettings
from backend.app.database import LocalDatabase
from backend.app.factory import create_app
from backend.app.repositories import KnowledgeRepository
from backend.app.services.ingestion import DocumentIngestionService
from backend.app.services.knowledge_pipeline import KnowledgeBuildPipeline
from backend.app.services.llm import OpenAICompatibleClient


class LocalAppSmokeTests(unittest.TestCase):
    def test_tauri_cors_preflight_is_allowed_without_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = AppPaths(
                root, root / "database" / "knowledge.db", root / "documents",
                root / "vectors", root / "cache", root / "logs", root / "backups",
                root / "config",
            )
            client = TestClient(create_app(paths=paths, settings=RuntimeSettings(token="test-token")))
            response = client.options(
                "/api/settings/test/llm",
                headers={
                    "Origin": "http://tauri.localhost",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("access-control-allow-origin"), "http://tauri.localhost")

    def test_connection_test_skips_disabled_providers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = AppPaths(
                root, root / "database" / "knowledge.db", root / "documents",
                root / "vectors", root / "cache", root / "logs", root / "backups",
                root / "config",
            )
            app = create_app(paths=paths, settings=RuntimeSettings(token="test-token"))
            with TestClient(app) as client:
                response = client.post(
                    "/api/settings/test",
                    headers={"Authorization": "Bearer test-token"},
                    json={"llm_provider": "none", "embedding_provider": "none"},
                )
                llm_response = client.post(
                    "/api/settings/test/llm",
                    headers={"Authorization": "Bearer test-token"},
                    json={"base_url": "", "model": ""},
                )
                embedding_response = client.post(
                    "/api/settings/test/embedding",
                    headers={"Authorization": "Bearer test-token"},
                    json={"base_url": "", "model": ""},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["llm"]["status"], "skipped")
            self.assertEqual(response.json()["embedding"]["status"], "skipped")
            self.assertEqual(llm_response.json()["status"], "skipped")
            self.assertEqual(embedding_response.json()["status"], "skipped")

    def test_import_builds_local_graph_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = AppPaths(
                root, root / "database" / "knowledge.db", root / "documents",
                root / "vectors", root / "cache", root / "logs", root / "backups",
                root / "config",
            )
            paths.ensure()
            db = LocalDatabase(paths.database)
            db.initialize(Path(__file__).parents[1] / "backend" / "app" / "schema.sql")
            repository = KnowledgeRepository(db)
            service = DocumentIngestionService(repository)
            text = "# 产品\nAcme 公司提供 CRM 平台，支持自动对账。\n面向企业客户。"

            first = service.import_document(
                title="Acme 产品资料", content=text, file_path=None,
                source_type="test", layer="l3_brand", brand_id="Acme", tenant_id="local",
            )
            second = service.import_document(
                title="Acme 产品资料", content=text, file_path=None,
                source_type="test", layer="l3_brand", brand_id="Acme", tenant_id="local",
            )

            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertGreaterEqual(repository.graph()["stats"]["nodes"], 1)
            self.assertEqual(repository.stats()["documents"], 1)

    def test_import_deduplicates_repeated_candidate_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = AppPaths(
                root, root / "database" / "knowledge.db", root / "documents",
                root / "vectors", root / "cache", root / "logs", root / "backups",
                root / "config",
            )
            paths.ensure()
            db = LocalDatabase(paths.database)
            db.initialize(Path(__file__).parents[1] / "backend" / "app" / "schema.sql")
            repository = KnowledgeRepository(db)
            service = DocumentIngestionService(repository)

            result = service.import_document(
                title="重复候选测试", content=(
                    "Acme 公司获得 ISO 27001 认证。"
                    "Acme 公司获得 ISO 27001 认证。"
                ), file_path=None, source_type="test", layer="l3_brand",
                brand_id="Acme", tenant_id="local",
            )

            self.assertFalse(result["duplicate"])
            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(repository.stats()["candidates"], 2)

    def test_import_rebuilds_old_style_entity_fusion_without_legacy_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = AppPaths(
                root, root / "database" / "knowledge.db", root / "documents",
                root / "vectors", root / "cache", root / "logs", root / "backups",
                root / "config",
            )
            paths.ensure()
            db = LocalDatabase(paths.database)
            db.initialize(Path(__file__).parents[1] / "backend" / "app" / "schema.sql")
            repository = KnowledgeRepository(db)
            service = DocumentIngestionService(repository)

            result = service.import_document(
                title="融合测试", content=(
                    "Acme 公司提供 CRM 平台，支持自动对账，面向中小企业客户。"
                    "获得 ISO 27001 认证。"
                ), file_path=None, source_type="test", layer="l3_brand",
                brand_id="Acme", tenant_id="local",
            )

            graph = repository.graph()
            node_keys = {(node["type"], node["name"]) for node in graph["nodes"]}
            edge_types = {edge["type"] for edge in graph["edges"]}
            self.assertTrue(result["entity_count"] >= 5)
            self.assertIn(("brand", "Acme"), node_keys)
            self.assertIn(("product", "CRM 平台"), node_keys)
            self.assertIn("offers", edge_types)
            self.assertNotIn(("organization", "ISO 27001"), node_keys)

    def test_llm_extraction_is_primary_when_available(self):
        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.test/v1",
            llm_model="test-model",
        )
        llm_candidates = [
            {
                "candidate_type": "entity",
                "candidate_payload": {"name": "模型产品", "entity_type": "product"},
                "confidence": 0.95,
                "generator": "llm:structured",
            },
            {
                "candidate_type": "relation",
                "candidate_payload": {
                    "subject_name": "Acme", "subject_type": "brand",
                    "object_name": "模型产品", "object_type": "product",
                    "type": "offers",
                },
                "confidence": 0.9,
                "generator": "llm:structured",
            },
        ]
        with patch.object(KnowledgeBuildPipeline, "_llm_extract", return_value=llm_candidates):
            build = KnowledgeBuildPipeline(settings).build(
                document_id="doc-llm", content="Acme 提供模型产品。",
                units=[{"unit_id": "unit-llm", "text": "Acme 提供模型产品。"}],
                layer="l3_brand", brand_id="Acme", tenant_id="local", content_hash="hash-llm",
            )

        methods = [method for candidate in build.candidates for method in candidate["extraction_method"]]
        self.assertTrue(build.llm_used)
        self.assertEqual(build.llm_fallback_count, 0)
        self.assertIn("llm:structured", methods)
        self.assertFalse(any(method.startswith("fallback:") for method in methods))

    def test_llm_relation_ids_are_resolved_before_promotion(self):
        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.test/v1",
            llm_model="test-model",
        )
        response = json.dumps({
            "entities": [
                {"id": "ent_brand_acme", "type": "brand", "canonical_name": "Acme"},
                {"id": "ent_product_crm", "type": "product", "canonical_name": "CRM 平台"},
            ],
            "relations": [{
                "subject": "ent_brand_acme",
                "relation": "offers",
                "object": "ent_product_crm",
                "entity_type_subject": "brand",
                "entity_type_object": "product",
                "confidence": 0.9,
            }],
            "statements": [],
        }, ensure_ascii=False)
        with patch.object(OpenAICompatibleClient, "chat", return_value=response):
            build = KnowledgeBuildPipeline(settings).build(
                document_id="doc-relation", content="Acme 提供 CRM 平台。",
                units=[{"unit_id": "unit-relation", "text": "Acme 提供 CRM 平台。"}],
                layer="l3_brand", brand_id="Acme", tenant_id="local",
                content_hash="hash-relation",
            )

        self.assertEqual(len(build.relations), 1)
        self.assertEqual(build.relations[0]["relation_type"], "offers")
        self.assertEqual(build.relations[0]["properties"]["extraction"], ["llm:structured"])

    def test_llm_extraction_marks_rule_fallbacks(self):
        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.test/v1",
            llm_model="test-model",
        )
        with patch.object(KnowledgeBuildPipeline, "_llm_extract", side_effect=TimeoutError("timeout")):
            build = KnowledgeBuildPipeline(settings).build(
                document_id="doc-timeout", content="Acme 公司提供 CRM 平台。",
                units=[{"unit_id": "unit-timeout", "text": "Acme 公司提供 CRM 平台。"}],
                layer="l3_brand", brand_id="Acme", tenant_id="local", content_hash="hash-timeout",
            )

        methods = [method for candidate in build.candidates for method in candidate["extraction_method"]]
        self.assertTrue(build.llm_attempted)
        self.assertEqual(build.llm_fallback_count, 1)
        self.assertTrue(any(method.startswith("fallback:") for method in methods))

    def test_llm_extraction_has_no_evidence_unit_limit(self):
        settings = RuntimeSettings(
            llm_provider="openai-compatible",
            llm_base_url="https://example.test/v1",
            llm_model="test-model",
        )
        units = [
            {"unit_id": f"unit-{index}", "text": f"第 {index} 条合成证据。"}
            for index in range(21)
        ]
        llm_candidates = [{
            "candidate_type": "statement",
            "candidate_payload": {"value": "模型提取的事实"},
            "confidence": 0.9,
            "generator": "llm:structured",
        }]
        with patch.object(
            KnowledgeBuildPipeline, "_llm_extract", return_value=llm_candidates
        ) as extract:
            build = KnowledgeBuildPipeline(settings).build(
                document_id="doc-no-limit", content="\n".join(unit["text"] for unit in units),
                units=units, layer="l3_brand", brand_id="Acme", tenant_id="local",
                content_hash="hash-no-limit",
            )

        self.assertEqual(extract.call_count, len(units))
        self.assertTrue(build.llm_used)
        self.assertEqual(build.llm_fallback_count, 0)


if __name__ == "__main__":
    unittest.main()
