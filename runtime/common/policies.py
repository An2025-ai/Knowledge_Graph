"""Independent API and CLI for L1 governance policies."""
from __future__ import annotations

import json
from typing import Any

from runtime.common.registry import get_common_registry


def list_policies() -> list[dict[str, Any]]:
    registry = get_common_registry()
    return [
        {"code": code, "definition": registry.policy_specs[code]}
        for code in sorted(registry.policy_specs)
    ]


def get_policy(code: str) -> dict[str, Any]:
    try:
        return get_common_registry().policy_specs[code]
    except KeyError as exc:
        raise KeyError(f"unknown L1 policy: {code}") from exc


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(list_policies(), ensure_ascii=False, indent=2, default=str))
