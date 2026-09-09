"""Application-level retrieval intent and scope handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...infrastructure.repositories import KnowledgeRepository


_OVERVIEW_PHRASES = (
    "\u77e5\u8bc6\u5e93\u6982\u89c8",
    "\u5de5\u4f5c\u533a\u6982\u89c8",
    "\u77e5\u8bc6\u5e93\u4e2d\u7684\u5185\u5bb9",
    "\u6570\u636e\u5e93\u4e2d\u7684\u5185\u5bb9",
    "\u5de5\u4f5c\u533a\u5185\u5bb9",
    "\u603b\u7ed3\u5f53\u524d\u77e5\u8bc6\u5e93",
    "\u4ecb\u7ecd\u5f53\u524d\u77e5\u8bc6\u5e93",
    "\u5f53\u524d\u77e5\u8bc6\u5e93\u6709\u54ea\u4e9b",
    "\u5f53\u524d\u5de5\u4f5c\u533a\u6709\u54ea\u4e9b",
)
_ENTITY_TYPE_MARKERS = {
    "\u4ea7\u54c1": {"product", "solution", "service"},
    "\u80fd\u529b": {"capability", "service"},
    "\u529f\u80fd": {"capability", "service"},
    "\u5ba2\u6237": {"customer", "audience"},
    "\u7528\u6237": {"customer", "audience"},
    "\u884c\u4e1a": {"industry", "organization", "audience"},
    "\u5e02\u573a": {"industry", "organization", "audience"},
}
_BRAND_MARKER = "\u54c1\u724c"
_DOCUMENT_MARKERS = (
    "\u6587\u6863",
    "\u8d44\u6599",
    "\u672c\u6587",
)
_NO_REFERENCE_WORDS = {
    "\u7684",
    "\u662f",
    "\u6709\u54ea\u4e9b",
    "\u4ec0\u4e48",
}


@dataclass(frozen=True)
class RetrievalIntent:
    overview: bool
    entity_types: frozenset[str]
    has_brand_scope: bool
    brand_reference: str | None
    has_document_scope: bool
    document_reference: str | None


class RetrievalService:
    """Classify retrieval intent before delegating execution to a repository."""

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        intent = self.classify(query)
        if intent.has_document_scope:
            if not intent.document_reference:
                return []
            document_id = self.repository.document_id_for_reference(
                intent.document_reference
            )
            if not document_id:
                return []
        else:
            document_id = None

        # Keep the existing simple repository contract for ordinary exact
        # searches.  No broad type query is allowed without an explicit
        # overview phrase or a concrete scope.
        if not intent.overview and not intent.has_brand_scope and not intent.has_document_scope:
            return self.repository.search(query, limit=limit)

        if intent.overview:
            return self.repository.search(
                query,
                limit=limit,
                overview=True,
                entity_types=intent.entity_types,
            )

        # Scoped list queries intentionally omit the full natural-language
        # sentence from the text match.  The parsed filters are the query;
        # an unknown brand/document therefore produces no rows instead of a
        # workspace-wide fallback.
        return self.repository.search_scoped(
            "",
            limit=limit,
            entity_types=intent.entity_types,
            brand_id=(
                intent.brand_reference
                if intent.has_brand_scope and intent.brand_reference is not None
                else ""
                if intent.has_brand_scope
                else None
            ),
            document_id=document_id,
        )

    @classmethod
    def classify(cls, query: str) -> RetrievalIntent:
        query = query.strip()
        has_brand_scope = _BRAND_MARKER in query
        has_document_scope = any(marker in query for marker in _DOCUMENT_MARKERS)
        entity_types: set[str] = set()
        for marker, values in _ENTITY_TYPE_MARKERS.items():
            if marker in query:
                entity_types.update(values)
        explicit_overview = any(phrase in query for phrase in _OVERVIEW_PHRASES)
        return RetrievalIntent(
            overview=explicit_overview and not has_brand_scope and not has_document_scope,
            entity_types=frozenset(entity_types),
            has_brand_scope=has_brand_scope,
            brand_reference=cls._brand_reference(query) if has_brand_scope else None,
            has_document_scope=has_document_scope,
            document_reference=cls._document_reference(query) if has_document_scope else None,
        )

    @staticmethod
    def _brand_reference(query: str) -> str | None:
        before = re.search(
            r"([A-Za-z0-9_\-\u4e00-\u9fff]{1,64})\s*\u54c1\u724c", query
        )
        if before:
            return before.group(1)
        after = re.search(
            r"\u54c1\u724c\s*(?:\u662f|\u4e3a|[:：])?\s*"
            r"([A-Za-z0-9_\-\u4e00-\u9fff]{1,64})",
            query,
        )
        if after and after.group(1) not in _NO_REFERENCE_WORDS:
            return after.group(1)
        return None

    @staticmethod
    def _document_reference(query: str) -> str | None:
        match = re.search(
            r"\u6587\u6863\s*(?:[:：]\s*)?([A-Za-z0-9_.\-]{1,128})",
            query,
        )
        return match.group(1) if match else None


__all__ = ["RetrievalIntent", "RetrievalService"]
