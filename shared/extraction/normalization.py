"""Candidate normalization and deterministic fusion primitives.

These functions are deliberately independent from SQLite, FastAPI and model
providers.  The desktop runtime can therefore use the same extraction
contract as future batch or server runtimes without importing the retired
``legacy`` package.
"""

from __future__ import annotations

import copy
import re
from typing import Any


_SEPARATOR_RE = re.compile(r"[\s，,、。;；：:]+")


def normalize_name(value: Any) -> str:
    """Normalize a mention for equality while keeping the original display name."""
    return _SEPARATOR_RE.sub("", str(value or "")).casefold()


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy without changing the source extraction result."""
    normalized = copy.deepcopy(candidate)
    subject = normalized.setdefault("subject", {}) or {}
    if subject.get("name"):
        subject["name"] = normalize_text(subject["name"]).rstrip("。；，、")
    obj = normalized.setdefault("object", {}) or {}
    if obj.get("name"):
        obj["name"] = normalize_text(obj["name"]).rstrip("。；，、")
    statement = normalized.setdefault("statement", {}) or {}
    if statement.get("text"):
        statement["text"] = normalize_text(statement["text"])
    return normalized


def candidate_key(candidate: dict[str, Any]) -> str:
    """Build the deterministic fusion key used for same-fact grouping."""
    subject = candidate.get("subject") or {}
    obj = candidate.get("object") or {}
    metric = candidate.get("metric") or {}
    statement = candidate.get("statement") or {}
    ctype = candidate.get("candidate_type") or "statement"
    subject_key = f"{subject.get('entity_type') or 'organization'}::{normalize_name(subject.get('name'))}"
    object_key = f"{obj.get('entity_type') or ''}::{normalize_name(obj.get('name'))}"
    if ctype == "relation":
        value = candidate.get("predicate_type") or ""
    elif ctype == "metric":
        value = f"{metric.get('type') or ''}::{normalize_text(metric.get('value'))}"
    elif ctype == "entity":
        value = subject_key
    else:
        value = normalize_text(statement.get("text"))
    return "::".join((ctype, subject_key, value, object_key))


def fuse_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge same-fact candidates and retain their evidence/provenance."""
    grouped: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        candidate = normalize_candidate(raw)
        key = candidate_key(candidate)
        current = grouped.get(key)
        evidence_text = normalize_text(candidate.get("evidence_text"))
        unit_id = candidate.get("evidence_unit_id")
        if current is None:
            current = candidate
            current["fusion_key"] = key
            current["evidence_refs"] = []
            grouped[key] = current
        current["confidence"] = max(
            float(current.get("confidence", 0.5)), float(candidate.get("confidence", 0.5))
        )
        methods = list(current.get("extraction_method") or [])
        for method in candidate.get("extraction_method") or []:
            if method not in methods:
                methods.append(method)
        current["extraction_method"] = methods
        refs = current["evidence_refs"]
        ref = {"evidence_unit_id": unit_id, "quote": evidence_text[:4000]}
        if ref not in refs and (unit_id or evidence_text):
            refs.append(ref)
        if len(refs) > 20:
            del refs[20:]
    return list(grouped.values())
