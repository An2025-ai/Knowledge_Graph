"""Shared storage helpers for traceable research records."""
from __future__ import annotations

import json
from pathlib import Path


DATASETS = ("market", "products", "academic", "user-voice")


def upsert_jsonl(path: Path, records: list[dict]) -> int:
    """Upsert records by id and atomically replace a JSONL file."""
    existing: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing[item["id"]] = item
    existing.update({record["id"]: record for record in records})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing.values()),
        encoding="utf-8",
    )
    temporary.replace(path)
    return len(existing)
