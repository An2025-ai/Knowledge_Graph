"""Small L1-backed policy helpers used by runtime gates.

This module centralizes policy defaults so pipeline code can ask L1 what is
allowed instead of unpacking YAML dictionaries directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.l1.registry import get_l1_registry


@dataclass(frozen=True)
class PromotionPolicy:
    profile_id: str
    confidence_threshold: float
    source_authority_allowed: set[str]
    evidence_access_status_allowed: set[str]
    evidence_support_status_allowed: set[str]
    direct_stable_promotion: bool = True
    near_duplicate_threshold: float = 0.85
    semantic_near_duplicate_threshold: float = 0.92

    def source_authority_ok(self, authority_level: str | None) -> bool:
        return bool(authority_level) and authority_level in self.source_authority_allowed

    def evidence_ok(self, access_status: str | None, support_status: str | None) -> bool:
        return (
            bool(access_status)
            and bool(support_status)
            and access_status in self.evidence_access_status_allowed
            and support_status in self.evidence_support_status_allowed
        )


def load_promotion_policy(profile_id: str, default_threshold: float) -> PromotionPolicy:
    profile = get_l1_registry().profile(profile_id)
    raw: dict[str, Any] = profile.promotion_policy if profile else {}
    return PromotionPolicy(
        profile_id=profile_id,
        confidence_threshold=float(raw.get("default_confidence_threshold", default_threshold)),
        source_authority_allowed=set(raw.get("source_authority_allowed") or ["high", "medium"]),
        evidence_access_status_allowed=set(raw.get("evidence_access_status_allowed") or ["verified", "crawled", "ok"]),
        evidence_support_status_allowed=set(
            raw.get("evidence_support_status_allowed") or ["directly_supports", "partially_supports"]
        ),
        direct_stable_promotion=bool(raw.get("direct_stable_promotion", True)),
        near_duplicate_threshold=float(raw.get("near_duplicate_threshold", 0.85)),
        semantic_near_duplicate_threshold=float(raw.get("semantic_near_duplicate_threshold", 0.92)),
    )
