"""Ontology validation for LLM extraction output (OPTIMIZATION_TECH_PLAN.md §4.3).

Applies business-rule checks against the L1 ontology after Pydantic shape
validation:
  - entity type in ontology
  - relation type in ontology
  - relation domain/range valid
  - statement_class in the four allowed classes
  - confidence in [0,1]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.knowledge.registry import get_common_registry


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)


class OntologyValidator:
    def __init__(self, ontology=None, profile_id: str | None = None) -> None:
        if not profile_id:
            raise ValueError("profile_id is required for ontology validation")
        self.registry = ontology or get_common_registry()
        self.profile_id = profile_id

    def validate_entity(self, entity: dict) -> list[str]:
        errors: list[str] = []
        etype = entity.get("type")
        if etype not in self.registry.entity_types(self.profile_id):
            errors.append(f"unknown entity type '{etype}'")
        return errors

    def validate_relation(self, relation: dict, entity_by_id: dict[str, dict]) -> list[str]:
        errors: list[str] = []
        rtype = relation.get("relation")
        if rtype not in self.registry.relation_types(self.profile_id):
            errors.append(f"unknown relation type '{rtype}'")
            return errors
        subj_id = relation.get("subject")
        obj_id = relation.get("object")
        subj = entity_by_id.get(subj_id)
        obj = entity_by_id.get(obj_id)
        if subj is None:
            errors.append(f"relation {rtype}: subject '{subj_id}' not found")
        if obj is None:
            errors.append(f"relation {rtype}: object '{obj_id}' not found")
        if subj and obj:
            subject_type = subj.get("type")
            object_type = obj.get("type")
            valid = self.registry.is_valid_relation(
                rtype, subject_type, object_type, self.profile_id
            )
            if not valid:
                errors.append(
                    f"relation {rtype}: domain/range invalid "
                    f"({subject_type} -> {object_type})"
                )
        conf = relation.get("confidence")
        if conf is not None and not (0.0 <= conf <= 1.0):
            errors.append(f"relation {rtype}: confidence {conf} out of [0,1]")
        return errors

    def validate_result(self, payload: dict[str, Any]) -> ValidationResult:
        """Validate the full extracted payload (entities/relations/statements)."""
        result = ValidationResult()
        entities = payload.get("entities", [])
        relations = payload.get("relations", [])
        statements = payload.get("statements", [])
        entity_by_id = {e.get("id"): e for e in entities}

        for e in entities:
            for err in self.validate_entity(e):
                result.add(f"entity {e.get('id')}: {err}")
        for r in relations:
            for err in self.validate_relation(r, entity_by_id):
                result.add(f"relation {r.get('subject')}-{r.get('relation')}: {err}")
        for s in statements:
            sc = s.get("statement_class")
            valid_class = sc in self.registry.statement_classes(self.profile_id)
            if sc and not valid_class:
                result.add(f"statement: invalid statement_class '{sc}'")
        return result


def validate_ontology(
    payload: dict[str, Any], ontology=None, profile_id: str | None = None
) -> ValidationResult:
    return OntologyValidator(ontology, profile_id=profile_id).validate_result(payload)
