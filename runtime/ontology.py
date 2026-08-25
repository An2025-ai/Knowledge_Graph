"""Profile-scoped access to the independent L2 and L3 ontologies."""
from __future__ import annotations

from runtime.common.registry import get_common_registry


class Ontology:
    def __init__(self) -> None:
        self.registry = get_common_registry()

    def is_valid_entity_type_for_profile(self, t: str, profile_id: str) -> bool:
        return t in self.registry.entity_types(profile_id)

    def is_valid_relation_type_for_profile(self, r: str, profile_id: str) -> bool:
        return r in self.registry.relation_types(profile_id)

    def is_valid_domain_range_for_profile(
        self, relation: str, subject_type: str, object_type: str, profile_id: str
    ) -> bool:
        return self.registry.is_valid_relation(relation, subject_type, object_type, profile_id)

    def is_valid_statement_class_for_profile(self, c: str, profile_id: str) -> bool:
        return c in self.registry.statement_classes(profile_id)


_default_ontology: Ontology | None = None


def get_ontology() -> Ontology:
    global _default_ontology
    if _default_ontology is None:
        _default_ontology = Ontology()
    return _default_ontology


if __name__ == "__main__":
    registry = get_common_registry()
    for profile_id in sorted(registry.profiles):
        print(
            profile_id,
            "entity types:", len(registry.entity_types(profile_id)),
            "relation types:", len(registry.relation_types(profile_id)),
        )
