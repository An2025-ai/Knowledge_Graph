"""Brand Atlas L2 Industry Knowledge Layer — executor orchestrator.

Runs one or more of the eight L2 pipelines（方案 §11.1），把一个共享 argparse
namespace 传给每个 pipeline 的 ``run(db, args)``。

新链路（证据 → 候选 → 门禁 → 主图）：

    article_registration → content_parsing → evidence_unit_merge → candidate_extraction
    → candidate_normalization → candidate_vectorization → knowledge_fusion → promotion

Usage:
    python -m engine.industry.executor --pipeline candidate_extraction --document-id <id>
    python -m engine.industry.executor --all --text "<正文>" [--dry-run]
    python -m engine.industry.executor --all --file <doc.md> [--dry-run]

`--dry-run` 由可跳过 DB 写的 pipeline 尊重（抽取仍打印而不 upsert）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from engine.core.db import check_connection, DB


# Map of pipeline name -> (module import path, run function).
PIPELINES = {
    "article_registration": "engine.industry.pipelines.article_registration",
    "content_parsing": "engine.industry.pipelines.content_parsing",
    "evidence_unit_merge": "engine.industry.pipelines.evidence_unit_merge",
    "candidate_extraction": "engine.industry.pipelines.candidate_extraction",
    "candidate_normalization": "engine.industry.pipelines.candidate_normalization",
    "candidate_vectorization": "engine.industry.pipelines.candidate_vectorization",
    "knowledge_fusion": "engine.industry.pipelines.knowledge_fusion",
    "promotion": "engine.industry.pipelines.promotion",
}

# Order used by --all，严格对齐方案 §11.1。
ALL_ORDER = [
    "article_registration",
    "content_parsing",
    "evidence_unit_merge",
    "candidate_extraction",
    "candidate_normalization",
    "candidate_vectorization",
    "knowledge_fusion",
    "promotion",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine.industry.executor",
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
        help="Run all L2 pipelines in order (--text or --file required).",
    )
    parser.add_argument("--document-id", help="External document identifier (brand/org id).")
    parser.add_argument("--document-uuid", help="document.id if article already registered.")
    parser.add_argument("--uuid", dest="document_uuid", help="Alias for --document-uuid.")
    parser.add_argument("--text", help="Raw article text input (content_parsing).")
    parser.add_argument("--file", help="Path to markdown/text document to read.")
    parser.add_argument("--title", help="Optional article title for registration.")
    parser.add_argument("--published-at", help="ISO published_at timestamp for registration.")
    parser.add_argument("--original-url", help="Source original_url for registration.")
    parser.add_argument("--profile-id", default="l2_industry", help="L2 profile id.")
    parser.add_argument("--layer", default="l2_industry", help="Graph layer label.")
    parser.add_argument("--tenant-id", help="Tenant id for gating/active graph.")
    parser.add_argument("--unit-limit", type=int, default=200,
                        help="Max evidence units scanned by candidate_extraction.")
    parser.add_argument("--skip-ner", action="store_true",
                        help="Disable optional NER, degrade to pure rule pre-extraction.")
    parser.add_argument("--unit-prefix", default="EU", help="Evidence unit id prefix.")
    parser.add_argument("--confidence-threshold", type=float,
                        help="Promotion gate confidence threshold (default from policy).")
    parser.add_argument("--knowledge-id", help="Promote only this gate_candidate_knowledge id.")
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
    if getattr(args, "dry_run", False):
        return run(db, args)
    with db.transaction():
        return run(db, args)


def _propagate_result(name: str, result: dict, args: argparse.Namespace) -> None:
    """Carry identifiers produced by one --all step into the next step."""
    if result.get("document_uuid"):
        args.document_uuid = result["document_uuid"]
    if result.get("document_id"):
        setattr(args, "document_id", result["document_id"])


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

    # --all needs either raw text/--file (full chain) or a known document-uuid
    # (re-run candidate_extraction..promotion on an existing article).
    if args.all and not args.file and not args.text and not args.document_uuid:
        parser.error("--all requires --file <doc.md> or --text \"...\" or --document-uuid <uuid>")

    results = {}
    failed = False
    with DB.from_env() as db:
        for name in names:
            try:
                result = _run_pipeline(name, args, db)
                if result.get("error"):
                    raise RuntimeError(str(result["error"]))
                results[name] = result
                _propagate_result(name, result, args)
            except Exception as exc:  # noqa: BLE001 - summarize the failed step
                print(f"[executor] pipeline '{name}' FAILED: {exc}", file=sys.stderr)
                results[name] = {"pipeline": name, "error": str(exc)}
                failed = True
                break

    print("\n=== L2 executor summary ===")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())