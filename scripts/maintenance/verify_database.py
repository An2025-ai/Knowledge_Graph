"""Verify SQLite integrity, foreign keys, required tables, and migrations."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import AppPaths  # noqa: E402


LEGACY_SCHEMA_VERSION = "desktop-1.0.0"
REQUIRED_TABLES = {
    "schema_versions", "documents", "evidence_spans", "evidence_units",
    "knowledge_candidates", "entities", "relations", "statements",
    "graph_outbox", "pipeline_jobs", "chat_messages", "embeddings",
}
MIGRATION_NAME = re.compile(r"^(\d{4}_[a-z0-9_]+)\.sql$")


def _migration_versions(directory: Path) -> list[str]:
    versions: list[str] = []
    for path in directory.glob("*.sql"):
        match = MIGRATION_NAME.match(path.name)
        if match:
            versions.append(match.group(1))
    return sorted(versions)


def verify_database(
    database: Path | None = None,
    migrations_dir: Path | None = None,
) -> dict[str, object]:
    """Return a safe, non-sensitive health report for a SQLite database."""
    database_path = Path(database) if database else AppPaths.from_environment().database
    versions_dir = (
        Path(migrations_dir)
        if migrations_dir
        else REPO_ROOT / "backend" / "app" / "migrations" / "versions"
    )
    report: dict[str, object] = {
        "database": str(database_path),
        "integrity_check": None,
        "foreign_key_errors": 0,
        "missing_tables": [],
        "schema_versions": [],
        "expected_schema_versions": _migration_versions(versions_dir),
    }
    if not database_path.is_file():
        return {**report, "status": "error", "error": "database_not_found"}

    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "schema_versions" in tables:
            applied = [row["version"] for row in connection.execute(
                "SELECT version FROM schema_versions ORDER BY rowid"
            ).fetchall()]
        else:
            applied = []
    finally:
        connection.close()

    expected = _migration_versions(versions_dir)
    normalized = (
        [expected[0] if version == LEGACY_SCHEMA_VERSION else version for version in applied]
        if expected else applied
    )
    missing_tables = sorted(REQUIRED_TABLES - tables)
    unknown_versions = [version for version in normalized if version not in expected]
    ordered_versions = normalized == expected[:len(normalized)]
    if unknown_versions or not ordered_versions:
        version_status = "invalid"
    elif normalized != expected:
        version_status = "migration_pending"
    else:
        version_status = "current"

    report.update({
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_key_errors),
        "missing_tables": missing_tables,
        "schema_versions": applied,
        "schema_version_status": version_status,
    })
    healthy = integrity == "ok" and not foreign_key_errors and not missing_tables
    status = "ok" if healthy and version_status == "current" else (
        "migration_pending" if healthy and version_status == "migration_pending" else "error"
    )
    return {**report, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Brand Atlas SQLite database")
    parser.add_argument("--database", type=Path, help="database to verify; defaults to runtime config")
    args = parser.parse_args()
    try:
        report = verify_database(args.database)
    except (OSError, sqlite3.Error) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"ok", "migration_pending"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
