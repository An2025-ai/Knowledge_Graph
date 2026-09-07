"""New-runtime knowledge construction pipeline.

The pipeline follows the retired runtime's conceptual stages without importing
anything from ``legacy``:

    evidence units → rule/LLM candidates → normalization → fusion
    → entity resolution → active SQLite graph rows

Rules and fusion are pure shared primitives; this module owns the optional
external LLM boundary and converts the result into the desktop repository's
write model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from shared.extraction.candidate_extraction import pre_extract
from shared.extraction.entity_rules import (
    extract_entity_candidates,
    extract_relation_candidates,
)
from shared.extraction.normalization import fuse_candidates, normalize_name, normalize_text
from shared.knowledge.prompt_builder import build_extraction_prompt
from shared.knowledge.registry import get_common_registry

from ..config import RuntimeSettings
from ..repositories import stable_id
from .llm import OpenAICompatibleClient


@dataclass
class KnowledgeBuild:
    candidates: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    llm_used: bool = False


class KnowledgeBuildPipeline:
    """Build graph-ready rows from evidence units without legacy imports."""

    def __init__(self, settings: RuntimeSettings | None = None):
        self.settings = settings or RuntimeSettings()

    def build(
        self,
        *,
        document_id: str,
        content: str,
        units: list[dict[str, Any]],
        layer: str,
        brand_id: str | None,
        tenant_id: str,
        content_hash: str,
    ) -> KnowledgeBuild:
        get_common_registry().require_profile(layer)
        raw: list[dict[str, Any]] = []

        for unit in units:
            text = unit.get("text", "")
            for candidate in pre_extract(text, profile_id=layer):
                raw.append(self._candidate_from_payload(candidate, unit))

        entity_candidates = extract_entity_candidates(
            content, profile_id=layer, brand_id=brand_id
        )
        first_unit = units[0] if units else {}
        raw.extend(self._candidate_from_payload(candidate, first_unit) for candidate in entity_candidates)
        raw.extend(
            self._candidate_from_payload(candidate, first_unit)
            for candidate in extract_relation_candidates(entity_candidates, profile_id=layer)
        )

        llm_used = False
        if self._llm_enabled():
            for unit in units[:20]:
                try:
                    llm_candidates = self._llm_extract(unit.get("text", ""), layer)
                except Exception:
                    # Import remains usable when the optional external model is
                    # unavailable. Deterministic candidates are still saved.
                    continue
                raw.extend(self._candidate_from_payload(candidate, unit) for candidate in llm_candidates)
                llm_used = llm_used or bool(llm_candidates)

        fused = fuse_candidates(raw)
        entity_rows = self._entities(
            fused, document_id=document_id, layer=layer,
            brand_id=brand_id, tenant_id=tenant_id, content_hash=content_hash,
        )
        relations = self._relations(
            fused, entity_rows, document_id=document_id,
            layer=layer, brand_id=brand_id, tenant_id=tenant_id,
        )
        candidate_rows = [
            self._candidate_row(candidate, document_id=document_id, content_hash=content_hash)
            for candidate in fused
            if candidate.get("candidate_type") != "entity"
        ]
        return KnowledgeBuild(
            candidates=candidate_rows,
            entities=entity_rows,
            relations=relations,
            llm_used=llm_used,
        )

    @staticmethod
    def _candidate_from_payload(candidate: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
        payload = candidate.get("candidate_payload") or {}
        ctype = candidate.get("candidate_type", "statement")
        subject = {
            "name": payload.get("name") or payload.get("subject_name"),
            "entity_type": payload.get("entity_type") or payload.get("subject_type"),
        }
        obj = {
            "name": payload.get("object_name"),
            "entity_type": payload.get("object_type"),
        }
        return {
            "candidate_type": ctype,
            "subject": {key: value for key, value in subject.items() if value},
            "predicate_type": payload.get("type") or payload.get("relation"),
            "object": {key: value for key, value in obj.items() if value},
            "metric": payload if ctype == "metric" else {},
            "statement": {"text": payload.get("value") or payload.get("text", "")},
            "evidence_text": unit.get("text", ""),
            "evidence_unit_id": unit.get("unit_id"),
            "confidence": candidate.get("confidence", 0.5),
            "extraction_method": [candidate.get("generator", "rule")],
        }

    def _candidate_row(
        self, candidate: dict[str, Any], *, document_id: str, content_hash: str
    ) -> dict[str, Any]:
        candidate_id = stable_id("kc", document_id, candidate.get("fusion_key"))
        return {
            "id": candidate_id,
            "candidate_type": candidate.get("candidate_type", "statement"),
            "subject": candidate.get("subject") or {},
            "predicate_type": candidate.get("predicate_type"),
            "object": candidate.get("object") or {},
            "metric": candidate.get("metric") or {},
            "statement": candidate.get("statement") or {},
            "evidence_text": candidate.get("evidence_text", "")[:4000],
            "confidence": candidate.get("confidence", 0.5),
            "extraction_method": candidate.get("extraction_method") or ["rule"],
            "content_hash": content_hash,
            "evidence_refs": candidate.get("evidence_refs") or [],
        }

    def _entities(
        self,
        candidates: list[dict[str, Any]],
        *,
        document_id: str,
        layer: str,
        brand_id: str | None,
        tenant_id: str,
        content_hash: str,
    ) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        allowed = get_common_registry().entity_types(layer)

        def add(name: str | None, entity_type: str | None, candidate: dict[str, Any]) -> dict[str, Any] | None:
            name = normalize_text(name)
            entity_type = entity_type or "organization"
            key = (entity_type, normalize_name(name))
            if not name or entity_type not in allowed:
                return None
            row = rows.get(key)
            if row is None:
                row = {
                    "id": stable_id("ent", layer, brand_id or "", entity_type, normalize_name(name)),
                    "type": entity_type,
                    "name": name,
                    "layer": layer,
                    "brand_id": brand_id,
                    "tenant_id": tenant_id,
                    "properties": {
                        "source_document_id": document_id,
                        "content_hash": content_hash,
                        "aliases": [],
                        "evidence_refs": [],
                    },
                }
                rows[key] = row
            properties = row["properties"]
            for ref in candidate.get("evidence_refs") or []:
                if ref not in properties["evidence_refs"]:
                    properties["evidence_refs"].append(ref)
            return row

        for candidate in candidates:
            if candidate.get("candidate_type") not in {"entity", "relation"}:
                continue
            subject = candidate.get("subject") or {}
            add(subject.get("name"), subject.get("entity_type"), candidate)
            obj = candidate.get("object") or {}
            add(obj.get("name"), obj.get("entity_type"), candidate)
        return list(rows.values())

    def _relations(
        self,
        candidates: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        *,
        document_id: str,
        layer: str,
        brand_id: str | None,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        allowed = get_common_registry().relation_types(layer)
        entity_by_key = {
            (row["type"], normalize_name(row["name"])): row for row in entities
        }
        relations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.get("candidate_type") != "relation":
                continue
            relation_type = candidate.get("predicate_type")
            subject = candidate.get("subject") or {}
            obj = candidate.get("object") or {}
            source = entity_by_key.get((subject.get("entity_type"), normalize_name(subject.get("name"))))
            target = entity_by_key.get((obj.get("entity_type"), normalize_name(obj.get("name"))))
            if not relation_type or relation_type not in allowed or not source or not target:
                continue
            relation_id = stable_id("rel", source["id"], target["id"], relation_type, document_id)
            if relation_id in seen:
                continue
            seen.add(relation_id)
            relations.append({
                "id": relation_id,
                "source_id": source["id"],
                "target_id": target["id"],
                "relation_type": relation_type,
                "confidence": candidate.get("confidence", 0.6),
                "properties": {
                    "source_document_id": document_id,
                    "tenant_id": tenant_id,
                    "brand_id": brand_id,
                    "extraction": candidate.get("extraction_method") or ["rule"],
                    "evidence_refs": candidate.get("evidence_refs") or [],
                },
            })
        return relations

    def _llm_enabled(self) -> bool:
        return self.settings.llm_provider == "openai-compatible" and bool(
            self.settings.llm_base_url and self.settings.llm_model
        )

    def _llm_extract(self, text: str, profile_id: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        client = OpenAICompatibleClient(
            base_url=self.settings.llm_base_url,
            model=self.settings.llm_model,
            key_reference=self.settings.api_key_reference,
        )
        response = client.chat([
            {"role": "system", "content": build_extraction_prompt(profile_id)},
            {
                "role": "user",
                "content": "只处理下面这段证据，返回符合系统 JSON 示例的对象，不要输出 Markdown：\n" + text[:12000],
            },
        ])
        payload = self._parse_json(response)
        registry = get_common_registry()
        allowed_entities = registry.entity_types(profile_id, extractable_only=True)
        allowed_relations = registry.relation_types(profile_id, extractable_only=True)
        candidates: list[dict[str, Any]] = []
        for item in payload.get("entities") or []:
            entity_type = item.get("type") or item.get("entity_type")
            name = normalize_text(item.get("canonical_name") or item.get("name"))
            if name and entity_type in allowed_entities:
                candidates.append({
                    "candidate_type": "entity",
                    "candidate_payload": {"name": name, "entity_type": entity_type},
                    "confidence": float(item.get("confidence", 0.75)),
                    "generator": "llm:structured",
                })
        for item in payload.get("relations") or []:
            relation = item.get("relation") or item.get("type")
            subject = item.get("subject") or {}
            obj = item.get("object") or {}
            if isinstance(subject, str):
                subject = {"name": subject}
            if isinstance(obj, str):
                obj = {"name": obj}
            if relation not in allowed_relations or not subject.get("name") or not obj.get("name"):
                continue
            candidates.append({
                "candidate_type": "relation",
                "candidate_payload": {
                    "subject_name": subject.get("name"),
                    "subject_type": subject.get("type") or subject.get("entity_type"),
                    "object_name": obj.get("name"),
                    "object_type": obj.get("type") or obj.get("entity_type"),
                    "type": relation,
                },
                "confidence": float(item.get("confidence", 0.7)),
                "generator": "llm:structured",
            })
        for item in payload.get("statements") or []:
            text_value = normalize_text(item.get("text") or item.get("statement"))
            if text_value:
                candidates.append({
                    "candidate_type": "statement",
                    "candidate_payload": {
                        "name": item.get("subject_name"),
                        "entity_type": item.get("subject_type"),
                        "value": text_value,
                    },
                    "confidence": float(item.get("confidence", 0.65)),
                    "generator": "llm:structured",
                })
        return candidates

    @staticmethod
    def _parse_json(value: str) -> dict[str, Any]:
        text = value.strip()
        if text.startswith("```"):
            text = text.strip("`").replace("json\n", "", 1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM extraction did not return a JSON object")
        payload = json.loads(text[start:end + 1])
        if not isinstance(payload, dict):
            raise ValueError("LLM extraction JSON must be an object")
        return payload
