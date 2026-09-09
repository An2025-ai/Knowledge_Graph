from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import ChatRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat")
def chat(payload: ChatRequest, request: Request):
    history = [
        {"role": item.role, "content": item.content[:8000]}
        for item in payload.history
    ]
    return request.app.state.chat.answer(payload.message, history=history)
