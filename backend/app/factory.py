"""FastAPI composition root and localhost security boundary."""

from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import AppPaths, RuntimeSettings, load_settings
from .infrastructure.database import LocalDatabase
from .application.jobs import JobManager
from .application.services.chat import ChatService
from .application.services.documents import DocumentQueryService
from .infrastructure.repositories import ChatRepository, JobRepository, KnowledgeRepository
from .api.routes import agent, documents, graph, system
from .runtime_settings import SettingsStore
from .application.services.agent import AgentService
from .infrastructure.providers.embedding import EmbeddingService
from .application.services.ingestion import DocumentIngestionService


def create_app(
    *, paths: AppPaths | None = None, settings: RuntimeSettings | None = None
) -> FastAPI:
    paths = (paths or AppPaths.from_environment()).ensure()
    settings = settings or load_settings(paths)
    settings_store = SettingsStore(settings, paths)
    db = LocalDatabase(paths.database)
    db.initialize(Path(__file__).with_name("schema.sql"))
    knowledge = KnowledgeRepository(db)
    jobs = JobRepository(db)
    embedding = EmbeddingService(knowledge, settings_store=settings_store)
    ingestion = DocumentIngestionService(
        knowledge, embedding, settings_store=settings_store
    )
    manager = JobManager(jobs, ingestion)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        application.state.jobs.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(
        title="Brand Atlas Local API",
        version="0.1.1",
        description="Local-first knowledge graph and agent runtime.",
        lifespan=lifespan,
    )
    app.state.paths = paths
    app.state.settings_store = settings_store
    app.state.knowledge = knowledge
    app.state.jobs = manager
    app.state.ingestion = ingestion
    app.state.embedding = embedding
    agent_service = AgentService(knowledge, settings_store=settings_store)
    app.state.agent = agent_service
    app.state.document_queries = DocumentQueryService(knowledge)
    app.state.chat = ChatService(agent_service, ChatRepository(db))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def local_token_guard(request: Request, call_next):
        # CORS preflight cannot carry the bearer token. Let the CORS middleware
        # answer OPTIONS before enforcing the token on the actual API call.
        if request.method == "OPTIONS":
            return await call_next(request)
        # Health remains public so the desktop shell can discover readiness.
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            expected = request.app.state.settings_store.snapshot().token
            received = request.headers.get("authorization", "")
            if expected and received != f"Bearer {expected}":
                return JSONResponse(status_code=401, content={"detail": "invalid local session token"})
        return await call_next(request)

    app.include_router(system.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")

    @app.get("/")
    def root():
        return {"service": "brand-atlas-local", "docs": "/docs", "api": "/api/health"}

    return app
