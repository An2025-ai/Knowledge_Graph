"""L2 pipeline: Geo Research Report Job (file ingestion step).

Per industry_knowledge/pipelines/geo_research_report_job.yaml, this pipeline
submits an industry knowledge requirement to geo-research and monitors the run.
Because geo-research is a separate process, this executor keeps the ingest step:
  (a) locate the delivered report on disk (path from  GEO_RESEARCH_REPORT_PATH
      env var or the --report / report_path arg),
  (b) validate the report file exists and is non-empty,
  (c) register an `external_import_record` and a `research_report` row.

It does NOT shell out to geo-research; it is a file-ingestion step that records
lineage for a report produced out-of-band.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from runtime.db import DB


def _file_hash(path: str) -> str:
    """SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _requirement_uuid(db: DB, requirement_id: str) -> str | None:
    """Resolve a requirement_id string to the industry_requirement UUID."""
    rows = db.query(
        "SELECT id FROM industry_requirement WHERE requirement_id = %s LIMIT 1",
        (requirement_id,),
    )
    return rows[0]["id"] if rows else None


def run(db: DB, args) -> dict[str, Any]:
    """Ingest a geo-research report file and register lineage rows."""
    report_path = (
        getattr(args, "report", None)
        or getattr(args, "report_path", None)
        or os.environ.get("GEO_RESEARCH_REPORT_PATH")
    )
    if not report_path:
        raise ValueError(
            "No report path provided. Set GEO_RESEARCH_REPORT_PATH or pass --report <file.md>"
        )
    if not os.path.exists(report_path):
        raise FileNotFoundError(f"Geo-research report not found: {report_path}")
    if os.path.getsize(report_path) == 0:
        raise ValueError(f"Geo-research report is empty: {report_path}")

    report_hash = _file_hash(report_path)
    run_id = getattr(args, "geo_research_run_id", None) or os.environ.get("GEO_RESEARCH_RUN_ID")
    requirement_id = getattr(args, "requirement_id", None)
    report_id = getattr(args, "report_id", None) or f"grep_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"

    # --- external_import_record: file-level provenance (not a knowledge fact) ---
    import_record = {
        "import_id": report_id,
        "requirement_id": requirement_id,
        "package_ref": report_path,
        "geo_research_run_id": run_id,
        "report_path": report_path,
        "package_hash": report_hash,
        "status": "imported",
        "metadata": {
            "file_size": os.path.getsize(report_path),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source": report_path,
        },
    }

    # --- research_report row ---
    research_report = {
        "report_id": report_id,
        "geo_research_run_id": run_id,
        "report_path": report_path,
        "report_hash": report_hash,
        "coverage_status": getattr(args, "coverage_status", None) or "pending",
        "validation_status": "pending",
        "report_metadata": {
            "file_size": os.path.getsize(report_path),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source": report_path,
        },
    }

    # requirement is a UUID FK on research_report; resolve if provided.
    req_uuid = _requirement_uuid(db, requirement_id) if requirement_id else None
    if req_uuid:
        research_report["requirement_id"] = req_uuid

    if getattr(args, "dry_run", False):
        print("[geo_research_report_job] DRY-RUN would register import + research_report")
        print(f"  report_path: {report_path}")
        print(f"  report_id:   {report_id}")
        print(f"  report_hash: {report_hash}")
        print(f"  requirement: {requirement_id} (uuid={req_uuid})")
        return {
            "pipeline": "geo_research_report_job",
            "dry_run": True,
            "report_id": report_id,
            "report_path": report_path,
            "report_hash": report_hash,
        }

    db.upsert("external_import_record", import_record, key_field="import_id")
    db.upsert("research_report", research_report, key_field="report_id")
    print(f"[geo_research_report_job] registered import {report_id} -> {report_path}")

    return {
        "pipeline": "geo_research_report_job",
        "report_id": report_id,
        "report_path": report_path,
        "report_hash": report_hash,
        "requirement_id": requirement_id,
        "geo_research_run_id": run_id,
        "status": "imported",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 geo-research report ingestion pipeline")
    parser.add_argument("--report", help="Path to the delivered geo-research markdown report")
    parser.add_argument("--report-id", help="Optional explicit report_id; else auto-generated")
    parser.add_argument("--requirement-id", help="Requirement_id this report satisfies")
    parser.add_argument("--geo-research-run-id", help="Optional geo-research run id for lineage")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))