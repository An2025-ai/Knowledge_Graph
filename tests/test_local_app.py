"""Smoke tests for the local-first application boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import AppPaths
from backend.app.config import RuntimeSettings
from backend.app.database import LocalDatabase
from backend.app.factory import create_app
from backend.app.repositories import KnowledgeRepository
from backend.app.services.ingestion import DocumentIngestionService


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


if __name__ == "__main__":
    unittest.main()
