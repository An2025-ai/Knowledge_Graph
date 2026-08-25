"""Build a deterministic L1 registry snapshot for review or deployment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.l1.registry import get_l1_registry
from runtime.l1.validate import validate_l1


def build_snapshot() -> dict:
    registry = get_l1_registry()
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and export the L1 registry")
    parser.add_argument("--out", type=Path, help="Write a JSON registry snapshot")
    args = parser.parse_args()
    errors = validate_l1()
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    payload = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
