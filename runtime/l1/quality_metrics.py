"""Independent API and CLI for L1 construction-quality metrics."""
from __future__ import annotations

import json
from typing import Any

from runtime.l1.registry import get_l1_registry


def list_quality_metrics() -> list[dict[str, Any]]:
    registry = get_l1_registry()
    return [registry.quality_metric_specs[code] for code in sorted(registry.quality_metric_specs)]


if __name__ == "__main__":
    print(json.dumps(list_quality_metrics(), ensure_ascii=False, indent=2))
