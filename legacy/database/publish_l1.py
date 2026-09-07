"""Build a deterministic L1 registry snapshot for review or deployment.

可用作两种用途：
1. `--out <path>`：导出 JSON 注册表快照（供 review / 部署比对）。
2. `--seed`：把 L1 注册表 UPSERT 进 PostgreSQL 的 entity_type / relation_type
   表（schema.sql）。L2/L3 建表里 entity.entity_type 与 relation.relation_type
   都外键引用它们（legacy/database/l2_l3_schema.sql:291,332），不 seed 会让任何 L2/L3
   写入因父键缺失而失败（审查 Critical #6）。幂等，可每次部署前跑。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.knowledge.registry import get_common_registry
from shared.knowledge.validate import validate_common


def build_snapshot() -> dict:
    registry = get_common_registry()
    return {
        "ontologies": {
            profile_id: {
                "layer": profile.layer,
                "entities": profile.entity_specs,
                "relations": profile.relation_specs,
                "metrics": profile.metric_specs,
            }
            for profile_id, profile in sorted(registry.profiles.items())
        },
        "assertion_types": registry.assertion_specs,
        "context_types": registry.context_specs,
        "operations": registry.operation_specs,
        "quality_metrics": registry.quality_metric_specs,
        "extraction_rules": registry.extraction_contract,
        "profiles": {
            profile_id: {
                "layer": profile.layer,
                "entity_types": sorted(profile.allowed_entity_types),
                "relation_types": sorted(profile.allowed_relation_types),
                "metrics": sorted(profile.metric_specs),
                "statement_classes": sorted(profile.statement_classes),
                "promotion_policy": profile.promotion_policy,
            }
            for profile_id, profile in sorted(registry.profiles.items())
        },
    }


def _entity_type_rows(registry) -> list[dict]:
    """Map L1 entity_specs → entity_type table rows (审查 Critical #6：写入注册表，
    否则 entity.entity_type FK 与 relation.relation_type FK 无父行可引用→任何 L2/L3
    写入都会失败）。type_code 即 {profile_id}.{code}（与 build_candidate_rows 使用
    entity_type "l2_industry.brand" 一致）。"""
    rows: list[dict] = []
    for type_id, spec in sorted(registry.entity_specs.items()):
        rows.append({
            "type_code": type_id,
            "canonical_name": spec.get("canonical_name") or spec.get("type") or type_id,
            "canonical_name_en": spec.get("canonical_name_en"),
            "definition": spec.get("definition") or spec.get("description") or type_id,
            "examples": spec.get("examples", []),
            "required_fields": spec.get("required_fields", []),
            "optional_fields": spec.get("optional_fields", []),
            "constraints": spec.get("constraints", []),
            "version": spec.get("version", "1.0.0"),
            "status": "active",
        })
    return rows


def _relation_type_rows(registry) -> list[dict]:
    """Map L1 relation_specs → relation_type table rows (审查 Critical #6）。"""
    rows: list[dict] = []
    for relation_id, spec in sorted(registry.relation_specs.items()):
        rows.append({
            "relation_code": relation_id,
            "description": spec.get("description") or relation_id,
            "description_en": spec.get("description_en"),
            "subject_types": spec.get("subject_types", []),
            "object_types": spec.get("object_types", []),
            "cardinality": spec.get("cardinality", "many-to-many"),
            "bidirectional": bool(spec.get("bidirectional", False)),
            "inverse_relation": spec.get("inverse_relation"),
            "confidence_required": bool(spec.get("confidence_required", False)),
            "source_refs_required": bool(spec.get("source_refs_required", False)),
            "examples": spec.get("examples", []),
            "version": spec.get("version", "1.0.0"),
            "status": "active",
        })
    return rows


def seed_registry(db) -> int:
    """UPSERT the whole L1 registry into entity_type / relation_type (idempotent).

    Safe to run on every deploy before any L2/L3 writer; old rows are updated by
    type_code/relation_code, no rows are deleted. Returns (entities, relations).
    """
    registry = get_common_registry()
    ent_rows = _entity_type_rows(registry)
    rel_rows = _relation_type_rows(registry)
    for r in ent_rows:
        db.upsert("entity_type", r, "type_code")
    for r in rel_rows:
        db.upsert("relation_type", r, "relation_code")
    return len(ent_rows), len(rel_rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate, export, and optionally seed the L1 registry")
    parser.add_argument("--out", type=Path, help="Write a JSON registry snapshot")
    parser.add_argument("--seed", action="store_true",
                        help="UPSERT the L1 registry into entity_type/relation_type "
                             "(required before any L2/L3 write — see schema.sql FKs)")
    args = parser.parse_args()
    errors = validate_common()
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    payload = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if args.seed:
        from legacy.core.db import DB

        with DB.from_env() as db:
            n_ent, n_rel = seed_registry(db)
        print(f"[publish_l1] seeded entity_type={n_ent} relation_type={n_rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
