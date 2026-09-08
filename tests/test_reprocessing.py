"""Document-owned replacement and rollback tests for the local graph store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.infrastructure.database import LocalDatabase
from backend.app.infrastructure.repositories import KnowledgeRepository


class ReprocessingTests(unittest.TestCase):
    @staticmethod
    def _repository(root: Path) -> tuple[LocalDatabase, KnowledgeRepository]:
        db = LocalDatabase(root / "knowledge.db")
        db.initialize()
        return db, KnowledgeRepository(db)

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
    def _bundle(
        document_id: str, *, include_b: bool = True, include_relation: bool = True
    ) -> dict[str, list[dict[str, object]] | dict[str, str]]:
        entity_a = {
            "id": "entity-a",
            "type": "brand",
            "name": "Acme",
            "layer": "l3_brand",
            "brand_id": "Acme",
            "tenant_id": "local",
            "properties": {"source_document_id": document_id},
        }
        entity_b = {
            "id": "entity-b",
            "type": "product",
            "name": "产品B",
            "layer": "l3_brand",
            "brand_id": "Acme",
            "tenant_id": "local",
            "properties": {"source_document_id": document_id},
        }
        entities = [entity_a] + ([entity_b] if include_b else [])
        relations = []
        if include_relation and include_b:
            relations.append({
                "id": f"relation-{document_id}",
                "source_id": "entity-a",
                "target_id": "entity-b",
                "relation_type": "offers",
                "confidence": 0.9,
                "properties": {"source_document_id": document_id},
            })
        return {
            "document": ReprocessingTests._document(document_id),
            "spans": [{
                "span_id": f"span-{document_id}", "span_type": "paragraph",
                "text": f"evidence-{document_id}", "order_index": 0,
                "char_start": 0, "char_end": 10,
            }],
            "units": [{
                "unit_id": f"unit-{document_id}",
                "source_span_ids": [f"span-{document_id}"],
                "text": f"evidence-{document_id}",
            }],
            "candidates": [{
                "id": f"candidate-{document_id}",
                "candidate_type": "statement",
                "evidence_text": f"evidence-{document_id}",
                "statement": {"text": f"fact-{document_id}"},
                "extraction_method": ["test"],
            }],
            "entities": entities,
            "relations": relations,
            "statements": [{
                "id": f"statement-{document_id}",
                "subject_id": "entity-a",
                "statement_text": f"fact-{document_id}",
            }],
        }

    @staticmethod
    def _save(repository: KnowledgeRepository, bundle: dict[str, object]) -> None:
        repository.save_bundle(
            bundle["document"], bundle["spans"], bundle["units"],
            bundle["candidates"], bundle["entities"], bundle["relations"],
            bundle["statements"],
        )

    def test_reprocessing_removes_only_current_document_relations(self):
        with tempfile.TemporaryDirectory() as temp:
            db, repository = self._repository(Path(temp))
            self._save(repository, self._bundle("doc-1"))
            self._save(repository, self._bundle("doc-2"))

            self._save(
                repository,
                self._bundle("doc-1", include_b=False, include_relation=False),
            )

            relations = db.query(
                "SELECT id, document_id FROM relations ORDER BY document_id"
            )
            self.assertEqual(relations, [{"id": "relation-doc-2", "document_id": "doc-2"}])
            self.assertEqual(db.query("SELECT COUNT(*) AS count FROM entities")[0]["count"], 2)
            self.assertEqual(
                db.query("SELECT COUNT(*) AS count FROM knowledge_candidates WHERE document_id='doc-1'")[0]["count"],
                1,
            )

    def test_reprocessing_failure_restores_the_previous_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            db, repository = self._repository(Path(temp))
            original = self._bundle("doc-1")
            self._save(repository, original)
            before_relation = db.query("SELECT * FROM relations WHERE document_id='doc-1'")
            before_candidate = db.query("SELECT * FROM knowledge_candidates WHERE document_id='doc-1'")
            before_document = db.query("SELECT * FROM documents WHERE id='doc-1'")

            broken = self._bundle("doc-1", include_b=False, include_relation=False)
            broken["candidates"] = [{"id": "broken-candidate"}]
            with self.assertRaises(KeyError):
                self._save(repository, broken)

            self.assertEqual(db.query("SELECT * FROM relations WHERE document_id='doc-1'"), before_relation)
            self.assertEqual(
                db.query("SELECT * FROM knowledge_candidates WHERE document_id='doc-1'"),
                before_candidate,
            )
            self.assertEqual(db.query("SELECT * FROM documents WHERE id='doc-1'"), before_document)

    def test_reprocessing_same_bundle_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            db, repository = self._repository(Path(temp))
            bundle = self._bundle("doc-1")
            self._save(repository, bundle)
            tables = (
                "documents", "evidence_spans", "evidence_units",
                "knowledge_candidates", "entities", "relations",
                "statements", "graph_outbox",
            )
            before = {
                table: db.query(f"SELECT COUNT(*) AS count FROM {table}")[0]["count"]
                for table in tables
            }

            self._save(repository, bundle)

            after = {
                table: db.query(f"SELECT COUNT(*) AS count FROM {table}")[0]["count"]
                for table in tables
            }
            self.assertEqual(after, before)

    def test_entity_sources_are_accumulated_across_documents(self):
        with tempfile.TemporaryDirectory() as temp:
            db, repository = self._repository(Path(temp))
            self._save(
                repository,
                self._bundle("doc-1", include_b=False, include_relation=False),
            )
            self._save(
                repository,
                self._bundle("doc-2", include_b=False, include_relation=False),
            )

            row = db.query("SELECT properties_json FROM entities WHERE id='entity-a'")[0]
            properties = json.loads(row["properties_json"])
            self.assertEqual(properties["source_document_id"], "doc-1")
            self.assertEqual(properties["source_document_ids"], ["doc-1", "doc-2"])


if __name__ == "__main__":
    unittest.main()
