from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..schemas import ChatRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat")
def chat(payload: ChatRequest, request: Request):
    history = [
        {"role": item.role, "content": item.content[:8000]}
        for item in payload.history
    ]
    result = request.app.state.agent.answer(payload.message, history=history)
    now = datetime.now(timezone.utc).isoformat()
    request.app.state.db.execute(
        "INSERT INTO chat_messages(id,role,content,citations_json,created_at) VALUES (?,?,?,?,?)",
        (uuid.uuid4().hex, "user", payload.message, "[]", now),
    )
    request.app.state.db.execute(
        "INSERT INTO chat_messages(id,role,content,citations_json,created_at) VALUES (?,?,?,?,?)",
        (
            uuid.uuid4().hex,
            "assistant",
            result["answer"],
            json.dumps([source["id"] for source in result.get("sources", []) if source.get("id")]),
            now,
        ),
    )
    return result
