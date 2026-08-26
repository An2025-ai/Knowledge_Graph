"""Single L1 contract validation entry point."""
from __future__ import annotations

import json

from engine.common.registry import get_common_registry


def validate_common() -> list[str]:
    registry = get_common_registry()
    return registry.validate_profiles() + registry.validate_common_contracts()


if __name__ == "__main__":
    errors = validate_common()
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
