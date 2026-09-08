"""Deterministic entity and relation candidates for the new runtime.

This is a fresh, dependency-free implementation of the old runtime's rule
baseline.  It emits candidates instead of writing graph rows, leaving
normalization, fusion and persistence to separate layers.
"""

from __future__ import annotations

import re
from typing import Any

from shared.knowledge.registry import get_common_registry
from .normalization import normalize_name, normalize_text


_ORGANIZATION_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9·（）()\s]{2,32}?(?:有限公司|公司|集团)")
_PRODUCT_RE = re.compile(
    r"[A-Za-z0-9\u4e00-\u9fff·（）()\-\s]{2,32}?(?:平台|系统|智能体|工厂|解决方案|产品)"
)


def _items(value: str) -> list[str]:
    result: list[str] = []
    for item in re.split(r"[、,，/；;|]|\s+和\s+|\s+及\s+", value):
        item = normalize_text(item)
        item = re.sub(r"^(包括|主要包括|支持|提供|具备|拥有|面向|服务|针对|覆盖)\s*", "", item)
        if 2 <= len(item) <= 48 and item not in result:
            result.append(item)
    return result[:20]


def _allowed(profile_id: str, entity_type: str) -> bool:
    return entity_type in get_common_registry().entity_types(profile_id)


def _entity(name: str, entity_type: str, source: str) -> dict[str, Any]:
    return {
        "candidate_type": "entity",
        "candidate_payload": {"name": name, "entity_type": entity_type},
        "confidence": 0.72,
        "generator": source,
    }


def extract_entity_candidates(
    text: str, *, profile_id: str, brand_id: str | None = None
) -> list[dict[str, Any]]:
    """Extract organization/product/capability/audience mentions from text."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, entity_type: str, source: str) -> None:
        name = normalize_text(name).strip(":：，,、;；。")
        key = (entity_type, normalize_name(name))
        if not name or key in seen or not _allowed(profile_id, entity_type):
            return
        seen.add(key)
        result.append(_entity(name, entity_type, source))

    if brand_id and profile_id == "l3_brand":
        add(brand_id, "brand", "input:brand_id")
    for name in _ORGANIZATION_RE.findall(text):
        add(name, "organization", "regex:organization")
    for name in _PRODUCT_RE.findall(text):
        # Keep trigger words and a preceding organization from becoming part
        # of the product name: "Acme 公司提供 CRM 平台" -> "CRM 平台".
        name = re.split(
            r"(?:提供|推出|上线|发布|支持|具备|拥有|包括|面向|服务|针对|覆盖)",
            name,
            maxsplit=1,
        )[-1]
        add(name, "product", "regex:product")
    for sentence in re.findall(r"(?:支持|提供|具备|拥有|包括)([^。；\n]{2,160})", text):
        sentence = re.split(r"(?:面向|服务|针对|覆盖|获得|取得|通过)", sentence, maxsplit=1)[0]
        for name in _items(sentence):
            if normalize_name(name) not in {normalize_name(item["candidate_payload"]["name"]) for item in result}:
                add(name, "capability", "regex:capability")
    for sentence in re.findall(r"(?:面向|服务|针对|覆盖)([^。；\n]{2,100})", text):
        for name in _items(sentence):
            add(name, "audience", "regex:audience")
    return result


def extract_relation_candidates(
    entities: list[dict[str, Any]], *, profile_id: str
) -> list[dict[str, Any]]:
    """Derive conservative relation candidates from extracted entities."""
    allowed_relations = get_common_registry().relation_types(profile_id)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for candidate in entities:
        payload = candidate.get("candidate_payload") or {}
        by_type.setdefault(str(payload.get("entity_type")), []).append(payload)

    brands = by_type.get("brand", [])
    organizations = by_type.get("organization", [])
    products = by_type.get("product", [])
    capabilities = by_type.get("capability", [])
    audiences = by_type.get("audience", [])
    anchor = (brands or organizations or [None])[0]
    if anchor is None:
        return []

    result: list[dict[str, Any]] = []

    def add(source: dict[str, Any], target: dict[str, Any], relation: str) -> None:
        if relation not in allowed_relations or normalize_name(source.get("name")) == normalize_name(target.get("name")):
            return
        result.append({
            "candidate_type": "relation",
            "candidate_payload": {
                "subject_name": source.get("name"),
                "subject_type": source.get("entity_type"),
                "object_name": target.get("name"),
                "object_type": target.get("entity_type"),
                "type": relation,
            },
            "confidence": 0.68,
            "generator": f"rule:relation:{relation}",
        })

    for product in products:
        add(anchor, product, "offers")
        for capability in capabilities:
            add(product, capability, "has_capability")
    if not products:
        for capability in capabilities:
            add(anchor, capability, "has_capability")
    for audience in audiences:
        add(anchor, audience, "serves")
    return result
