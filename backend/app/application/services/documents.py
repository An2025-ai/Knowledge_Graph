"""Application use cases for document queries."""

from __future__ import annotations

from typing import Any

from ...infrastructure.repositories import KnowledgeRepository


class DocumentQueryService:
    """Expose document reads without leaking persistence details to routes."""

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def list_documents(self) -> list[dict[str, Any]]:
        return self.repository.list_documents()