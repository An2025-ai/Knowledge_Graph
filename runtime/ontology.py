"""Load L1 ontology (entity types + relation domain/range) from YAML.

Used by ontology_validator and extraction_schema to enforce the L1/L3
ontology constraints on LLM extraction output.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]  # Knowledge_Graph root
ENTITIES_YAML = ROOT / "common_knowledge" / "ontology" / "entities.yaml"
RELATIONS_YAML = ROOT / "common_knowledge" / "ontology" / "relations.yaml"


class Ontology:
    def __init__(self) -> None:
        self.entity_types: set[str] = set()
        self.relation_types: dict[str, dict] = {}  # relation -> {subject_types, object_types}
        self.statement_classes: set[str] = {"fact", "claim", "observation", "inference"}
        self._load()

    def _load(self) -> None:
        if ENTITIES_YAML.exists():
            e = yaml.safe_load(ENTITIES_YAML.read_text(encoding="utf-8")) or {}
            for et in e.get("entity_types", []):
                t = et.get("type")
                if t:
                    self.entity_types.add(t)
        if RELATIONS_YAML.exists():
            r = yaml.safe_load(RELATIONS_YAML.read_text(encoding="utf-8")) or {}
            for rt in r.get("relation_types", []):
                rel = rt.get("relation")
                if rel:
                    self.relation_types[rel] = {
                        "subject_types": set(rt.get("subject_types", [])),
                        "object_types": set(rt.get("object_types", [])),
                    }

    def is_valid_entity_type(self, t: str) -> bool:
        return t in self.entity_types

    def is_valid_relation_type(self, r: str) -> bool:
        return r in self.relation_types

    def is_valid_domain_range(self, relation: str, subject_type: str, object_type: str) -> bool:
        """Check relation domain/range against the ontology (if the relation is known)."""
        spec = self.relation_types.get(relation)
        if not spec:
            return False
        return subject_type in spec["subject_types"] and object_type in spec["object_types"]

    def is_valid_statement_class(self, c: str) -> bool:
        return c in self.statement_classes


_default_ontology: Ontology | None = None


def get_ontology() -> Ontology:
    global _default_ontology
    if _default_ontology is None:
        _default_ontology = Ontology()
    return _default_ontology


if __name__ == "__main__":
    o = get_ontology()
    print("entity types:", len(o.entity_types))
    print("relation types:", len(o.relation_types))
    print("has_capability domain/range ok (product->capability):",
          o.is_valid_domain_range("has_capability", "product", "capability"))