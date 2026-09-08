from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import config
from backend.app.config import AppPaths, default_database_path


class AppPathsTests(unittest.TestCase):
    def _environment(self, **values: str):
        base = {"LOCALAPPDATA": ""}
        base.update(values)
        return patch.dict(os.environ, base, clear=True)

    def test_default_database_uses_user_data_root(self):
        with tempfile.TemporaryDirectory() as td, self._environment(LOCALAPPDATA=td):
            paths = AppPaths.from_environment()

            expected_root = Path(td).resolve() / "BrandAtlas"
            self.assertEqual(paths.root, expected_root)
            self.assertEqual(paths.database, expected_root / "database" / "knowledge.db")

    def test_data_dir_contains_all_runtime_paths(self):
        with tempfile.TemporaryDirectory() as td, self._environment(
            BRAND_ATLAS_DATA_DIR=td
        ):
            paths = AppPaths.from_environment()
            root = Path(td).resolve()

            self.assertEqual(paths.root, root)
            for path in (
                paths.database,
                paths.documents,
                paths.vectors,
                paths.cache,
                paths.logs,
                paths.backups,
                paths.config,
            ):
                self.assertTrue(path == root or root in path.parents, path)
            self.assertEqual(paths.database, root / "database" / "knowledge.db")
            self.assertEqual(paths.config, root / "config")

    def test_database_path_only_overrides_database_file(self):
        with tempfile.TemporaryDirectory() as td:
            database = Path(td) / "separate" / "knowledge.db"
            with self._environment(
                LOCALAPPDATA=td,
                BRAND_ATLAS_DATABASE_PATH=str(database),
            ):
                paths = AppPaths.from_environment()

            self.assertEqual(paths.database, database.resolve())
            self.assertEqual(paths.root, (Path(td) / "BrandAtlas").resolve())
            self.assertEqual(paths.documents, paths.root / "documents")
            self.assertEqual(paths.config, paths.root / "config")

    def test_database_path_has_priority_over_data_dir(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as data_td:
            database = Path(td) / "knowledge.db"
            with self._environment(
                BRAND_ATLAS_DATA_DIR=data_td,
                BRAND_ATLAS_DATABASE_PATH=str(database),
            ):
                paths = AppPaths.from_environment()

            self.assertEqual(paths.root, Path(data_td).resolve())
            self.assertEqual(paths.database, database.resolve())

    def test_ensure_creates_runtime_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "BrandAtlas"
            paths = AppPaths(
                root=root,
                database=root / "database" / "knowledge.db",
                documents=root / "documents",
                vectors=root / "vectors",
                cache=root / "cache",
                logs=root / "logs",
                backups=root / "backups",
                config=root / "config",
            )

            paths.ensure()

            for directory in (
                paths.root,
                paths.database.parent,
                paths.documents,
                paths.vectors,
                paths.cache,
                paths.logs,
                paths.backups,
                paths.config,
            ):
                self.assertTrue(directory.is_dir(), directory)

    def test_database_path_does_not_use_pyinstaller_file_location(self):
        with tempfile.TemporaryDirectory() as data_td, tempfile.TemporaryDirectory() as unpack_td:
            with self._environment(BRAND_ATLAS_DATA_DIR=data_td), patch.object(
                config, "__file__", str(Path(unpack_td) / "internal" / "config.py")
            ):
                database = default_database_path(Path(data_td).resolve())

            self.assertEqual(database, Path(data_td).resolve() / "database" / "knowledge.db")
            self.assertNotIn(Path(unpack_td).resolve(), database.parents)


if __name__ == "__main__":
    unittest.main()
