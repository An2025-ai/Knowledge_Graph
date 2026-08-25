"""Single L1 contract validation entry point."""
from __future__ import annotations

import json

from runtime.l1.registry import get_l1_registry


def validate_l1() -> list[str]:
    registry = get_l1_registry()
    return registry.validate_profiles() + registry.validate_l1_contracts()


if __name__ == "__main__":
    errors = validate_l1()
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
