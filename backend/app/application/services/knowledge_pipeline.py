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

from ...config import RuntimeSettings
from ...infrastructure.repositories import stable_id
from ...runtime_settings import SettingsStore
from ...infrastructure.providers.llm import OpenAICompatibleClient


@dataclass
class KnowledgeBuild:
    candidates: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relations: list[dict[str, Any]]
    llm_used: bool = False
    llm_attempted: bool = False
    llm_fallback_count: int = 0
    llm_error: str | None = None


class KnowledgeBuildPipeline:
    """Build graph-ready rows from evidence units without legacy imports."""

    def __init__(
        self,
        settings: RuntimeSettings | None = None,
        *,
        settings_store: SettingsStore | None = None,
    ):
        self.settings_store = settings_store or SettingsStore(settings or RuntimeSettings())

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
        settings = self.settings_store.snapshot()
        llm_attempted = self._llm_enabled(settings)
        llm_used = False
        llm_fallback_count = 0
        llm_errors: list[str] = []
        entity_candidates = extract_entity_candidates(
            "", profile_id=layer, brand_id=brand_id
        )

        for unit in units:
            text = unit.get("text", "")
            if not llm_attempted:
                raw.extend(
                    self._candidate_from_payload(candidate, unit)
                    for candidate in pre_extract(text, profile_id=layer)
                )
                continue

            try:
                # There is deliberately no per-document LLM budget. Every
                # evidence unit gets a model request while the configured
                # endpoint is available; only a failed request falls back to
                # deterministic extraction for that unit.
                llm_candidates = self._llm_extract(text, layer, settings)
            except Exception as exc:
                llm_candidates = []
                llm_errors.append(str(exc))

            if llm_candidates:
                raw.extend(self._candidate_from_payload(candidate, unit) for candidate in llm_candidates)
                llm_used = True
            else:
                # LLM is the primary extractor when configured. Rule output is
                # explicitly marked as fallback so it cannot be mistaken for a
                # successful model extraction in the database.
                llm_fallback_count += 1
                for candidate in pre_extract(text, profile_id=layer):
                    fallback = dict(candidate)
                    fallback["generator"] = f"fallback:{candidate.get('generator', 'rule')}"
                    raw.append(self._candidate_from_payload(fallback, unit))
                entity_candidates.extend(
                    extract_entity_candidates(text, profile_id=layer, brand_id=None)
                )

        if not llm_attempted:
            entity_candidates.extend(
                extract_entity_candidates(content, profile_id=layer, brand_id=None)
            )
        entity_candidates = self._dedupe_entity_candidates(entity_candidates)
        first_unit = units[0] if units else {}
        raw.extend(self._candidate_from_payload(candidate, first_unit) for candidate in entity_candidates)
        relation_candidates = extract_relation_candidates(entity_candidates, profile_id=layer)
        if llm_attempted and llm_fallback_count:
            for candidate in relation_candidates:
                candidate["generator"] = f"fallback:{candidate.get('generator', 'rule')}"
        raw.extend(
            self._candidate_from_payload(candidate, first_unit)
            for candidate in relation_candidates
        )

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
            llm_attempted=llm_attempted,
            llm_fallback_count=llm_fallback_count,
            llm_error=llm_errors[0][:500] if llm_errors else None,
        )

    @staticmethod
    def _dedupe_entity_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            payload = candidate.get("candidate_payload") or {}
            key = (
                str(payload.get("entity_type") or "organization"),
                normalize_name(payload.get("name")),
            )
            if not key[1] or key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        return result

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

    def _llm_enabled(self, settings: RuntimeSettings | None = None) -> bool:
        current = settings or self.settings_store.snapshot()
        return current.llm_provider == "openai-compatible" and bool(
            current.llm_base_url and current.llm_model
        )

    def _llm_extract(
        self,
        text: str,
        profile_id: str,
        settings: RuntimeSettings | None = None,
    ) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        current = settings or self.settings_store.snapshot()
        client = OpenAICompatibleClient(
            base_url=current.llm_base_url,
            model=current.llm_model,
            key_reference=current.api_key_reference,
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
        entity_by_id: dict[str, dict[str, str]] = {}
        entity_by_name: dict[str, dict[str, str]] = {}
        for item in payload.get("entities") or []:
            entity_type = item.get("type") or item.get("entity_type")
            name = normalize_text(item.get("canonical_name") or item.get("name"))
            if name and entity_type in allowed_entities:
                entity = {"name": name, "entity_type": str(entity_type)}
                entity_id = item.get("id") or item.get("entity_id")
                if entity_id:
                    entity_by_id[str(entity_id)] = entity
                entity_by_name[normalize_name(name)] = entity
                candidates.append({
                    "candidate_type": "entity",
                    "candidate_payload": {"name": name, "entity_type": entity_type},
                    "confidence": float(item.get("confidence", 0.75)),
                    "generator": "llm:structured",
                })
        for item in payload.get("relations") or []:
            relation = item.get("relation") or item.get("type")
            subject_name, subject_type = self._resolve_relation_endpoint(
                item.get("subject"),
                item.get("entity_type_subject") or item.get("subject_type"),
                entity_by_id,
                entity_by_name,
            )
            object_name, object_type = self._resolve_relation_endpoint(
                item.get("object"),
                item.get("entity_type_object") or item.get("object_type"),
                entity_by_id,
                entity_by_name,
            )
            if relation not in allowed_relations or not subject_name or not object_name:
                continue
            candidates.append({
                "candidate_type": "relation",
                "candidate_payload": {
                    "subject_name": subject_name,
                    "subject_type": subject_type,
                    "object_name": object_name,
                    "object_type": object_type,
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
    def _resolve_relation_endpoint(
        value: Any,
        type_hint: Any,
        entity_by_id: dict[str, dict[str, str]],
        entity_by_name: dict[str, dict[str, str]],
    ) -> tuple[str | None, str | None]:
        """Resolve an LLM relation endpoint to the entity row shape.

        The extraction prompt uses entity IDs in ``subject``/``object`` while
        some compatible models return names or nested ``{name, type}``
        objects. Accept all of these forms before the relation promotion
        stage performs its strict type/name lookup.
        """
        raw_name: Any = value
        raw_type: Any = type_hint
        if isinstance(value, dict):
            entity_id = value.get("id") or value.get("entity_id")
            resolved = entity_by_id.get(str(entity_id)) if entity_id else None
            raw_name = value.get("canonical_name") or value.get("name") or value.get("entity")
            raw_type = value.get("type") or value.get("entity_type") or type_hint
            if resolved:
                raw_name = raw_name or resolved["name"]
                raw_type = raw_type or resolved["entity_type"]

        name = normalize_text(str(raw_name)) if raw_name is not None else ""
        resolved = entity_by_id.get(name) or entity_by_name.get(normalize_name(name))
        if resolved:
            name = resolved["name"]
            raw_type = raw_type or resolved["entity_type"]
        entity_type = normalize_text(str(raw_type)) if raw_type is not None else ""
        return (name or None, entity_type or None)

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
