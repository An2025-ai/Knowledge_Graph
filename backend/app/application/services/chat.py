"""Chat application orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ...infrastructure.repositories import ChatRepository
from .agent import AgentService


class ChatService:
    """Generate an answer, then persist the complete exchange atomically."""

    def __init__(self, agent: AgentService, repository: ChatRepository):
        self.agent = agent
        self.repository = repository

    def answer(
        self, message: str, history: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        # The model call happens before ChatRepository opens its write
        # transaction, so model latency never holds a SQLite write lock.
        result = self.agent.answer(message, history=history)
        now = datetime.now(timezone.utc).isoformat()
        citations = [
            source["id"]
            for source in result.get("sources", [])
            if source.get("id")
        ]
        self.repository.save_exchange(
            {
                "id": uuid.uuid4().hex,
                "role": "user",
                "content": message,
                "citations": [],
                "mode": "user",
                "created_at": now,
            },
            {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": result["answer"],
                "citations": citations,
                "mode": result.get("mode", "unknown"),
                "created_at": now,
            },
        )
        return result