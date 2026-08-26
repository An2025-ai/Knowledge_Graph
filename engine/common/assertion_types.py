"""Independent API and CLI for L1 assertion types."""
from __future__ import annotations

import json
from typing import Any

from engine.common.registry import get_common_registry


def list_assertion_types() -> list[dict[str, Any]]:
    return [get_common_registry().assertion_specs[code] for code in sorted(get_common_registry().assertion_specs)]


def get_assertion_type(code: str) -> dict[str, Any]:
    try:
        return get_common_registry().assertion_specs[code]
    except KeyError as exc:
        raise KeyError(f"unknown assertion type: {code}") from exc


if __name__ == "__main__":
    print(json.dumps(list_assertion_types(), ensure_ascii=False, indent=2))
