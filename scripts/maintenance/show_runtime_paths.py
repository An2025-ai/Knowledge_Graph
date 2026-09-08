"""Show resolved Brand Atlas runtime paths without creating or changing them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import AppPaths  # noqa: E402


def runtime_paths() -> dict[str, object]:
    paths = AppPaths.from_environment()
    return {
        "root": str(paths.root),
        "database": str(paths.database),
        "documents": str(paths.documents),
        "vectors": str(paths.vectors),
        "cache": str(paths.cache),
        "logs": str(paths.logs),
        "backups": str(paths.backups),
        "config": str(paths.config),
        "database_exists": paths.database.is_file(),
    }


def main() -> int:
    print(json.dumps(runtime_paths(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
