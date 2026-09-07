"""Independent API and CLI for L1 entity type definitions."""
from __future__ import annotations

import json
from typing import Any

from shared.knowledge.registry import get_common_registry


def list_entity_types(profile_id: str | None = None) -> list[dict[str, Any]]:
    registry = get_common_registry()
    codes = registry.entity_types(profile_id)
    return [registry.entity_metadata(code, profile_id) for code in sorted(codes)]


def get_entity_type(code: str, profile_id: str | None = None) -> dict[str, Any]:
    registry = get_common_registry()
    if code not in registry.entity_types(profile_id):
        raise KeyError(f"unknown entity type: {code}")
    return registry.entity_metadata(code, profile_id)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="List L1 entity type definitions")
    parser.add_argument("--profile", required=True, choices=["l2_industry", "l3_brand"])
    args = parser.parse_args()
    print(json.dumps(list_entity_types(args.profile), ensure_ascii=False, indent=2))
