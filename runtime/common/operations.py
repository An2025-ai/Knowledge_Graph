"""Independent API and CLI for LLM operation contracts.

Operations are grouped by LLM role (producer / validator / consumer / governor),
each with its own write_mode permission boundary.
"""
from __future__ import annotations

import json
from typing import Any

from runtime.common.registry import get_common_registry


def list_operations() -> list[dict[str, Any]]:
    registry = get_common_registry()
    return [registry.operation_specs[code] for code in sorted(registry.operation_specs)]


def get_operation(code: str) -> dict[str, Any]:
    try:
        return get_common_registry().operation_specs[code]
    except KeyError as exc:
        raise KeyError(f"unknown LLM operation: {code}") from exc


def list_operation_roles() -> list[dict[str, Any]]:
    """Return the role-grouped operation contracts (from operation_roles in protocols.yaml)."""
    registry = get_common_registry()
    return [registry.role_specs[role] for role in sorted(registry.role_specs)]


def get_role(role: str) -> dict[str, Any]:
    try:
        return get_common_registry().role_specs[role]
    except KeyError as exc:
        raise KeyError(f"unknown LLM operation role: {role}") from exc


def write_mode_for(operation_code: str) -> str | None:
    """Return the write_mode permission bound to an operation's role."""
    spec = get_common_registry().operation_specs.get(operation_code)
    return spec.get("write_mode") if spec else None


if __name__ == "__main__":
    print(json.dumps(list_operation_roles(), ensure_ascii=False, indent=2))
