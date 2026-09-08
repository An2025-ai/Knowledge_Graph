"""Small SQLite infrastructure layer.

Repositories own SQL and this module owns connection policy.  Connections are
short-lived, WAL is enabled for the UI + worker combination, and every write
uses an explicit transaction.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class LocalDatabase:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, schema_path: Path | None = None) -> None:
        """Apply all bundled migrations before the application starts.

        ``schema_path`` remains in the signature for callers from the first
        desktop runtime. The migration directory is now the source of truth;
        ``schema.sql`` is retained as a complete inspection/snapshot file.
        """
        del schema_path
        from .migrations.runner import MigrationRunner

        MigrationRunner(
            self,
            Path(__file__).with_name("migrations") / "versions",
        ).run()

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        # sqlite3.Connection.__exit__ commits/rolls back but does not close the
        # connection. Close explicitly so Windows can rotate or back up the DB.
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount

    @staticmethod
    def json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)


def json_loads(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
