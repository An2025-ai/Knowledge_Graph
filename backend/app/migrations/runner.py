"""Transactional runner for the bundled SQLite schema migrations."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ..database import LocalDatabase


LEGACY_SCHEMA_VERSION = "desktop-1.0.0"
_MIGRATION_NAME = re.compile(r"^(\d{4}_[a-z0-9_]+)\.sql$")
_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"ADD\s+COLUMN\s+(?P<column>[A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE | re.DOTALL,
)


class MigrationError(RuntimeError):
    """Raised when a database cannot be safely brought to the bundled schema."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


class MigrationRunner:
    def __init__(self, database: "LocalDatabase", versions_dir: Path):
        self.database = database
        self.versions_dir = Path(versions_dir)

    def run(self) -> None:
        migrations = self.discover()
        if not migrations:
            raise MigrationError(f"no SQLite migrations found in {self.versions_dir}")

        versions = [migration.version for migration in migrations]
        applied = self._read_applied_versions()
        normalized = [
            versions[0] if version == LEGACY_SCHEMA_VERSION else version
            for version in applied
        ]
        unknown = [version for version in normalized if version not in versions]
        if unknown:
            raise MigrationError(
                "database contains unknown schema version(s): " + ", ".join(unknown)
            )
        if len(set(normalized)) != len(normalized):
            raise MigrationError("schema_versions contains duplicate versions")
        if normalized != versions[: len(normalized)]:
            raise MigrationError(
                "schema_versions is not an ordered prefix of the bundled migrations"
            )

        applied_set = set(normalized)
        rewrite_pending = applied != normalized
        for migration in migrations:
            if migration.version in applied_set:
                continue
            self._apply(
                migration,
                baseline_versions=normalized if rewrite_pending else None,
            )
            rewrite_pending = False
            applied_set.add(migration.version)
        if rewrite_pending:
            self._rewrite_versions(normalized)

    def discover(self) -> list[Migration]:
        migrations: list[Migration] = []
        for path in self.versions_dir.glob("*.sql"):
            match = _MIGRATION_NAME.match(path.name)
            if not match:
                raise MigrationError(f"invalid migration filename: {path.name}")
            migrations.append(Migration(match.group(1), path))
        migrations.sort(key=lambda migration: migration.version)
        if len({migration.version for migration in migrations}) != len(migrations):
            raise MigrationError("duplicate SQLite migration versions")
        return migrations

    def _read_applied_versions(self) -> list[str]:
        conn = self.database.connect()
        try:
            if not self._table_exists(conn, "schema_versions"):
                return []
            rows = conn.execute(
                "SELECT version FROM schema_versions ORDER BY rowid"
            ).fetchall()
            return [str(row["version"]) for row in rows]
        finally:
            conn.close()

    def _rewrite_versions(self, versions: list[str]) -> None:
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM schema_versions")
            for version in versions:
                conn.execute(
                    "INSERT INTO schema_versions(version, applied_at) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (version,),
                )

    def _apply(
        self,
        migration: Migration,
        baseline_versions: list[str] | None = None,
    ) -> None:
        sql = migration.path.read_text(encoding="utf-8")
        with self.database.transaction() as conn:
            if baseline_versions is not None:
                conn.execute("DELETE FROM schema_versions")
                for version in baseline_versions:
                    conn.execute(
                        "INSERT INTO schema_versions(version, applied_at) "
                        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                        (version,),
                    )
            for statement in _statements(sql):
                # Databases created by the transitional desktop build already
                # contain some or all of the 0002 columns. Skipping an existing
                # ADD COLUMN keeps that legacy baseline upgradeable without
                # weakening transaction handling for other statements.
                match = _ADD_COLUMN.search(statement.strip())
                if match and self._column_exists(
                    conn, match.group("table"), match.group("column")
                ):
                    continue
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_versions(version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (migration.version,),
            )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        return any(
            row["name"] == column
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        )


def _statements(sql: str) -> Iterator[str]:
    """Yield complete SQLite statements without executescript's auto-commit."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        yield buffer.strip()
