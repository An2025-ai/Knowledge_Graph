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
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
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
        return int(os.environ.get("GEO_RESEARCH_TIMEOUT", "1800"))
    except ValueError:
        return 1800


def _build_request(args, db=None) -> str:
    """Compose a geo-research `--request` research demand.

    Priority:
      1. Explicit --request text (user-provided).
      2. --requirement-id → load industry_requirement from DB → flatten to a
         full 14-dimension request via requirement_to_request.
      3. Fallback generic demand.
    """
    if getattr(args, "request", None):
        return args.request

    requirement_id = getattr(args, "requirement_id", None) or getattr(args, "requirement", None)
    if requirement_id:
        if db is None:
            raise ValueError(
                "--requirement-id requires a DB connection to load industry_requirement; "
                "either pass --request <text> or ensure PostgreSQL is reachable."
            )
        try:
            from runtime.industry.requirement_to_request import load_requirement, requirement_to_request

            req = load_requirement(db, requirement_id)
            market = getattr(args, "market", None) or req.get("market", "CN")
            return requirement_to_request(req, market=market)
        except Exception as exc:
            raise RuntimeError(f"Failed to build request from requirement {requirement_id}: {exc}") from exc

    return "请对指定行业进行公开权威研究，覆盖市场、产品、竞品、用户与趋势维度。"


def _build_source_config(args, db=None) -> str | None:
    """Return a source-config JSON path for geo-research, or None if not derivable.

    Reuses the same requirement as `_build_request` and serializes the structured
    source whitelist (allowed_source_classes + per-dimension required classes) so
    the crawler can run a two-layer authoritative-source strategy. Writes a temp
    JSON file and returns its path; caller passes it as `--source-config`.
    """
    requirement_id = getattr(args, "requirement_id", None) or getattr(args, "requirement", None)
    if not requirement_id or db is None:
        return None
    try:
        from runtime.industry.requirement_to_request import (
            load_requirement,
            requirement_to_source_config,
        )

        req = load_requirement(db, requirement_id)
        market = getattr(args, "market", None) or req.get("market", "CN")
        cfg = requirement_to_source_config(req, market=market)
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".source-config.json", prefix="kg_src_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return path
    except Exception as exc:  # noqa: BLE001 - source config is best-effort
        print(f"[geo_research_report_job] source-config skip: {exc}")
        return None


def trigger_geo_research(args, db=None) -> str:
    """Shell out to geo-research to crawl + synthesize a report. Returns report path.

    Runs:
        <python> -m src.llm_report --config <llm-config.local.json> run \
            --request "<request>" [--source-config <json>]
    in the geo-research root. Returns the path to the latest generated report.
    """
    root = _geo_research_root()
    python = _geo_research_python(root)
    llm_config = _geo_research_llm_config(root)
    request = _build_request(args, db=db)
    source_config = _build_source_config(args, db=db)
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
    if source_config:
        cmd += ["--source-config", source_config]
    if getattr(args, "query_profile", None):
        cmd += ["--query-profile", args.query_profile]
    passthrough_options = {
        "searxng_url": "--searxng-url",
        "results_per_query": "--results-per-query",
        "max_pages": "--max-pages",
        "max_sources": "--max-sources",
        "max_report_sources": "--max-report-sources",
        "max_industry_authorities": "--max-industry-authorities",
        "max_pages_per_authority": "--max-pages-per-authority",
        "max_pages_per_authority_per_dim": "--max-pages-per-authority-per-dim",
        "min_sources_per_dimension": "--min-sources-per-dimension",
        "target_sources_per_dimension": "--target-sources-per-dimension",
    }
    for attr, flag in passthrough_options.items():
        value = getattr(args, attr, None)
        if value is not None:
            cmd += [flag, str(value)]

    print(f"[geo_research_report_job] CRAWL trigger")
    print(f"  root:     {root}")
    print(f"  python:   {python}")
    print(f"  request:  {request}")
    if source_config:
        print(f"  source_config: {source_config}")
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


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _strip_html(value: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_text(url: str, timeout: int = 12) -> tuple[str, str]:
    """Fetch readable text from a URL. Returns (access_status, text)."""
    if not url.startswith(("http://", "https://")):
        return "not_fetchable", ""
    if "google.com/search?" in url:
        return "search_plan_only", ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BrandAtlasKG/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL comes from candidate list
            raw = resp.read(1_000_000)
            content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type.lower():
            return "unsupported_pdf", ""
        text = raw.decode("utf-8", errors="replace")
        if "<html" in text[:1000].lower() or "<body" in text[:5000].lower():
            text = _strip_html(text)
        return "fetched", text[:12000]
    except Exception as exc:  # noqa: BLE001 - capture per-source failures in package
        return f"fetch_failed:{str(exc)[:120]}", ""


def _quote_for_source(source: dict, text: str) -> str:
    if text:
        return text[:700]
    return source.get("snippet") or source.get("title") or source.get("url") or "No extractable text."


def _source_dimensions(source: dict) -> list[str]:
    dims = source.get("dimension_codes") or source.get("dimensions") or []
    return [str(d) for d in dims if d]


def _build_research_package(source_list_path: str, out_dir: str | None = None,
                            fetch: bool = True) -> dict[str, Any]:
    """Build a research_package directory from source candidates."""
    source_payload = _read_json(source_list_path)
    sources = [
        source for source in (source_payload.get("sources") or [])
        if source.get("accepted_for_research", True)
    ]
    industry = source_payload.get("industry") or "industry"
    market = source_payload.get("market") or "CN"
    package_id = f"rp_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    if out_dir:
        package_dir = Path(out_dir)
    else:
        safe = "".join(c.lower() if c.isalnum() else "_" for c in industry).strip("_") or "industry"
        package_dir = Path("runtime") / "l2" / "output" / f"research_package_{safe}_{market.lower()}_{package_id}"
    package_dir.mkdir(parents=True, exist_ok=True)
    documents_dir = package_dir / "documents"
    documents_dir.mkdir(exist_ok=True)

    evidence_sources = []
    candidates = []
    coverage: dict[str, dict[str, Any]] = {}

    for idx, source in enumerate(sources, start=1):
        label = f"S{idx}"
        access_status, text = _fetch_text(source.get("url", "")) if fetch else ("not_fetched", "")
        quote = _quote_for_source(source, text)
        content_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        content_path = None
        if text:
            content_path = str(documents_dir / f"{label}.txt")
            Path(content_path).write_text(text, encoding="utf-8")

        dims = _source_dimensions(source) or ["source_ecology"]
        for dim in dims:
            item = coverage.setdefault(dim, {
                "dimension_code": dim,
                "coverage_status": "partial",
                "source_count": 0,
                "citation_labels": [],
            })
            item["source_count"] += 1
            item["citation_labels"].append(label)

        evidence_sources.append({
            "label": label,
            "evidence_id": f"ev_{package_id}_{idx:03d}",
            "source_id": source.get("source_id") or f"src_{package_id}_{idx:03d}",
            "url": source.get("url"),
            "title": source.get("title"),
            "publisher": source.get("publisher") or source.get("title"),
            "source_class": source.get("source_class") or "reliable_media",
            "source_type": source.get("source_type") or "web",
            "access_status": "verified" if access_status == "fetched" else access_status,
            "support_status": "directly_supports" if quote and access_status != "fetch_failed" else "insufficient",
            "quote": quote,
            "content_path": content_path,
            "content_hash": content_hash,
            "dimension_codes": dims,
        })

        for dim in dims:
            candidates.append({
                "dimension_code": dim,
                "statement": f"{source.get('title') or source.get('url')} provides evidence for {dim} in {industry}. [{label}]",
                "citation_labels": [label],
                "source_id": source.get("source_id"),
                "confidence": 0.55 if access_status == "fetched" else 0.45,
            })

    coverage_list = list(coverage.values())
    report_path = package_dir / "report.md"
    _write_package_report(report_path, industry, market, coverage_list, evidence_sources, candidates)

    manifest = {
        "package_id": package_id,
        "industry": industry,
        "market": market,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_list": str(Path(source_list_path).resolve()),
        "files": {
            "report": "report.md",
            "sources": "sources.json",
            "evidence_index": "evidence_index.json",
            "coverage_ledger": "coverage_ledger.json",
            "candidates": "candidates.json",
        },
        "stats": {
            "sources": len(sources),
            "evidence": len(evidence_sources),
            "dimensions": len(coverage_list),
            "candidates": len(candidates),
        },
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_dir / "sources.json").write_text(json.dumps(source_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_dir / "evidence_index.json").write_text(
        json.dumps({"sources": evidence_sources}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (package_dir / "coverage_ledger.json").write_text(json.dumps(coverage_list, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_dir / "candidates.json").write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"package_dir": str(package_dir), "manifest": manifest, "report_path": str(report_path)}


def _write_package_report(path: Path, industry: str, market: str, coverage: list[dict],
                          evidence_sources: list[dict], candidates: list[dict]) -> None:
    lines = [
        f"# {industry} 行业研究报告（{market}）",
        "",
        "## 执行摘要",
        f"本报告由 research_package 自动生成，覆盖 {len(coverage)} 个 L2 维度、{len(evidence_sources)} 条候选信源证据。当前内容用于 L2 候选入库和人工审核，不等同于最终权威结论。",
        "",
        "## 维度覆盖",
    ]
    for item in coverage:
        labels = ", ".join(item.get("citation_labels") or [])
        lines.append(f"- {item['dimension_code']}: {item['coverage_status']}，source_count={item['source_count']}，citations={labels}")
    lines += ["", "## 维度发现"]
    grouped: dict[str, list[dict]] = {}
    for cand in candidates:
        grouped.setdefault(cand["dimension_code"], []).append(cand)
    for dim, items in grouped.items():
        lines.append("")
        lines.append(f"### {dim}")
        for cand in items[:8]:
            lines.append(f"- {cand['statement']}")
    lines += ["", "## 来源清单"]
    for source in evidence_sources:
        lines.append(f"- [{source['label']}] {source.get('title') or source.get('url')} - {source.get('url')}")
    lines += ["", "## 缺失数据说明", "- 自动抓取失败、搜索计划型来源和未审核来源需要人工补证或二次抓取。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _package_paths(package_dir: str) -> dict[str, str]:
    root = Path(package_dir)
    manifest_path = root / "manifest.json"
    manifest = _read_json(str(manifest_path)) if manifest_path.exists() else {}
    files = manifest.get("files") or {}
    return {
        "package_dir": str(root),
        "manifest_path": str(manifest_path) if manifest_path.exists() else None,
        "report_path": str(root / files.get("report", "report.md")),
        "evidence_path": str(root / files.get("evidence_index", "evidence_index.json")),
        "sources_path": str(root / files.get("sources", "sources.json")),
        "coverage_path": str(root / files.get("coverage_ledger", "coverage_ledger.json")),
        "candidates_path": str(root / files.get("candidates", "candidates.json")),
        "manifest": manifest,
    }


def _requirement_uuid(db: DB, requirement_id: str) -> str | None:
    """Resolve a requirement_id string to the industry_requirement UUID."""
    rows = db.query(
        "SELECT id FROM industry_requirement WHERE requirement_id = %s LIMIT 1",
        (requirement_id,),
    )
    return rows[0]["id"] if rows else None


def run(db: DB, args) -> dict[str, Any]:
    """Trigger geo-research crawl (if --crawl) and ingest the delivered report."""
    package_paths = None
    source_list = getattr(args, "source_list", None)
    research_package = getattr(args, "research_package", None) or getattr(args, "package", None)
    if research_package:
        package_paths = _package_paths(research_package)
        report_path = package_paths["report_path"]
        args.report = report_path
        args.evidence = package_paths["evidence_path"]
    elif source_list:
        built = _build_research_package(
            source_list,
            out_dir=getattr(args, "package_out", None),
            fetch=not getattr(args, "no_fetch", False) and not getattr(args, "dry_run", False),
        )
        package_paths = _package_paths(built["package_dir"])
        report_path = package_paths["report_path"]
        args.research_package = built["package_dir"]
        args.report = report_path
        args.evidence = package_paths["evidence_path"]
        print(f"[geo_research_report_job] built research_package {built['package_dir']}")
    else:
        report_path = None

    crawl = getattr(args, "crawl", False)
    if crawl and not package_paths:
        report_path = trigger_geo_research(args, db=db)
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
    elif not package_paths:
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
    package_hash = _json_hash(package_paths["manifest"]) if package_paths else report_hash
    run_id = getattr(args, "geo_research_run_id", None) or os.environ.get("GEO_RESEARCH_RUN_ID")
    requirement_id = getattr(args, "requirement_id", None)
    report_id = getattr(args, "report_id", None) or f"grep_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    # Make the generated report_id available to downstream --all pipelines.
    args.report_id = report_id

    # --- external_import_record: file-level provenance (not a knowledge fact) ---
    import_record = {
        "import_id": report_id,
        "requirement_id": requirement_id,
        "package_ref": package_paths["package_dir"] if package_paths else report_path,
        "geo_research_run_id": run_id,
        "report_path": report_path,
        "package_hash": package_hash,
        "status": "imported",
        "metadata": {
            "file_size": os.path.getsize(report_path),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "source": report_path,
            **({"research_package": package_paths} if package_paths else {}),
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
            **({"research_package": package_paths} if package_paths else {}),
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
            **({"research_package": package_paths["package_dir"],
                "evidence_path": package_paths["evidence_path"]} if package_paths else {}),
        }

    db.upsert("external_import_record", import_record, key_field="import_id")
    db.upsert("research_report", research_report, key_field="report_id")
    print(f"[geo_research_report_job] registered import {report_id} -> {report_path}")

    return {
        "pipeline": "geo_research_report_job",
        "report_id": report_id,
        "report_path": report_path,
        "report_hash": report_hash,
        **({"research_package": package_paths["package_dir"],
            "evidence_path": package_paths["evidence_path"],
            "source_list": source_list} if package_paths else {}),
        "requirement_id": requirement_id,
        "geo_research_run_id": run_id,
        "status": "imported",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 geo-research report ingestion pipeline")
    parser.add_argument("--report", help="Path to the delivered geo-research markdown report")
    parser.add_argument("--source-list", help="Source candidate JSON from source_discovery")
    parser.add_argument("--research-package", "--package", dest="research_package", help="Existing research_package directory")
    parser.add_argument("--package-out", help="Output directory when building a research_package")
    parser.add_argument("--no-fetch", action="store_true", help="Build package without fetching candidate URLs")
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
