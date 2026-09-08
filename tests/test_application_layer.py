import time
import unittest
from pathlib import Path

from backend.app.application.jobs import JobManager
from backend.app.application.services.agent import AgentService
from backend.app.config import RuntimeSettings


class FakeJobRepository:
    def __init__(self, recoverable=None):
        self.jobs = {}
        self.created = []
        self.updates = []
        self._next_id = 1
        self._recoverable = list(recoverable or [])

    def create(self, job_type, document_id=None, payload=None):
        job_id = f"job-{self._next_id}"
        self._next_id += 1
        self.created.append((job_id, job_type, document_id, payload or {}))
        self.jobs[job_id] = {
            "id": job_id,
            "job_type": job_type,
            "document_id": document_id,
            "payload": payload or {},
            "status": "queued",
        }
        return job_id

    def update(self, job_id, *, stage, status, progress, result=None, error=None):
        self.updates.append((job_id, stage, status, progress, result, error))
        self.jobs.setdefault(job_id, {})["status"] = status
        self.jobs[job_id]["stage"] = stage
        self.jobs[job_id]["progress"] = progress

    def get(self, job_id):
        return self.jobs.get(job_id)

    def recoverable(self):
        return self._recoverable


class FakeIngestion:
    def __init__(self):
        self.imports = []
        self.reprocesses = []

    def import_document(self, **payload):
        self.imports.append(payload)
        progress = payload.get("progress")
        if progress:
            progress("extracting", 48)
        return {"document_id": "doc-imported"}

    def reprocess(self, document_id, progress=None):
        self.reprocesses.append(document_id)
        if progress:
            progress("saving", 78)
        return {"document_id": document_id}


class FakeKnowledgeRepository:
    def search(self, query, limit=8):
        return [{"kind": "entity", "id": "entity-1", "title": "Acme", "snippet": "Acme 是测试实体。"}]


class ApplicationLayerTests(unittest.TestCase):
    def _wait_for_status(self, repository, job_id, status="completed"):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if repository.get(job_id,).get("status") == status:
                return
            time.sleep(0.01)
        self.fail(f"job {job_id} did not reach {status}: {repository.get(job_id)}")

    def _manager(self, jobs=None, ingestion=None):
        jobs = jobs or FakeJobRepository()
        ingestion = ingestion or FakeIngestion()
        manager = JobManager(jobs, ingestion)
        self.addCleanup(manager.executor.shutdown, wait=True, cancel_futures=True)
        return manager, jobs, ingestion

    def test_import_job_is_created_and_executed(self):
        manager, jobs, ingestion = self._manager()

        job_id = manager.submit_import({"title": "测试文档", "content": "内容"})

        self._wait_for_status(jobs, job_id)
        self.assertEqual(jobs.created[0][1], "document_import")
        self.assertEqual(ingestion.imports[0]["title"], "测试文档")
        self.assertEqual(jobs.get(job_id)["progress"], 100)

    def test_reprocess_job_is_created_and_executed(self):
        manager, jobs, ingestion = self._manager()

        job_id = manager.submit_reprocess("doc-existing")

        self._wait_for_status(jobs, job_id)
        self.assertEqual(jobs.created[0][1], "pipeline_run")
        self.assertEqual(ingestion.reprocesses, ["doc-existing"])

    def test_queued_job_is_recovered_after_startup(self):
        jobs = FakeJobRepository([
            {
                "id": "job-recovered",
                "job_type": "document_import",
                "document_id": None,
                "payload": {"title": "恢复文档", "content": "内容"},
            }
        ])
        ingestion = FakeIngestion()
        manager, jobs, ingestion = self._manager(jobs, ingestion)

        self._wait_for_status(jobs, "job-recovered")
        self.assertEqual(ingestion.imports[0]["title"], "恢复文档")

    def test_application_agent_can_answer_from_local_knowledge(self):
        service = AgentService(FakeKnowledgeRepository(), RuntimeSettings())

        result = service.answer("Acme 是什么？")

        self.assertEqual(result["mode"], "local_retrieval")
        self.assertEqual(result["sources"][0]["id"], "entity-1")

    def test_new_entry_points_are_canonical(self):
        from backend.app.application.services.agent import AgentService as NewAgentService
        from backend.app.application.services.ingestion import DocumentIngestionService as NewIngestion
        from backend.app.application.services.knowledge_pipeline import KnowledgeBuildPipeline as NewPipeline
        from backend.app.infrastructure.database import LocalDatabase
        from backend.app.infrastructure.providers.embedding import EmbeddingService
        from backend.app.infrastructure.providers.llm import OpenAICompatibleClient
        from backend.app.infrastructure.repositories import KnowledgeRepository

        self.assertIsNotNone(JobManager)
        self.assertIsNotNone(NewAgentService)
        self.assertIsNotNone(NewIngestion)
        self.assertIsNotNone(NewPipeline)
        self.assertIsNotNone(LocalDatabase)
        self.assertIsNotNone(EmbeddingService)
        self.assertIsNotNone(OpenAICompatibleClient)
        self.assertIsNotNone(KnowledgeRepository)

        repository = Path(__file__).resolve().parents[1]
        removed = (
            repository / "backend" / "app" / "jobs.py",
            repository / "backend" / "app" / "database.py",
            repository / "backend" / "app" / "repositories.py",
            repository / "backend" / "app" / "services" / "agent.py",
            repository / "backend" / "app" / "services" / "embedding.py",
            repository / "backend" / "app" / "services" / "ingestion.py",
            repository / "backend" / "app" / "services" / "knowledge_pipeline.py",
            repository / "backend" / "app" / "services" / "llm.py",
        )
        for path in removed:
            self.assertFalse(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
