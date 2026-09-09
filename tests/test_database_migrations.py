"""Tests for the versioned local SQLite schema migrations."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.app.infrastructure.database import LocalDatabase
from backend.app.migrations.runner import MigrationError, MigrationRunner


ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "backend" / "app" / "schema.sql"
VERSIONS = ROOT / "backend" / "app" / "migrations" / "versions"


class DatabaseMigrationTests(unittest.TestCase):
    def test_empty_database_initializes_all_bundled_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")

            db.initialize()

            self.assertEqual(
                [row["version"] for row in db.query(
                    "SELECT version FROM schema_versions ORDER BY rowid"
                )],
                ["0001_initial", "0002_runtime_fields"],
            )
            self.assertIn(
                "status",
                {row["name"] for row in db.query("PRAGMA table_info(entities)")},
            )
            self.assertIn(
                "payload_json",
                {row["name"] for row in db.query("PRAGMA table_info(pipeline_jobs)")},
            )

    def test_transitional_database_is_upgraded(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")
            connection = db.connect()
            try:
                connection.executescript(
                    (VERSIONS / "0001_initial.sql").read_text(encoding="utf-8")
                )
                connection.execute(
                    "INSERT INTO schema_versions(version, applied_at) VALUES (?, ?)",
                    ("desktop-1.0.0", "2026-01-01T00:00:00Z"),
                )
                connection.commit()
            finally:
                connection.close()

            db.initialize(SCHEMA)

            versions = [row["version"] for row in db.query(
                "SELECT version FROM schema_versions ORDER BY rowid"
            )]
            self.assertEqual(versions, ["0001_initial", "0002_runtime_fields"])
            self.assertIn(
                "evidence_refs_json",
                {row["name"] for row in db.query(
                    "PRAGMA table_info(knowledge_candidates)"
                )},
            )
            self.assertIn(
                "mode",
                {row["name"] for row in db.query("PRAGMA table_info(chat_messages)")},
            )

    def test_current_snapshot_with_previous_marker_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")
            connection = db.connect()
            try:
                connection.executescript(SCHEMA.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_versions(version, applied_at) VALUES (?, ?)",
                    ("desktop-1.0.0", "2026-01-01T00:00:00Z"),
                )
                connection.commit()
            finally:
                connection.close()

            db.initialize(SCHEMA)

            self.assertEqual(
                [row["version"] for row in db.query(
                    "SELECT version FROM schema_versions ORDER BY rowid"
                )],
                ["0001_initial", "0002_runtime_fields"],
            )

    def test_repeated_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")
            db.initialize(SCHEMA)
            before = db.query(
                "SELECT name, type, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index') ORDER BY name"
            )
            versions_before = db.query(
                "SELECT version, applied_at FROM schema_versions ORDER BY rowid"
            )

            db.initialize(SCHEMA)

            self.assertEqual(before, db.query(
                "SELECT name, type, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index') ORDER BY name"
            ))
            self.assertEqual(versions_before, db.query(
                "SELECT version, applied_at FROM schema_versions ORDER BY rowid"
            ))

    def test_failed_migration_rolls_back_all_statements_in_that_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            versions = root / "versions"
            versions.mkdir()
            (versions / "0001_initial.sql").write_text(
                "CREATE TABLE schema_versions (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);\n"
                "CREATE TABLE base (id INTEGER PRIMARY KEY);\n",
                encoding="utf-8",
            )
            (versions / "0002_broken.sql").write_text(
                "ALTER TABLE base ADD COLUMN added TEXT;\n"
                "INSERT INTO missing_table(value) VALUES ('boom');\n",
                encoding="utf-8",
            )
            db = LocalDatabase(root / "knowledge.db")

            with self.assertRaises(sqlite3.OperationalError):
                MigrationRunner(db, versions).run()

            self.assertEqual(
                [row["version"] for row in db.query(
                    "SELECT version FROM schema_versions ORDER BY rowid"
                )],
                ["0001_initial"],
            )
            self.assertNotIn(
                "added",
                {row["name"] for row in db.query("PRAGMA table_info(base)")},
            )

    def test_unknown_future_version_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")
            db.initialize(SCHEMA)
            db.execute(
                "INSERT INTO schema_versions(version, applied_at) VALUES (?, ?)",
                ("9999_future", "2026-01-01T00:00:00Z"),
            )

            with self.assertRaises(MigrationError):
                db.initialize(SCHEMA)

    def test_schema_versions_follow_migration_filename_order(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LocalDatabase(Path(temp) / "knowledge.db")
            runner = MigrationRunner(db, VERSIONS)

            db.initialize(SCHEMA)

            expected = [migration.version for migration in runner.discover()]
            actual = [row["version"] for row in db.query(
                "SELECT version FROM schema_versions ORDER BY rowid"
            )]
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
