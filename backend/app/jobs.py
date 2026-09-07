"""Durable background pipeline jobs backed by SQLite."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .repositories import JobRepository
from .services.ingestion import DocumentIngestionService


class JobManager:
    def __init__(self, jobs: JobRepository, ingestion: DocumentIngestionService):
        self.jobs = jobs
        self.ingestion = ingestion
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="brand-atlas")
        self._recover()

    def submit_import(self, payload: dict[str, Any]) -> str:
        job_id = self.jobs.create("document_import", payload=payload)
        self.executor.submit(self._run_import, job_id, payload)
        return job_id

    def submit_reprocess(self, document_id: str) -> str:
        job_id = self.jobs.create("pipeline_run", document_id, {"document_id": document_id})
        self.executor.submit(self._run_reprocess, job_id, document_id)
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def _recover(self) -> None:
        """Requeue interrupted jobs after an application restart."""
        for job in self.jobs.recoverable():
            if job["job_type"] == "document_import":
                self.executor.submit(self._run_import, job["id"], job["payload"])
            elif job["job_type"] == "pipeline_run" and job.get("document_id"):
                self.executor.submit(self._run_reprocess, job["id"], job["document_id"])

    def _run_import(self, job_id: str, payload: dict[str, Any]) -> None:
        self.jobs.update(job_id, stage="importing", status="running", progress=8)
        try:
            result = self.ingestion.import_document(
                **payload,
                progress=lambda stage, progress: self.jobs.update(
                    job_id, stage=stage, status="running", progress=progress
                ),
            )
            self.jobs.update(job_id, stage="completed", status="completed", progress=100, result=result)
        except Exception as exc:
            self.jobs.update(job_id, stage="failed", status="failed", progress=100, error=str(exc))

    def _run_reprocess(self, job_id: str, document_id: str) -> None:
        self.jobs.update(job_id, stage="queued", status="running", progress=8)
        try:
            result = self.ingestion.reprocess(
                document_id,
                progress=lambda stage, progress: self.jobs.update(
                    job_id, stage=stage, status="running", progress=progress
                ),
            )
            self.jobs.update(job_id, stage="completed", status="completed", progress=100, result=result)
        except Exception as exc:
            self.jobs.update(job_id, stage="failed", status="failed", progress=100, error=str(exc))
