"""Build the stable, provenance-aware context package consumed by LLMs."""
from __future__ import annotations

from typing import Any

from engine.common.registry import get_common_registry


def build_context_package(
    query: str,
    *,
    scope: dict[str, Any] | None = None,
    entities: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    assertions: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    missing_information: list[str] | None = None,
) -> dict[str, Any]:
    """Return a deterministic retrieval contract without changing the graph."""
    registry = get_common_registry()
    package = {
        "query": query,
        "scope": scope or {},
        "entities": entities or [],
        "relations": relations or [],
        "assertions": assertions or [],
        "evidence": evidence or [],
        "conflicts": conflicts or [],
        "missing_information": missing_information or [],
        "retrieval_trace": [],
    }
    package["retrieval_contract_version"] = registry.retrieval_contract.get("meta", {}).get("version")
    return package


def validate_context_package(package: dict[str, Any]) -> list[str]:
    required = set(
        get_common_registry().retrieval_contract.get("context_package", {}).get("required_fields", [])
    )
    return [f"missing context package field: {field}" for field in sorted(required - set(package))]
