"""Create a consistent SQLite backup using SQLite's online Backup API."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import AppPaths  # noqa: E402


def backup_database(source: Path | None = None, destination: Path | None = None) -> Path:
    """Back up a live SQLite database without copying its main file directly."""
    source_path = Path(source) if source else AppPaths.from_environment().database
    if not source_path.is_file():
        raise FileNotFoundError(f"database not found: {source_path}")

    if destination is None:
        paths = AppPaths.from_environment()
        destination = paths.backups / (
            f"knowledge-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        )
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("backup destination must be different from the source database")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    source_connection = sqlite3.connect(source_path, timeout=30)
    destination_connection = sqlite3.connect(destination_path, timeout=30)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    return destination_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the Brand Atlas SQLite database")
    parser.add_argument("--database", type=Path, help="source database; defaults to runtime config")
    parser.add_argument("--output", type=Path, help="backup file; defaults to the backups directory")
    args = parser.parse_args()
    try:
        output = backup_database(args.database, args.output)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
