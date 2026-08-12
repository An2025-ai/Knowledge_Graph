"""L2 pipeline: Geo Research Report Job (crawl + ingest).

Per industry_knowledge/pipelines/geo_research_report_job.yaml, this pipeline
submits an industry knowledge requirement to geo-research and monitors the run.

Two modes:
  * CRAWL mode (new): when --crawl is set, shell out to the geo-research
    subprocess to actually crawl the web and generate an industry report
    (SearXNG search + Playwright browser + LLM synthesis). Then ingest the
    produced report.
  * INGEST mode (default): treat the report as already delivered on disk
    (path from GEO_RESEARCH_REPORT_PATH env or --report) and register lineage.

geo-research is a separate project; this bridge locates it via env-configurable
paths so no absolute path is hardcoded. cwd MUST be the geo-research root
because its module imports depend on it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from runtime.db import DB

# --- geo-research bridge config (env-overridable, no hardcoded abs path) ---
DEFAULT_GEO_RESEARCH_ROOT = str(Path("d:/Brand Atlas/geo-research").resolve())


def _geo_research_root() -> str:
    return os.environ.get("GEO_RESEARCH_ROOT", DEFAULT_GEO_RESEARCH_ROOT)


def _geo_research_python(root: str) -> str:
    return os.environ.get(
        "GEO_RESEARCH_PYTHON",
        str(Path(root) / ".venv-browser" / "Scripts" / "python.exe"),
    )


def _geo_research_llm_config(root: str) -> str:
    return os.environ.get(
        "GEO_RESEARCH_LLM_CONFIG",
        str(Path(root) / "llm-config.local.json"),
    )


def _geo_research_timeout() -> int:
    try:
        return int(os.environ.get("GEO_RESEARCH_TIMEOUT", "900"))
    except ValueError:
        return 900


def _build_request(args) -> str:
    """Compose a geo-research `--request` research demand from scope/requirement."""
    if getattr(args, "request", None):
        return args.request
    # Fall back to constructing from industry_requirement / scope if available.
    requirement_id = getattr(args, "requirement_id", None) or getattr(args, "requirement", None)
    if requirement_id:
        return f"研究行业：{requirement_id}。请覆盖行业与市场、产品与竞品、用户需求、趋势与风险等维度，引用公开权威来源。"
    return "请对指定行业进行公开权威研究，覆盖市场、产品、竞品、用户与趋势维度。"


def trigger_geo_research(args) -> str:
    """Shell out to geo-research to crawl + synthesize a report. Returns report path.

    Runs:
        <python> -m src.llm_report --config <llm-config.local.json> run \
            --request "<request>"
    in the geo-research root. Returns the path to the latest generated report.
    """
    root = _geo_research_root()
    python = _geo_research_python(root)
    llm_config = _geo_research_llm_config(root)
    request = _build_request(args)
    timeout = _geo_research_timeout()
    dry_run = getattr(args, "dry_run", False)

    if not Path(root).exists():
        raise FileNotFoundError(
            f"geo-research not found at {root}. Set GEO_RESEARCH_ROOT env var."
        )
    if not Path(python).exists():
        raise FileNotFoundError(f"geo-research python not found at {python}. Set GEO_RESEARCH_PYTHON.")

    cmd = [
        python,
        "-m",
        "src.llm_report",
        "--config",
        llm_config,
        "run",
        "--request",
        request,
    ]
    if getattr(args, "query_profile", None):
        cmd += ["--query-profile", args.query_profile]

    print(f"[geo_research_report_job] CRAWL trigger")
    print(f"  root:     {root}")
    print(f"  python:   {python}")
    print(f"  request:  {request}")
    print(f"  timeout:  {timeout}s")

    if dry_run:
        print(f"  [DRY-RUN] would run: {' '.join(cmd)}")
        # In dry-run, still try to locate an existing latest report if present.
        latest = _find_latest_report(root)
        if latest:
            print(f"  [DRY-RUN] existing latest report: {latest}")
            return latest
        return "<dry-run: no crawl executed>"

    print(f"  running (cwd={root})...")
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(
            f"geo-research crawl exceeded {timeout}s. Increase GEO_RESEARCH_TIMEOUT."
        )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RuntimeError(f"geo-research crawl failed (rc={proc.returncode}):\n{tail}")

    report_path = _find_latest_report(root)
    if not report_path:
        raise FileNotFoundError(
            "geo-research reported success but no latest report found in reports/latest-search-report.md"
        )
    return report_path


def _find_latest_report(root: str) -> str | None:
    """Return the path of the most recent geo-research report."""
    latest = Path(root) / "reports" / "latest-search-report.md"
    if latest.exists():
        return str(latest)
    # fallback: newest search-report-*.md in reports/generated
    gen = Path(root) / "reports" / "generated"
    if gen.exists():
        matches = sorted(gen.glob("search-report-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return str(matches[0])
    return None


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
    """Trigger geo-research crawl (if --crawl) and ingest the delivered report."""
    crawl = getattr(args, "crawl", False)
    if crawl:
        report_path = trigger_geo_research(args)
        # If dry-run produced a placeholder, return early without DB writes.
        if report_path.startswith("<dry-run"):
            return {
                "pipeline": "geo_research_report_job",
                "dry_run": True,
                "mode": "crawl",
                "report_path": report_path,
            }
        # Override args.report so the ingest step below uses the crawled report.
        args.report = report_path
    else:
        report_path = (
            getattr(args, "report", None)
            or getattr(args, "report_path", None)
            or os.environ.get("GEO_RESEARCH_REPORT_PATH")
        )
    if not report_path:
        raise ValueError(
            "No report path. Either pass --crawl to trigger geo-research, or set "
            "GEO_RESEARCH_REPORT_PATH / pass --report <file.md>."
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
    parser.add_argument("--crawl", action="store_true", help="Trigger geo-research crawl to generate the report")
    parser.add_argument("--request", help="Research demand passed to geo-research (crawl mode)")
    parser.add_argument("--report-id", help="Optional explicit report_id; else auto-generated")
    parser.add_argument("--requirement-id", help="Requirement_id this report satisfies")
    parser.add_argument("--geo-research-run-id", help="Optional geo-research run id for lineage")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))