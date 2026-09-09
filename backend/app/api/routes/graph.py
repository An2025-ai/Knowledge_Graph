from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("")
def graph(
    request: Request,
    layer: str | None = Query(default=None),
    brand_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
):
    return request.app.state.knowledge.graph(layer=layer, brand_id=brand_id, limit=limit)


@router.get("/search")
def search(request: Request, q: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=100)):
    return {"query": q, "items": request.app.state.knowledge.search(q, limit)}
