"""Brand Atlas L2 Industry Knowledge Layer — executor orchestrator.

Runs one or more of the six L2 pipeline executors, passing a shared argparse
namespace to each pipeline's `run(db, args)` function.

Usage:
    python -m runtime.l2.executor --pipeline requirement_compilation --scope <scope.yaml>
    python -m runtime.l2.executor --pipeline geo_research_report_job --report <file.md>
    python -m runtime.l2.executor --pipeline geo_research_report_job --crawl --request "研究需求"
    python -m runtime.l2.executor --pipeline report_ingestion --report <file.md>
    python -m runtime.l2.executor --pipeline evidence_resolution --evidence <evidence.json>
    python -m runtime.l2.executor --pipeline extraction --report <file.md> [--dry-run]
    python -m runtime.l2.executor --pipeline promotion --report-id <id> [--dry-run]
    python -m runtime.l2.executor --all --scope <scope.yaml> --report <file.md> [--dry-run]
    python -m runtime.l2.executor --all --scope <scope.yaml> --crawl --request "研究需求" [--dry-run]

`--dry-run` is honored by pipelines that can skip DB writes (extraction still
calls the LLM but prints instead of upserting).
"""
from __future__ import annotations

import argparse
import json
import sys

from runtime.db import check_connection, DB


# Map of pipeline name -> (module import path, run function).
PIPELINES = {
    "requirement_compilation": "runtime.l2.pipelines.requirement_compilation",
    "geo_research_report_job": "runtime.l2.pipelines.geo_research_report_job",
    "report_ingestion": "runtime.l2.pipelines.report_ingestion",
    "evidence_resolution": "runtime.l2.pipelines.evidence_resolution",
    "extraction": "runtime.l2.pipelines.extraction",
    "promotion": "runtime.l2.pipelines.promotion",
}

# Order used by --all. Geo-research is a file-ingestion step, so its report
# path must already exist (GEO_RESEARCH_REPORT_PATH or --report).
ALL_ORDER = [
    "requirement_compilation",
    "geo_research_report_job",
    "report_ingestion",
    "evidence_resolution",
    "extraction",
    "promotion",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime.l2.executor",
        description="Run L2 industry knowledge layer pipelines.",
    )
    parser.add_argument(
        "--pipeline",
        choices=list(PIPELINES.keys()),
        help="Run a single L2 pipeline.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all L2 pipelines in order (scope + report required).",
    )
    parser.add_argument("--scope", help="Path to industry scope manifest YAML.")
    parser.add_argument(
        "--industry",
        help="Target industry (e.g. 'CRM软件'); builds a scope manifest automatically instead of --scope.",
    )
    parser.add_argument("--market", default="CN", help="Market region (default CN).")
    parser.add_argument("--category", help="Optional category id (scope builder).")
    parser.add_argument("--audience", help="Comma-separated target audiences (scope builder).")
    parser.add_argument("--competitors", help="Comma-separated seed competitors (scope builder).")
    parser.add_argument("--priority-dim", help="Comma-separated priority dimension codes (scope builder).")
    parser.add_argument("--questions", help="Extra research questions (semicolon-separated) (scope builder).")
    parser.add_argument("--seed-sources", help="Comma-separated seed authoritative sources (scope builder).")
    parser.add_argument("--report", help="Path to markdown report (or geo-research report).")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Trigger geo-research web crawl to generate the report (uses SearXNG + Playwright + LLM).",
    )
    parser.add_argument(
        "--request",
        help="Research demand text passed to geo-research in crawl mode (default built from scope/requirement).",
    )
    parser.add_argument(
        "--requirement-id",
        help="industry_requirement.requirement_id — crawl uses its 14 dimensions as the request.",
    )
    parser.add_argument("--report-id", help="research_report.report_id to attach/scope to.")
    parser.add_argument("--evidence", help="Path to evidence index JSON.")
    parser.add_argument("--text", help="Raw text input for extraction.")
    parser.add_argument("--run-id", help="Explicit extraction run id.")
    parser.add_argument("--geo-research-run-id", help="Geo-research run id for lineage.")
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.5,
        help="Promotion gate_10 confidence threshold.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip DB writes where feasible; print what would be done.",
    )
    parser.add_argument(
        "--no-db-check",
        action="store_true",
        help="Skip the preliminary PostgreSQL connection check.",
    )
    return parser


def _load_run(module_path: str):
    """Import a pipeline module and return its run function."""
    import importlib

    module = importlib.import_module(module_path)
    return module.run


def _run_pipeline(name: str, args: argparse.Namespace, db: DB) -> dict:
    run = _load_run(PIPELINES[name])
    print(f"\n=== L2 pipeline: {name} ===")
    return run(db, args)


def _build_scope_from_industry(args: argparse.Namespace) -> str:
    """Use scope_builder to turn --industry/--market/... into a scope manifest path.

    Returns the path to the generated scope manifest (written to scopes/).
    """
    from runtime.l2 import scope_builder

    def _csv(v):
        return [s.strip() for s in v.split(",")] if v else None

    scope = scope_builder.build_scope(
        industry=args.industry,
        market=args.market,
        category=getattr(args, "category", None),
        audiences=_csv(getattr(args, "audience", None)),
        competitors=_csv(getattr(args, "competitors", None)),
        priority_dims=_csv(getattr(args, "priority_dim", None)),
        extra_questions=_csv(getattr(args, "questions", None)),
        seed_sources=_csv(getattr(args, "seed_sources", None)),
    )
    request_id = scope["scope"]["request_id"]
    out_path = f"scopes/{request_id}.yaml"
    import os

    os.makedirs("scopes", exist_ok=True)
    import yaml

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(scope, f, allow_unicode=True, sort_keys=False)
    print(f"[executor] built scope manifest from --industry: {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.pipeline and not args.all:
        parser.error("specify --pipeline <name> or --all")

    if not args.no_db_check and not check_connection() and not args.dry_run:
        print("[executor] aborting: PostgreSQL unreachable (pass --no-db-check to skip)",
              file=sys.stderr)
        return 1

    names = [args.pipeline] if args.pipeline else ALL_ORDER

    # If --industry is given (but no --scope), build a scope manifest first.
    if args.industry and not args.scope:
        args.scope = _build_scope_from_industry(args)

    # --all needs a scope for requirement_compilation and either a report,
    # --crawl, or a --requirement-id (crawl).
    if args.all:
        if not args.scope:
            parser.error("--all requires --scope <scope.yaml> or --industry <名称>")
        if not args.report and not args.crawl and not args.requirement_id:
            parser.error(
                "--all requires --report <file.md>, or --crawl / --requirement-id to have geo-research generate it"
            )

    results = {}
    with DB.from_env() as db:
        for name in names:
            try:
                results[name] = _run_pipeline(name, args, db)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"[executor] pipeline '{name}' FAILED: {exc}", file=sys.stderr)
                results[name] = {"pipeline": name, "error": str(exc)}

    print("\n=== L2 executor summary ===")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())