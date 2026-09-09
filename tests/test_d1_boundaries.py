"""Regression tests for the D1 application/infrastructure boundaries."""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.application.services.chat import ChatService
from backend.app.config import AppPaths, RuntimeSettings
from backend.app.factory import create_app
from backend.app.infrastructure.database import LocalDatabase
from backend.app.infrastructure.repositories import ChatRepository


class D1BoundaryTests(unittest.TestCase):
    @staticmethod
    def _paths(root: Path) -> AppPaths:
        return AppPaths(
            root,
            root / "database" / "knowledge.db",
            root / "documents",
            root / "vectors",
            root / "cache",
            root / "logs",
            root / "backups",
            root / "config",
        )

    @staticmethod
    def _database(paths: AppPaths) -> LocalDatabase:
        database = LocalDatabase(paths.database)
        database.initialize()
        return database

    def test_document_list_keeps_fields_order_and_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            database = self._database(paths)
            for index in range(105):
                database.execute(
                    "INSERT INTO documents "
                    "(id,title,content,source_type,layer,content_hash,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        f"doc-{index}", f"Document {index}", "content", "test",
                        "l3_brand", f"hash-{index}", "active",
                        f"created-{index:03d}", f"updated-{index:03d}",
                    ),
                )

            app = create_app(paths=paths, settings=RuntimeSettings(token="test-token"))
            with TestClient(app) as client:
                response = client.get(
                    "/api/documents",
                    headers={"Authorization": "Bearer test-token"},
                )

            self.assertEqual(response.status_code, 200)
            documents = response.json()
            self.assertEqual(len(documents), 100)
            self.assertEqual([item["id"] for item in documents], [f"doc-{i}" for i in range(104, 4, -1)])
            self.assertEqual(
                set(documents[0]),
                {"id", "title", "source_type", "layer", "brand_id", "content_hash", "status", "created_at", "updated_at"},
            )

    def test_chat_route_persists_exactly_one_exchange(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            app = create_app(paths=paths, settings=RuntimeSettings(token="test-token"))
            with TestClient(app) as client:
                response = client.post(
                    "/api/agent/chat",
                    headers={"Authorization": "Bearer test-token"},
                    json={"message": "你好"},
                )

            self.assertEqual(response.status_code, 200)
            database = LocalDatabase(paths.database)
            rows = database.query(
                "SELECT role,content,citations_json,mode FROM chat_messages ORDER BY rowid"
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
            self.assertEqual(rows[0]["content"], "你好")
            self.assertEqual(rows[0]["citations_json"], "[]")
            self.assertEqual(rows[0]["mode"], "user")
            self.assertEqual(rows[1]["mode"], "local_retrieval")

    def test_chat_repository_rolls_back_when_assistant_insert_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            database = self._database(paths)
            repository = ChatRepository(database)
            user = {
                "id": "user-message",
                "role": "user",
                "content": "hello",
                "citations": [],
                "mode": "user",
                "created_at": "now",
            }
            assistant = {
                "id": "assistant-message",
                "role": "assistant",
                "content": "answer",
                "citations": [],
                "mode": None,
                "created_at": "now",
            }

            with self.assertRaises(sqlite3.IntegrityError):
                repository.save_exchange(user, assistant)

            self.assertEqual(
                database.query("SELECT COUNT(*) AS count FROM chat_messages")[0]["count"],
                0,
            )

    def test_chat_save_failure_is_not_returned_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self._paths(Path(temp))
            app = create_app(paths=paths, settings=RuntimeSettings(token="test-token"))
            with TestClient(app, raise_server_exceptions=False) as client:
                with mock.patch.object(
                    app.state.chat.repository,
                    "save_exchange",
                    side_effect=RuntimeError("database write failed"),
                ):
                    response = client.post(
                        "/api/agent/chat",
                        headers={"Authorization": "Bearer test-token"},
                        json={"message": "你好"},
                    )

            self.assertGreaterEqual(response.status_code, 500)
            database = LocalDatabase(paths.database)
            self.assertEqual(
                database.query("SELECT COUNT(*) AS count FROM chat_messages")[0]["count"],
                0,
            )

    def test_chat_generation_precedes_repository_write(self):
        events: list[str] = []

        class FakeAgent:
            def answer(self, message, history=None):
                events.append("generate")
                return {"answer": "ok", "mode": "local_retrieval", "sources": []}

        class FakeRepository:
            def save_exchange(self, user_message, assistant_message):
                events.append("save")

        result = ChatService(FakeAgent(), FakeRepository()).answer("hello")

        self.assertEqual(result["answer"], "ok")
        self.assertEqual(events, ["generate", "save"])

    def test_routes_do_not_access_database_connection_directly(self):
        documents_source = inspect.getsource(__import__("backend.app.api.routes.documents", fromlist=["router"]))
        agent_source = inspect.getsource(__import__("backend.app.api.routes.agent", fromlist=["router"]))
        self.assertNotIn("state.db", documents_source)
        self.assertNotIn("state.db", agent_source)
        self.assertNotIn("INSERT INTO", documents_source)
        self.assertNotIn("INSERT INTO", agent_source)

        with tempfile.TemporaryDirectory() as temp:
            app = create_app(paths=self._paths(Path(temp)), settings=RuntimeSettings(token="test-token"))
            self.assertFalse(hasattr(app.state, "db"))


if __name__ == "__main__":
    unittest.main()