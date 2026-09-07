"""Local document ingestion service.

This service composes the pure parsing/extraction primitives from
``shared`` but owns the desktop persistence workflow.  It deliberately does
not import PostgreSQL, Neo4j, PaddlePaddle, or a local model.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from shared.knowledge.registry import get_common_registry
from shared.extraction.candidate_extraction import pre_extract
from shared.extraction.evidence_parsing import merge_spans_to_unit_rows, parse_to_span_rows

from ..repositories import KnowledgeRepository, stable_id, utc_now
from .embedding import EmbeddingService


ProgressCallback = Callable[[str, int], None]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip(" \t\r\n:：，,、;；。"))


def _items(value: str) -> list[str]:
    """Turn a short Chinese/English list into bounded graph labels."""
    result: list[str] = []
    for item in re.split(r"[、,，/；;|]|\s+和\s+|\s+及\s+", value):
        item = _clean(item)
        item = re.sub(r"^(包括|主要包括|支持|提供|具备|拥有)\s*", "", item)
        if 2 <= len(item) <= 48 and item not in result:
            result.append(item)
    return result[:20]


class DocumentIngestionService:
    def __init__(self, repository: KnowledgeRepository, embedding: EmbeddingService | None = None):
        self.repository = repository
        self.embedding = embedding

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
        profile_id = layer
        get_common_registry().require_profile(profile_id)
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
        candidates = self._candidates(doc_id, layer, content_hash, units)
        entities, relations = self._graph_facts(
            doc_id, content, layer, brand_id, tenant_id, content_hash
        )
        statements = self._statements(doc_id, spans, entities, content_hash)

        emit("saving", 78)
        document = {
            "id": doc_id, "title": title, "content": content,
            "source_path": source_path, "source_type": source_type,
            "layer": layer, "brand_id": brand_id, "tenant_id": tenant_id,
            "content_hash": content_hash, "status": "active",
            "created_at": created_at or now, "updated_at": now,
        }
        self.repository.save_bundle(
            document, spans, units, candidates, entities, relations, statements
        )
        embedding_count = 0
        if self.embedding:
            try:
                embedding_count = self.embedding.index_units(units)
            except Exception:
                # Embeddings are an optional enhancement; local ingestion must
                # remain usable when a remote provider is unavailable.
                embedding_count = 0
        emit("completed", 100)
        return {
            "document_id": doc_id, "title": title, "content_hash": content_hash,
            "duplicate": False, "span_count": len(spans), "unit_count": len(units),
            "candidate_count": len(candidates), "entity_count": len(entities),
            "relation_count": len(relations), "statement_count": len(statements),
            "embedding_count": embedding_count,
            "layer": layer, "brand_id": brand_id,
        }

    def _count(self, table: str, document_id: str) -> int:
        row = self.repository.db.query(
            f"SELECT COUNT(*) AS count FROM {table} WHERE document_id=?", (document_id,)
        )
        return int(row[0]["count"]) if row else 0

    def _candidates(
        self, document_id: str, layer: str, content_hash: str, units: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for unit in units:
            for candidate in pre_extract(unit.get("text", ""), profile_id=layer):
                payload = candidate.get("candidate_payload") or {}
                candidate_id = stable_id(
                    "kc", document_id, candidate.get("candidate_type"),
                    candidate.get("generator"), payload.get("value"), payload.get("trigger"),
                )
                candidates.append({
                    "id": candidate_id,
                    "candidate_type": candidate.get("candidate_type", "statement"),
                    "subject": {"name": payload.get("name"), "entity_type": payload.get("entity_type")},
                    "predicate_type": payload.get("type"),
                    "object": {}, "metric": payload if candidate.get("candidate_type") == "metric" else {},
                    "statement": {"text": payload.get("value", "")},
                    "evidence_text": unit.get("text", "")[:4000],
                    "confidence": candidate.get("confidence", 0.5),
                    "extraction_method": [candidate.get("generator", "rule")],
                    "content_hash": content_hash,
                })
        return candidates

    def _entity(
        self, doc_id: str, layer: str, entity_type: str, name: str,
        brand_id: str | None, tenant_id: str, content_hash: str,
    ) -> dict[str, Any]:
        name = _clean(name)
        return {
            "id": stable_id("ent", layer, brand_id or "", entity_type, name),
            "type": entity_type, "name": name, "layer": layer,
            "brand_id": brand_id, "tenant_id": tenant_id,
            "properties": {"source_document_id": doc_id, "content_hash": content_hash},
        }

    def _graph_facts(
        self, doc_id: str, content: str, layer: str, brand_id: str | None,
        tenant_id: str, content_hash: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        entities: dict[str, dict[str, Any]] = {}

        def add(entity_type: str, name: str) -> dict[str, Any] | None:
            name = _clean(name)
            if not name:
                return None
            entity = self._entity(doc_id, layer, entity_type, name, brand_id, tenant_id, content_hash)
            entities[entity["id"]] = entity
            return entity

        brand = add("brand", brand_id) if layer == "l3_brand" and brand_id else None
        for name in re.findall(r"[\u4e00-\u9fffA-Za-z0-9·（）()]{2,32}?(?:有限公司|公司|集团)", content):
            add("organization", name)

        product_names: list[str] = []
        for match in re.findall(
            r"[A-Za-z0-9\u4e00-\u9fff·（）()\-]{2,32}?(?:平台|系统|智能体|工厂|解决方案|产品)",
            content,
        ):
            name = _clean(match)
            if name and name not in product_names:
                product_names.append(name)
                add("product", name)

        capabilities: list[str] = []
        for sentence in re.findall(r"(?:支持|提供|具备|拥有|包括)([^。；\n]{2,160})", content):
            for name in _items(sentence):
                if name not in product_names and name not in capabilities:
                    capabilities.append(name)
                    add("capability", name)

        audiences: list[str] = []
        for sentence in re.findall(r"(?:面向|服务|针对|覆盖)([^。；\n]{2,100})", content):
            for name in _items(sentence):
                if name not in audiences:
                    audiences.append(name)
                    add("audience", name)

        relations: list[dict[str, Any]] = []

        def link(source: dict[str, Any] | None, target: dict[str, Any] | None, relation_type: str):
            if not source or not target or source["id"] == target["id"]:
                return
            relations.append({
                "id": stable_id("rel", source["id"], target["id"], relation_type, doc_id),
                "source_id": source["id"], "target_id": target["id"],
                "relation_type": relation_type,
                "confidence": 0.72,
                "properties": {"source_document_id": doc_id, "extraction": "rule"},
            })

        anchor = brand
        if anchor is None and entities:
            anchor = next(iter(entities.values()))
        products = [e for e in entities.values() if e["type"] == "product"]
        caps = [e for e in entities.values() if e["type"] == "capability"]
        auds = [e for e in entities.values() if e["type"] == "audience"]
        for product in products:
            link(anchor, product, "offers")
            for capability in caps:
                link(product, capability, "has_capability")
        if not products:
            for capability in caps:
                link(anchor, capability, "has_capability")
        for audience in auds:
            link(anchor, audience, "serves")
        return list(entities.values()), relations

    def _statements(
        self, doc_id: str, spans: list[dict[str, Any]], entities: list[dict[str, Any]], content_hash: str
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
