"""Regression tests for the D3 Application/Repository boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.application.services.ingestion import DocumentIngestionService
from backend.app.infrastructure.database import LocalDatabase
from backend.app.infrastructure.repositories import KnowledgeRepository


class D3RepositoryBoundaryTests(unittest.TestCase):
    @staticmethod
    def _repository(root: Path) -> tuple[LocalDatabase, KnowledgeRepository]:
        database = LocalDatabase(root / "knowledge.db")
        database.initialize()
        return database, KnowledgeRepository(database)

    @staticmethod
    def _document(document_id: str) -> dict[str, str]:
        return {
            "id": document_id,
            "title": document_id,
            "content": f"content-{document_id}",
            "source_type": "test",
            "layer": "l3_brand",
            "brand_id": "Acme",
            "tenant_id": "local",
            "content_hash": f"hash-{document_id}",
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    @staticmethod
    def _bundle(document_id: str, count: int) -> dict:
        spans = [
            {
                "span_id": f"span-{document_id}-{index}",
                "span_type": "paragraph",
                "text": f"evidence-{document_id}-{index}",
                "order_index": index,
                "char_start": index * 10,
                "char_end": index * 10 + 10,
            }
            for index in range(count)
        ]
        units = [
            {
                "unit_id": f"unit-{document_id}-{index}",
                "source_span_ids": [span["span_id"]],
                "text": span["text"],
            }
            for index, span in enumerate(spans)
        ]
        candidates = [
            {
                "id": f"candidate-{document_id}-{index}",
                "candidate_type": "statement",
                "evidence_text": unit["text"],
                "statement": {"text": f"fact-{document_id}-{index}"},
                "extraction_method": ["test"],
            }
            for index, unit in enumerate(units)
        ]
        return {
            "document": D3RepositoryBoundaryTests._document(document_id),
            "spans": spans,
            "units": units,
            "candidates": candidates,
            "entities": [],
            "relations": [],
            "statements": [],
        }

    @staticmethod
    def _save(repository: KnowledgeRepository, bundle: dict) -> None:
        repository.save_bundle(
            bundle["document"], bundle["spans"], bundle["units"],
            bundle["candidates"], bundle["entities"], bundle["relations"],
            bundle["statements"],
        )

    def test_document_extraction_counts_are_scoped_to_one_document(self):
        with tempfile.TemporaryDirectory() as temp:
            database, repository = self._repository(Path(temp))
            self._save(repository, self._bundle("doc-a", 2))
            self._save(repository, self._bundle("doc-b", 3))

            self.assertEqual(
                repository.document_extraction_counts("doc-a"),
                {"spans": 2, "units": 2, "candidates": 2, "relations": 0, "statements": 0},
            )
            self.assertEqual(
                repository.document_extraction_counts("missing"),
                {"spans": 0, "units": 0, "candidates": 0, "relations": 0, "statements": 0},
            )
            self.assertEqual(database.query("SELECT COUNT(*) AS count FROM evidence_spans")[0]["count"], 5)

    def test_duplicate_import_returns_existing_counts_without_new_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            database, repository = self._repository(Path(temp))
            service = DocumentIngestionService(repository)
            content = "Acme 公司提供 CRM 平台，支持企业客户。"

            first = service.import_document(
                title="重复导入", content=content, file_path=None,
                source_type="test", layer="l3_brand", brand_id="Acme", tenant_id="local",
            )
            second = service.import_document(
                title="重复导入", content=content, file_path=None,
                source_type="test", layer="l3_brand", brand_id="Acme", tenant_id="local",
            )

            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(second["span_count"], first["span_count"])
            self.assertEqual(second["unit_count"], first["unit_count"])
            self.assertEqual(second["candidate_count"], first["candidate_count"])
            self.assertEqual(database.query("SELECT COUNT(*) AS count FROM documents")[0]["count"], 1)
            self.assertEqual(database.query("SELECT COUNT(*) AS count FROM evidence_spans")[0]["count"], first["span_count"])
            self.assertEqual(database.query("SELECT COUNT(*) AS count FROM evidence_units")[0]["count"], first["unit_count"])
            self.assertEqual(database.query("SELECT COUNT(*) AS count FROM knowledge_candidates")[0]["count"], first["candidate_count"])

    def test_empty_counts_return_zero_for_all_fixed_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            _, repository = self._repository(Path(temp))
            self.assertEqual(
                repository.document_extraction_counts("empty-document"),
                {"spans": 0, "units": 0, "candidates": 0, "relations": 0, "statements": 0},
            )

    def test_duplicate_branch_works_with_repository_without_db_attribute(self):
        class FakeRepository:
            def document_by_hash(self, content_hash):
                return {"id": "existing", "title": "Existing"}

            def document_extraction_counts(self, document_id):
                if document_id != "existing":
                    raise AssertionError(f"unexpected document id: {document_id}")
                return {"spans": 3, "units": 2, "candidates": 1}

        repository = FakeRepository()
        result = DocumentIngestionService(repository).import_document(
            title="Existing", content="same content", file_path=None,
            source_type="test", layer="l3_brand", brand_id="Acme", tenant_id="local",
        )

        self.assertFalse(hasattr(repository, "db"))
        self.assertEqual(
            result,
            {
                "document_id": "existing",
                "title": "Existing",
                "content_hash": __import__("hashlib").sha256("same content".encode("utf-8")).hexdigest(),
                "duplicate": True,
                "span_count": 3,
                "unit_count": 2,
                "candidate_count": 1,
            },
        )

    def test_application_has_no_direct_database_access(self):
        application_root = Path(__file__).resolve().parents[1] / "backend" / "app" / "application"
        for path in application_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "repository.db",
                "sqlite3",
                "Connection",
                "Cursor",
                ".query(",
                ".execute(",
                "SELECT ",
                "INSERT INTO",
                "UPDATE ",
                "DELETE ",
                "PRAGMA",
            ):
                self.assertNotIn(forbidden, source, path)





if __name__ == "__main__":
    unittest.main()