"""L3 Pipeline Orchestrator.

Runs one — or all — of the L3 brand-cognition pipeline executors against a brand
document, producing the "brand docs/report -> brand knowledge" flow.

Usage:
    python -m runtime.l3.executor --pipeline source_registration --file <doc.md> --brand <brand_id>
    python -m runtime.l3.executor --pipeline candidate_extraction --file <doc.md> --brand <brand_id> [--dry-run]
    python -m runtime.l3.executor --all --file <doc.md> --brand <brand_id> [--dry-run]

Each pipeline is a ``run(db, args) -> dict`` in ``runtime.l3.pipelines.<name>``.
The orchestrator owns argparse and passes a plain ``args`` namespace to each
pipeline; ``--dry-run`` is forwarded so pipelines never write to the DB.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any

from runtime.db import DB

# L3 is self-contained and never creates mappings to L2.
DEFAULT_PIPELINES = [
    "source_registration",
    "original_file_gate",
    "layout_aware_parsing",
    "semantic_chunking",
    "candidate_pre_extraction",
    "candidate_extraction",
    "entity_resolution",
    "assertion_classification",
    "evidence_verification",
    "review_promotion",
]
PIPELINES = DEFAULT_PIPELINES

# Pipelines that need a --document-id (produced by source_registration).
REQUIRE_DOCUMENT_ID = {
    "layout_aware_parsing",
    "semantic_chunking",
    "candidate_pre_extraction",
    "candidate_extraction",
}

# Pipelines that need a --file.
REQUIRE_FILE = {"source_registration", "original_file_gate", "layout_aware_parsing"}


def load_pipeline(name: str):
    """Import ``runtime.l3.pipelines.<name>`` and return its ``run`` callable."""
    try:
        module = importlib.import_module(f"runtime.l3.pipelines.{name}")
    except ImportError as exc:
        raise SystemExit(f"Unknown pipeline: {name} ({exc})")
    run = getattr(module, "run", None)
    if not callable(run):
        raise SystemExit(f"Pipeline module {name} has no run(db, args) callable")
    return run


def run_one(db: DB, name: str, args) -> dict[str, Any]:
    run = load_pipeline(name)
    print(f"\n=== L3 pipeline: {name} ===")
    if getattr(args, "dry_run", False):
        result = run(db, args)
    else:
        with db.transaction():
            result = run(db, args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


def _validate(names: list[str], args) -> None:
    for name in names:
        if name in REQUIRE_FILE and not getattr(args, "file", None):
            raise SystemExit(f"pipeline '{name}' requires --file <doc.md>")
        if name in REQUIRE_DOCUMENT_ID and not getattr(args, "document_id", None):
            raise SystemExit(
                f"pipeline '{name}' requires --document-id (from source_registration). "
                f"Use --all, or pass --document-id."
            )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m runtime.l3.executor",
        description="Brand Atlas L3 brand-cognition pipeline executor",
    )
    p.add_argument("--pipeline", choices=PIPELINES, help="Name of a single L3 pipeline to run")
    p.add_argument("--all", action="store_true", help="Run the default L3 pipelines in sequence")
    p.add_argument("--file", help="Path to the brand source document (md/txt/html)")
    p.add_argument("--brand", required=True, help="Brand key / id")
    p.add_argument("--tenant", help="Tenant key (default: 'default')")
    p.add_argument("--document-id", help="document_id (auto-derived under --all)")
    p.add_argument("--source-id", help="source_id (auto-derived under --all)")
    p.add_argument("--dry-run", action="store_true", help="Do not write to the DB")
    # pass-through / optional metadata
    p.add_argument("--source-type", help="Source type")
    p.add_argument("--publisher", help="Publisher")
    p.add_argument("--canonical-url", help="Canonical URL")
    p.add_argument("--access-level", choices=["public", "internal", "confidential", "restricted"])
    p.add_argument("--language", help="Document language")
    p.add_argument("--content-hash", help="Source content hash (for snapshot)")
    p.add_argument("--skip-ner", action="store_true",
                   help="Disable the optional PaddleNLP NER candidate layer")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.all and not args.pipeline:
        parser.error("specify --pipeline <name> or --all")

    # Derive a stable document_id from the file name when running --all so the
    # downstream pipelines can reference the same document across steps.
    if args.all and not args.document_id:
        import os
        fname = os.path.basename(args.file) if args.file else "document"
        stem = os.path.splitext(fname)[0]
        args.document_id = f"doc_{stem}"
    if args.all and not args.source_id:
        import os
        fname = os.path.basename(args.file) if args.file else "source"
        args.source_id = f"src_{fname}"

    if args.all:
        names = list(DEFAULT_PIPELINES)
    else:
        names = [args.pipeline]

    _validate(names, args)

    with DB.from_env() as db:
        results = {}
        failed = False
        for name in names:
            try:
                result = run_one(db, name, args)
                if result.get("error"):
                    raise RuntimeError(str(result["error"]))
                results[name] = result
            except Exception as exc:  # noqa: BLE001 - summarize failed pipeline
                print(f"[executor] pipeline '{name}' FAILED: {exc}", file=sys.stderr)
                results[name] = {"pipeline": name, "error": str(exc)}
                failed = True
                break
            # --all: chain the auto document_id/source_id we already set; also
            # carry the content hash forward for the final snapshot.
            if args.all and name == "source_registration":
                args.content_hash = result.get("content_hash") or args.content_hash

        if args.all:
            print("\n=== L3 run summary ===")
            for name, res in results.items():
                keys = [k for k in ("stats", "section_count", "span_count", "mapping_count",
                                    "promoted", "queued") if k in res]
                brief = {k: res[k] for k in keys}
                print(f"  {name}: {brief or res.get('status', 'ok')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
