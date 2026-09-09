from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schemas import ImportRequest, PipelineRequest

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("")
def list_documents(request: Request):
    return request.app.state.document_queries.list_documents()


@router.get("/{document_id}")
def get_document(document_id: str, request: Request):
    document = request.app.state.knowledge.document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    document.pop("content", None)
    return document


@router.post("/import")
def import_document(payload: ImportRequest, request: Request):
    job_id = request.app.state.jobs.submit_import(payload.model_dump())
    return {"job_id": job_id, "status": "queued"}


@router.post("/{document_id}/run")
def run_pipeline(document_id: str, payload: PipelineRequest, request: Request):
    if document_id != payload.document_id:
        raise HTTPException(status_code=400, detail="document_id does not match path")
    if not request.app.state.knowledge.document(document_id):
        raise HTTPException(status_code=404, detail="document not found")
    return {"job_id": request.app.state.jobs.submit_reprocess(document_id), "status": "queued"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
