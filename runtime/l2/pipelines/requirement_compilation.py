"""L2 pipeline: Requirement Compilation.

Loads an industry scope manifest (industry_scope) and compiles it into a
machine-readable industry knowledge requirement (industry_requirement).

Per industry_knowledge/pipelines/requirement_compilation.yaml:
  1. Load & validate the industry scope manifest
  2. Build the required_dimensions list from priority_dimensions + research_questions
  3. Compile dimension questions / expected fields / source requirements / report contract
  4. Upsert the compiled requirement into the `industry_requirement` table

The YAML semantics are implemented pragmatically: the executor reads a scope
manifest (YAML) and produces a row in `industry_requirement` keyed by
`requirement_id`. Source requirements and the report contract are derived from
common defaults unless overridden by the scope manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import yaml

from runtime.db import DB


# Default report contract used when the scope manifest does not specify one.
DEFAULT_REPORT_CONTRACT = {
    "format": "markdown",
    "inline_citation_format": "[S#]",
    "require_coverage_ledger": True,
    "require_evidence_package": True,
    "require_missing_data_section": True,
    "sla_hours": 72,
}

# A conservative default source profile. These are the registered, allowed
# source classes for industry knowledge (mirrors requirement example).
DEFAULT_SOURCE_REQUIREMENTS = {
    "primary_mode": "whitelist_first",
    "fallback_discovery": {
        "enabled": True,
        "trigger_on": ["missing", "partial", "outdated", "conflicting"],
        "require_original_url": True,
        "require_selection_reason": True,
    },
    "allowed_source_classes": [
        "government",
        "regulator",
        "standards_body",
        "industry_association",
        "industry_research",
        "academic",
        "brokerage_research",
        "reliable_media",
        "competitor_official",
        "company_disclosure",
    ],
    "critical_claim_min_independent_sources": 2,
}


def _scope_id_for_industry(db: DB, industry_id: str) -> str | None:
    """Return the industry_scope.id (UUID) matching an industry_id, if any."""
    rows = db.query(
        "SELECT id FROM industry_scope WHERE industry_id = %s ORDER BY created_at DESC LIMIT 1",
        (industry_id,),
    )
    return rows[0]["id"] if rows else None


def _build_required_dimensions(scope: dict) -> list[dict]:
    """Compile the required_dimensions JSONB from the scope manifest.

    Prefers the scope's own `required_dimensions` (if provided — e.g. by
    scope_builder, which embeds the full 14-dimension template with questions).
    Falls back to building from `priority_dimensions` + `research_questions`.
    """
    explicit = scope.get("required_dimensions")
    if isinstance(explicit, list) and explicit:
        dims = []
        for i, dim in enumerate(explicit, start=1):
            entry = dict(dim)
            entry.setdefault("required", True)
            entry.setdefault("order", i)
            entry.setdefault("expected_fields", ["canonical_name", "definition", "evidence_spans"])
            entry.setdefault("required_source_classes", DEFAULT_SOURCE_REQUIREMENTS["allowed_source_classes"])
            entry.setdefault("evidence_rules", {"min_independent_sources": 1})
            dims.append(entry)
        return dims

    priority = scope.get("priority_dimensions") or []
    questions = scope.get("research_questions") or []
    dimensions: list[dict] = []

    for i, dim in enumerate(priority, start=1):
        dimensions.append(
            {
                "dimension_code": dim,
                "required": True,
                "order": i,
                "questions": questions if i == 1 else [],
                "expected_fields": [
                    "canonical_name",
                    "definition",
                    "evidence_spans",
                ],
                "required_source_classes": DEFAULT_SOURCE_REQUIREMENTS["allowed_source_classes"],
                "evidence_rules": {"min_independent_sources": 1},
            }
        )

    if not dimensions:
        dimensions.append(
            {
                "dimension_code": "research_questions",
                "required": True,
                "order": 1,
                "questions": questions,
                "expected_fields": ["answer", "evidence_spans"],
                "required_source_classes": DEFAULT_SOURCE_REQUIREMENTS["allowed_source_classes"],
                "evidence_rules": {"require_original_url": True},
            }
        )

    return dimensions


def _content_hash(requirement_id: str, dimensions: list[dict]) -> str:
    """Deterministic content hash over the requirement body."""
    payload = json.dumps(
        {"requirement_id": requirement_id, "required_dimensions": dimensions},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_scope(path: str) -> dict[str, Any]:
    """Load and lightly validate a scope manifest YAML file.

    Supports both flat manifests and the nested form (scope: { ... }), e.g. the
    CRM example under industry_knowledge/examples/crm/scope.yaml, by merging the
    `scope` sub-object into the top level.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    scope = dict(raw)
    inner = raw.get("scope")
    if isinstance(inner, dict):
        # Nested scope manifest: merge inner fields in (outer meta wins for meta).
        for k, v in inner.items():
            scope.setdefault(k, v)

    industry_id = scope.get("industry_id") or scope.get("meta", {}).get("industry_id")
    if not industry_id:
        raise ValueError(f"Scope manifest {path} is missing a valid industry_id")
    return scope


def run(db: DB, args) -> dict[str, Any]:
    """Compile an industry scope manifest into an industry_requirement row."""
    scope_path = getattr(args, "scope", None) or os.environ.get("L2_SCOPE_PATH")
    if not scope_path or not os.path.exists(scope_path):
        raise FileNotFoundError(f"Scope manifest not found: {scope_path}")

    scope = _load_scope(scope_path)
    industry_id = scope.get("industry_id")
    canonical_name = scope.get("industry_name") or industry_id
    market = scope.get("market", "CN")
    language = (scope.get("languages") or ["zh-CN"])[0]

    # Stable requirement id derived from the scope identity.
    requirement_id = scope.get("requirement_id") or f"ikr_{industry_id}_{market.lower()}_{datetime.now(timezone.utc):%Y%m%d}"

    required_dimensions = _build_required_dimensions(scope)
    source_requirements = scope.get("source_requirements") or DEFAULT_SOURCE_REQUIREMENTS
    report_contract = scope.get("report_contract") or DEFAULT_REPORT_CONTRACT
    content_hash = _content_hash(requirement_id, required_dimensions)

    row = {
        "requirement_id": requirement_id,
        "industry_id": industry_id,
        "schema_version": scope.get("meta", {}).get("version", "1.0.0"),
        "required_dimensions": required_dimensions,
        "source_requirements": source_requirements,
        "report_contract": report_contract,
        "content_hash": content_hash,
        "status": "draft",
    }

    # scope_id is a UUID FK into industry_scope; resolve it if available.
    scope_id = _scope_id_for_industry(db, industry_id)
    if scope_id:
        row["scope_id"] = scope_id

    if getattr(args, "dry_run", False):
        print(f"[requirement_compilation] DRY-RUN would upsert industry_requirement")
        print(f"  requirement_id: {requirement_id}")
        print(f"  industry_id:    {industry_id}")
        print(f"  dimensions:     {len(required_dimensions)}")
        print(f"  content_hash:   {content_hash}")
        return {
            "pipeline": "requirement_compilation",
            "dry_run": True,
            "requirement_id": requirement_id,
            "industry_id": industry_id,
            "dimension_count": len(required_dimensions),
            "content_hash": content_hash,
        }

    db.upsert("industry_requirement", row, key_field="requirement_id")
    print(f"[requirement_compilation] upserted industry_requirement {requirement_id} "
          f"({len(required_dimensions)} dimensions)")

    return {
        "pipeline": "requirement_compilation",
        "requirement_id": requirement_id,
        "industry_id": industry_id,
        "scope_path": scope_path,
        "dimension_count": len(required_dimensions),
        "content_hash": content_hash,
        "status": "draft",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 requirement compilation pipeline")
    parser.add_argument("--scope", required=True, help="Path to industry scope manifest YAML")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))