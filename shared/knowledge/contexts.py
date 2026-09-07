"""Independent API and CLI for L1 context types."""
from __future__ import annotations

import json
from typing import Any

from shared.knowledge.registry import get_common_registry


def list_context_types() -> list[dict[str, Any]]:
    registry = get_common_registry()
    return [registry.context_specs[code] for code in sorted(registry.context_specs)]


if __name__ == "__main__":
    print(json.dumps(list_context_types(), ensure_ascii=False, indent=2))
