"""Tests for the standard-library maintenance utilities."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.infrastructure.database import LocalDatabase
from scripts.maintenance.backup_database import backup_database
from scripts.maintenance.show_runtime_paths import runtime_paths
from scripts.maintenance.verify_database import verify_database


class MaintenanceScriptTests(unittest.TestCase):
    def test_script_layout_uses_classified_directories(self):
        repository = Path(__file__).resolve().parents[1]
        expected = (
            repository / "scripts" / "dev" / "dev-desktop.ps1",
            repository / "scripts" / "dev" / "dev-local.ps1",
            repository / "scripts" / "build" / "build-sidecar.ps1",
            repository / "scripts" / "build" / "prepare-tauri-sidecar.ps1",
            repository / "scripts" / "build" / "create-tauri-icon.py",
            repository / "scripts" / "build" / "build_layered_prototype.py",
            repository / "scripts" / "build" / "render_graph.py",
            repository / "scripts" / "maintenance" / "fix_html_stale.py",
            repository / "scripts" / "maintenance" / "fix_html_cdn.py",
        )
        for path in expected:
            self.assertTrue(path.is_file(), path)

        old_paths = (
            repository / "scripts" / "dev-desktop.ps1",
            repository / "scripts" / "dev-local.ps1",
            repository / "scripts" / "build-sidecar.ps1",
            repository / "scripts" / "prepare-tauri-sidecar.ps1",
            repository / "scripts" / "create-tauri-icon.py",
            repository / "scripts" / "build_layered_prototype.py",
            repository / "scripts" / "render_graph.py",
            repository / "scripts" / "fix_html_stale.py",
            repository / "scripts" / "fix_html_cdn.py",
        )
        for path in old_paths:
            self.assertFalse(path.exists(), path)

    def test_backup_uses_sqlite_backup_api_and_is_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.db"
            destination = root / "backups" / "knowledge.db"
            database = LocalDatabase(source)
            database.initialize()
            database.execute("CREATE TABLE backup_marker (value TEXT NOT NULL)")
            database.execute("INSERT INTO backup_marker(value) VALUES ('ok')")

            result = backup_database(source, destination)

            self.assertEqual(result, destination)
            self.assertTrue(destination.is_file())
            connection = sqlite3.connect(destination)
            try:
                self.assertEqual(
                    connection.execute("SELECT value FROM backup_marker").fetchone()[0],
                    "ok",
                )
            finally:
                connection.close()
            self.assertEqual(verify_database(destination)["status"], "ok")

    def test_verify_reports_missing_database_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "missing.db"

            report = verify_database(database)

            self.assertEqual(report["status"], "error")
            self.assertEqual(report["error"], "database_not_found")
            self.assertFalse(database.exists())

    def test_show_runtime_paths_respects_overrides_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runtime"
            database = root / "custom" / "knowledge.db"
            with patch.dict(
                os.environ,
                {
                    "BRAND_ATLAS_DATA_DIR": str(root),
                    "BRAND_ATLAS_DATABASE_PATH": str(database),
                },
                clear=False,
            ):
                report = runtime_paths()

            self.assertEqual(report["root"], str(root.resolve()))
            self.assertEqual(report["database"], str(database.resolve()))
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
