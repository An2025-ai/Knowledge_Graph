"""Independent API and CLI for layer profiles."""
from __future__ import annotations

import json
from typing import Any

from engine.common.registry import get_common_registry


def list_profiles() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "layer": profile.layer,
            "entity_types": sorted(profile.allowed_entity_types),
            "relation_types": sorted(profile.allowed_relation_types),
            "statement_classes": sorted(profile.statement_classes),
            "promotion_policy": profile.promotion_policy,
        }
        for profile in sorted(get_common_registry().profiles.values(), key=lambda item: item.profile_id)
    ]


def get_profile(profile_id: str) -> dict[str, Any]:
    for profile in list_profiles():
        if profile["profile_id"] == profile_id:
            return profile
    raise KeyError(f"unknown schema profile: {profile_id}")


if __name__ == "__main__":
    print(json.dumps(list_profiles(), ensure_ascii=False, indent=2))
