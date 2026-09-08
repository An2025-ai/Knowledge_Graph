"""Local document ingestion and knowledge construction orchestration.

The service owns the desktop persistence workflow. Extraction, normalization
and fusion are delegated to ``KnowledgeBuildPipeline`` so this boundary stays
independent from the retired ``legacy`` runtime.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from shared.extraction.evidence_parsing import merge_spans_to_unit_rows, parse_to_span_rows
from shared.knowledge.registry import get_common_registry

from ..config import RuntimeSettings
from ..repositories import KnowledgeRepository, stable_id, utc_now
from ..runtime_settings import SettingsStore
from .embedding import EmbeddingService
from .knowledge_pipeline import KnowledgeBuildPipeline


ProgressCallback = Callable[[str, int], None]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentIngestionService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding: EmbeddingService | None = None,
        settings: RuntimeSettings | None = None,
        *,
        settings_store: SettingsStore | None = None,
    ):
        self.repository = repository
        self.embedding = embedding
        self.settings_store = settings_store or SettingsStore(settings or RuntimeSettings())
        self.pipeline = KnowledgeBuildPipeline(settings_store=self.settings_store)

    def import_document(
        self,
        *,
        title: str | None,
        content: str | None,
        file_path: str | None,
        source_type: str,
        layer: str,
        brand_id: str | None,
        tenant_id: str,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if file_path:
            path = Path(file_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"document file not found: {path}")
            content = path.read_text(encoding="utf-8")
            source_path = str(path)
            resolved_title = title or path.name
        else:
            source_path = None
            resolved_title = title or "未命名文档"
        content = content or ""
        if not content.strip():
            raise ValueError("document content is empty")
        return self._process(
            title=resolved_title,
            content=content,
            source_path=source_path,
            source_type=source_type,
            layer=layer,
            brand_id=brand_id,
            tenant_id=tenant_id,
            progress=progress,
        )

    def reprocess(
        self, document_id: str, progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        document = self.repository.document(document_id)
        if not document:
            raise ValueError(f"document not found: {document_id}")
        return self._process(
            title=document["title"], content=document["content"],
            source_path=document.get("source_path"), source_type=document["source_type"],
            layer=document["layer"], brand_id=document.get("brand_id"),
            tenant_id=document.get("tenant_id") or "local", progress=progress,
            document_id=document_id, created_at=document["created_at"],
        )

    def _process(
        self,
        *,
        title: str,
        content: str,
        source_path: str | None,
        source_type: str,
        layer: str,
        brand_id: str | None,
        tenant_id: str,
        progress: ProgressCallback | None,
        document_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        get_common_registry().require_profile(layer)
        content_hash = _sha256(content)
        existing = self.repository.document_by_hash(content_hash)
        if existing and document_id is None:
            return {
                "document_id": existing["id"], "title": existing["title"],
                "content_hash": content_hash, "duplicate": True,
                "span_count": self._count("evidence_spans", existing["id"]),
                "unit_count": self._count("evidence_units", existing["id"]),
                "candidate_count": self._count("knowledge_candidates", existing["id"]),
            }

        now = utc_now()
        doc_id = document_id or stable_id("doc", content_hash)
        emit = progress or (lambda _stage, _value: None)
        emit("parsing", 20)
        spans = parse_to_span_rows(content)
        units = merge_spans_to_unit_rows(spans)

        emit("extracting", 48)
        build = self.pipeline.build(
            document_id=doc_id,
            content=content,
            units=units,
            layer=layer,
            brand_id=brand_id,
            tenant_id=tenant_id,
            content_hash=content_hash,
        )
        statements = self._statements(doc_id, spans, build.entities, content_hash)

        emit("saving", 78)
        document = {
            "id": doc_id, "title": title, "content": content,
            "source_path": source_path, "source_type": source_type,
            "layer": layer, "brand_id": brand_id, "tenant_id": tenant_id,
            "content_hash": content_hash, "status": "active",
            "created_at": created_at or now, "updated_at": now,
        }
        self.repository.save_bundle(
            document, spans, units, build.candidates, build.entities,
            build.relations, statements,
        )
        embedding_count = 0
        if self.embedding:
            try:
                embedding_count = self.embedding.index_units(units)
            except Exception:
                # Embeddings are optional; local graph construction remains usable.
                embedding_count = 0
        emit("completed", 100)
        return {
            "document_id": doc_id, "title": title, "content_hash": content_hash,
            "duplicate": False, "span_count": len(spans), "unit_count": len(units),
            "candidate_count": len(build.candidates), "entity_count": len(build.entities),
            "relation_count": len(build.relations), "statement_count": len(statements),
            "embedding_count": embedding_count, "llm_used": build.llm_used,
            "llm_attempted": build.llm_attempted,
            "llm_fallback_count": build.llm_fallback_count,
            "llm_error": build.llm_error,
            "layer": layer, "brand_id": brand_id,
        }

    def _count(self, table: str, document_id: str) -> int:
        row = self.repository.db.query(
            f"SELECT COUNT(*) AS count FROM {table} WHERE document_id=?", (document_id,)
        )
        return int(row[0]["count"]) if row else 0

    def _statements(
        self, doc_id: str, spans: list[dict[str, Any]],
        entities: list[dict[str, Any]], content_hash: str,
    ) -> list[dict[str, Any]]:
        subject_id = next((e["id"] for e in entities if e["type"] == "brand"), None)
        if not subject_id and entities:
            subject_id = entities[0]["id"]
        return [
            {
                "id": stable_id("stmt", doc_id, span["text"]),
                "subject_id": subject_id, "statement_text": span["text"],
                "statement_class": "observation",
                "properties": {
                    "source_span_id": span["span_id"],
                    "heading_path": span.get("heading_path", []),
                    "content_hash": content_hash,
                },
            }
            for span in spans[:200] if len(span.get("text", "").strip()) >= 8
        ]
