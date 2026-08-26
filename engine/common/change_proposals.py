"""Validate L1 change proposals without mutating active definitions.

The allowed change types and lifecycle states are driven by the L1
``update_protocol`` contract (``common_knowledge/contracts/protocols.yaml`` /
``engine.common.registry``), with the literals kept as a degraded fallback so the
validator works even when the registry is unavailable. This keeps the validator
single-sourced: editing the governance contract updates validation automatically.
"""
from __future__ import annotations

from typing import Any


# Degraded fallback when the L1 registry (update_protocol) is not resolvable.
_FALLBACK_TYPES = {
    "add_entity_type", "add_relation_type", "modify_constraint", "modify_policy",
    "deprecate_type", "revise_assertion",
}
_FALLBACK_STATES = {"draft", "validated", "benchmarked", "approved", "published", "rejected"}


def _allowed_types() -> set[str]:
    try:
        from engine.common.registry import get_common_registry
        change_types = (get_common_registry().update_protocol or {}).get("change_types")
        if change_types:
            return set(change_types)
    except Exception:  # noqa: BLE001 - degraded fallback keeps validator usable
        pass
    return set(_FALLBACK_TYPES)


def _allowed_states() -> set[str]:
    try:
        from engine.common.registry import get_common_registry
        lifecycle = (get_common_registry().update_protocol or {}).get("change_lifecycle")
        if lifecycle:
            return set(lifecycle)
    except Exception:  # noqa: BLE001 - degraded fallback keeps validator usable
        pass
    return set(_FALLBACK_STATES)


def validate_change_proposal(proposal: dict[str, Any]) -> list[str]:
    allowed_types = _allowed_types()
    allowed_states = _allowed_states()
    errors: list[str] = []
    if not proposal.get("proposal_id"):
        errors.append("proposal_id is required")
    if proposal.get("proposal_type") not in allowed_types:
        errors.append(f"proposal_type must be one of {sorted(allowed_types)}")
    if proposal.get("status", "draft") not in allowed_states:
        errors.append(f"status must be one of {sorted(allowed_states)}")
    if not proposal.get("evidence"):
        errors.append("evidence is required")
    if proposal.get("status") == "published" and not proposal.get("rollback_plan"):
        errors.append("published proposals require rollback_plan")
    return errors


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Validate an L1 change proposal JSON")
    parser.add_argument("path")
    args = parser.parse_args()
    errors = validate_change_proposal(json.loads(open(args.path, encoding="utf-8").read()))
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
