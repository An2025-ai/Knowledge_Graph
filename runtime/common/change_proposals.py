"""Validate L1 change proposals without mutating active definitions."""
from __future__ import annotations

from typing import Any


ALLOWED_TYPES = {
    "add_entity_type", "add_relation_type", "modify_constraint", "modify_policy",
    "deprecate_type", "revise_assertion",
}
ALLOWED_STATES = {"draft", "validated", "benchmarked", "approved", "published", "rejected"}


def validate_change_proposal(proposal: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not proposal.get("proposal_id"):
        errors.append("proposal_id is required")
    if proposal.get("proposal_type") not in ALLOWED_TYPES:
        errors.append(f"proposal_type must be one of {sorted(ALLOWED_TYPES)}")
    if proposal.get("status", "draft") not in ALLOWED_STATES:
        errors.append(f"status must be one of {sorted(ALLOWED_STATES)}")
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
