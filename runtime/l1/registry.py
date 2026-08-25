"""Configuration-driven L1 ontology registry.

The registry is the single runtime reader for L1 ontology/profile YAML. It
keeps the existing YAML files as the source of truth, while giving pipelines a
profile-aware API instead of hard-coded entity/relation lists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "common_knowledge"
PROFILES_DIR = COMMON / "schema_profiles"
POLICIES_DIR = COMMON / "policies"
GOVERNANCE_YAML = COMMON / "contracts" / "governance.yaml"
PROTOCOLS_YAML = COMMON / "contracts" / "protocols.yaml"
EXTRACTION_RULES_YAML = COMMON / "schema_profiles" / "extraction_rules.yaml"

# ontology_group slug -> Chinese module display name (used in extraction prompts).
_MODULE_NAMES = {
    "market_structure": "市场结构",
    "user_demand": "用户与需求",
    "competition": "竞品格局",
    "opportunity_risk": "机会与风险",
    "brand_identity": "品牌身份",
    "product_solution": "产品服务",
    "technical_capability": "技术能力",
    "customer_case": "客户案例",
    "competitive": "竞争格局",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _to_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _upper_snake(value: str) -> str:
    out = []
    previous_lower = False
    for char in value:
        if char.isupper() and previous_lower:
            out.append("_")
        if char.isalnum():
            out.append(char.upper())
            previous_lower = char.islower() or char.isdigit()
        else:
            if out and out[-1] != "_":
                out.append("_")
            previous_lower = False
    return "".join(out).strip("_") or value.upper()


def _pascal(value: str) -> str:
    parts = [part for part in value.replace("-", "_").split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or value


@dataclass(frozen=True)
class SchemaProfile:
    profile_id: str
    layer: str
    allowed_entity_types: set[str] = field(default_factory=set)
    allowed_relation_types: set[str] = field(default_factory=set)
    statement_classes: set[str] = field(default_factory=set)
    entity_type_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    relation_type_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    promotion_policy: dict[str, Any] = field(default_factory=dict)
    entity_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    relation_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    metric_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    ontology_files: dict[str, str] = field(default_factory=dict)
    cross_layer_access: bool = False


class L1Registry:
    def __init__(self) -> None:
        self.profiles = self._load_profiles()
        self.entity_specs = {
            f"{profile_id}.{code}": spec
            for profile_id, profile in self.profiles.items()
            for code, spec in profile.entity_specs.items()
        }
        self.relation_specs = {
            f"{profile_id}.{code}": spec
            for profile_id, profile in self.profiles.items()
            for code, spec in profile.relation_specs.items()
        }
        self.metric_specs = {
            f"{profile_id}.{code}": spec
            for profile_id, profile in self.profiles.items()
            for code, spec in profile.metric_specs.items()
        }
        self.governance_contract = _load_yaml(GOVERNANCE_YAML)
        self.protocol_contract = _load_yaml(PROTOCOLS_YAML)
        self.extraction_contract = _load_yaml(EXTRACTION_RULES_YAML)
        self.assertion_specs = self._index_items(
            self.governance_contract.get("assertion_types", []), "code"
        )
        self.context_specs = self._index_items(
            self.governance_contract.get("context_types", []), "code"
        )
        self.role_specs, self.operation_specs = self._load_protocol_operations(self.protocol_contract)
        self.quality_metric_specs = self._index_items(
            self.governance_contract.get("quality_metrics", []), "code"
        )
        self.policy_specs = self._load_policies()
        self.retrieval_contract = self._find_role_contract(self.protocol_contract, "consumer", "retrieval_contract")
        self.update_protocol = self._find_role_contract(self.protocol_contract, "governor", "update_protocol")

    @staticmethod
    def _load_indexed(path: Path, key: str, code_key: str) -> dict[str, dict[str, Any]]:
        data = _load_yaml(path)
        return L1Registry._index_items(data.get(key, []), code_key)

    @staticmethod
    def _index_items(items: list[dict[str, Any]], code_key: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            code = item.get(code_key)
            if code:
                result[str(code)] = item
        return result

    @staticmethod
    def _load_policies() -> dict[str, dict[str, Any]]:
        policies: dict[str, dict[str, Any]] = {}
        for path in POLICIES_DIR.glob("*.yaml"):
            data = _load_yaml(path)
            policies[path.stem] = data
        return policies

    @staticmethod
    def _load_protocol_operations(
        protocol: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """Parse role-based operation groups into role_specs and flattened operation_specs."""
        role_specs: dict[str, dict[str, Any]] = {}
        operation_specs: dict[str, dict[str, Any]] = {}
        for role_group in protocol.get("operation_roles", []):
            role = role_group.get("role")
            if not role:
                continue
            write_mode = role_group.get("write_mode")
            ops: list[dict[str, Any]] = []
            for op in role_group.get("operations", []):
                code = op.get("code")
                if not code:
                    continue
                enriched = dict(op)
                enriched["role"] = role
                enriched["write_mode"] = write_mode
                operation_specs[code] = enriched
                ops.append(code)
            role_specs[role] = {
                "role": role,
                "name": role_group.get("name"),
                "description": role_group.get("description"),
                "write_mode": write_mode,
                "direction": role_group.get("direction"),
                "operations": ops,
            }
        return role_specs, operation_specs

    @staticmethod
    def _find_role_contract(
        protocol: dict[str, Any], role: str, contract_key: str
    ) -> dict[str, Any]:
        """Find a nested contract (retrieval_contract / update_protocol) under a specific role."""
        for role_group in protocol.get("operation_roles", []):
            if role_group.get("role") == role and contract_key in role_group:
                return role_group[contract_key]
        return {}

    @staticmethod
    def _ontology_path(value: str | None) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else ROOT / path

    @classmethod
    def _load_ontology_index(
        cls, value: str | None, collection: str, code_key: str
    ) -> dict[str, dict[str, Any]]:
        path = cls._ontology_path(value)
        if not path:
            return {}
        return cls._index_items(_load_yaml(path).get(collection, []), code_key)

    def _load_profiles(self) -> dict[str, SchemaProfile]:
        profiles: dict[str, SchemaProfile] = {}
        if not PROFILES_DIR.exists():
            return profiles
        for path in PROFILES_DIR.glob("*_profile.yaml"):
            data = _load_yaml(path)
            profile_id = data.get("profile_id") or path.stem
            ontology_files = data.get("ontology") or {}
            entity_specs = self._load_ontology_index(
                ontology_files.get("entities"), "entity_types", "type"
            )
            relation_specs = self._load_ontology_index(
                ontology_files.get("relations"), "relation_types", "relation"
            )
            metric_specs = self._load_ontology_index(
                ontology_files.get("metrics"), "metrics", "metric"
            )
            profiles[profile_id] = SchemaProfile(
                profile_id=profile_id,
                layer=data.get("layer") or profile_id,
                allowed_entity_types=set(entity_specs),
                allowed_relation_types=set(relation_specs),
                statement_classes=_to_set(data.get("statement_classes")),
                entity_type_metadata={code: spec for code, spec in entity_specs.items()},
                relation_type_metadata={code: spec for code, spec in relation_specs.items()},
                promotion_policy=data.get("promotion_policy") or {},
                entity_specs=entity_specs,
                relation_specs=relation_specs,
                metric_specs=metric_specs,
                ontology_files={key: str(value) for key, value in ontology_files.items()},
                cross_layer_access=bool(data.get("cross_layer_access", False)),
            )
        return profiles

    def profile(self, profile_id: str | None = None) -> SchemaProfile:
        """Return one independent layer profile; there is no global business ontology."""
        if not profile_id:
            raise ValueError(
                "profile_id is required; use 'l2_industry' or 'l3_brand'. "
                "L1 does not expose a shared business ontology."
            )
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise ValueError(
                f"unknown schema profile '{profile_id}'. "
                f"Registered profiles: {sorted(self.profiles)}."
            )
        return profile

    def entity_types(self, profile_id: str | None = None, *, extractable_only: bool = False) -> set[str]:
        profile = self.profile(profile_id)
        allowed = set(profile.allowed_entity_types)
        if extractable_only:
            allowed = {
                type_code for type_code in allowed
                if profile.entity_specs.get(type_code, {}).get("extractable", True) is not False
            }
        return allowed

    def relation_types(self, profile_id: str | None = None, *, extractable_only: bool = False) -> set[str]:
        profile = self.profile(profile_id)
        allowed = set(profile.allowed_relation_types)
        if extractable_only:
            allowed = {
                relation for relation in allowed
                if profile.relation_specs.get(relation, {}).get("extractable", True) is not False
            }
        return allowed

    def metrics(self, profile_id: str) -> set[str]:
        return set(self.profile(profile_id).metric_specs)

    def statement_classes(self, profile_id: str | None = None) -> set[str]:
        profile = self.profile(profile_id)
        if profile.statement_classes:
            return set(profile.statement_classes)
        return {"fact", "claim", "observation", "inference"}

    def semantic_terms(self) -> list[dict[str, Any]]:
        return list(self.extraction_contract.get("semantic_terms", []))

    def narrative_chains(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        chains = self.extraction_contract.get("narrative_chains", [])
        if not profile_id:
            return list(chains)
        return [chain for chain in chains if chain.get("layer") == profile_id]

    def extraction_rules(self, profile_id: str | None = None) -> dict[str, Any]:
        rules = self.extraction_contract.get("profile_extraction_rules", {})
        if not profile_id:
            return {}
        return rules.get(profile_id, {})

    def prompt_output_rules(self) -> list[str]:
        return list(self.extraction_contract.get("prompt_output_rules", []))

    def layer_dimensions(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        """Derive module dimensions from the profile ontology's ontology_group.

        The ontology YAML is the single source of truth: every entity, relation
        and metric carries an `ontology_group`. This aggregates them into the
        `[{module, entity_types, relation_types, metrics}]` shape that the
        extraction prompt consumes, so the modules never drift from the ontology.
        """
        if not profile_id:
            return []
        profile = self.profile(profile_id)
        grouped: dict[str, dict[str, list[str]]] = {}
        for specs, key in (
            (profile.entity_specs, "entity_types"),
            (profile.relation_specs, "relation_types"),
            (profile.metric_specs, "metrics"),
        ):
            for code, spec in specs.items():
                group = spec.get("ontology_group")
                if not group:
                    continue
                bucket = grouped.setdefault(str(group), {})
                bucket.setdefault("entity_types", [])
                bucket.setdefault("relation_types", [])
                bucket.setdefault("metrics", [])
                bucket[key].append(code)
        # deterministically ordered, matching the original layer_dimensions shape
        result: list[dict[str, Any]] = []
        for group, bucket in sorted(grouped.items()):
            result.append(
                {
                    "module": _MODULE_NAMES.get(group, group),
                    "entity_types": sorted(bucket["entity_types"]),
                    "relation_types": sorted(bucket["relation_types"]),
                    "metrics": sorted(bucket["metrics"]),
                }
            )
        return result

    def prompt_output_schema(self) -> dict[str, Any]:
        return dict(self.extraction_contract.get("prompt_output_schema", {}))

    def require_profile(self, profile_id: str | None) -> SchemaProfile:
        """Return the required independent layer profile, raising if absent."""
        if not profile_id:
            raise ValueError("require_profile needs a non-empty profile_id")
        return self.profile(profile_id)

    def entity_metadata(self, entity_type: str, profile_id: str | None = None) -> dict[str, Any]:
        profile = self.profile(profile_id)
        return dict(profile.entity_specs.get(entity_type) or {})

    def relation_metadata(self, relation_type: str, profile_id: str | None = None) -> dict[str, Any]:
        profile = self.profile(profile_id)
        return dict(profile.relation_specs.get(relation_type) or {})

    def relation_domain_range(
        self, relation: str, profile_id: str | None = None
    ) -> tuple[set[str], set[str]]:
        spec = self.profile(profile_id).relation_specs.get(relation) or {}
        return _to_set(spec.get("subject_types")), _to_set(spec.get("object_types"))

    def is_valid_relation(self, relation: str, subject_type: str, object_type: str,
                          profile_id: str | None = None) -> bool:
        if relation not in self.relation_types(profile_id):
            return False
        subject_types, object_types = self.relation_domain_range(relation, profile_id)
        return subject_type in subject_types and object_type in object_types

    def neo4j_entity_label(self, entity_type: str) -> str | None:
        return _pascal(entity_type)

    def neo4j_relation_label(self, relation_type: str) -> str:
        return _upper_snake(relation_type)

    def operation_role(self, operation_code: str) -> str | None:
        """Return the role (producer/validator/consumer/governor) for an operation."""
        spec = self.operation_specs.get(operation_code)
        return spec.get("role") if spec else None

    def operations_for_role(self, role: str) -> list[str]:
        """Return operation codes assigned to a specific role."""
        role_info = self.role_specs.get(role)
        return list(role_info.get("operations", [])) if role_info else []

    def write_mode_for_role(self, role: str) -> str | None:
        """Return the write_mode constraint for a specific role."""
        role_info = self.role_specs.get(role)
        return role_info.get("write_mode") if role_info else None

    def validate_profile(self, profile_id: str) -> list[str]:
        # Use a non-raising lookup here: a validator reports unknown profiles as
        # an error string rather than raising (unlike profile()/entity_types(),
        # which fail fast so misconfigured pipelines abort).
        profile = self.profiles.get(profile_id)
        if not profile:
            return [f"unknown profile '{profile_id}'"]
        errors: list[str] = []
        if profile.cross_layer_access:
            errors.append(f"{profile_id}: cross_layer_access must be false")
        if not profile.entity_specs or not profile.relation_specs or not profile.metric_specs:
            errors.append(f"{profile_id}: entities, relations and metrics must all be defined")
        allowed_entities = set(profile.allowed_entity_types)
        for code, spec in profile.entity_specs.items():
            if spec.get("layer") != profile.layer:
                errors.append(f"{profile_id}: entity '{code}' has wrong layer")
            if spec.get("type_id") != f"{profile_id}.{code}":
                errors.append(f"{profile_id}: entity '{code}' has invalid type_id")
        for relation in sorted(profile.allowed_relation_types):
            spec = profile.relation_specs[relation]
            subject_types, object_types = self.relation_domain_range(relation, profile_id)
            unknown_subjects = sorted(subject_types - allowed_entities)
            unknown_objects = sorted(object_types - allowed_entities)
            if unknown_subjects:
                errors.append(
                    f"{profile_id}: relation '{relation}' has foreign subject types {unknown_subjects}"
                )
            if unknown_objects:
                errors.append(
                    f"{profile_id}: relation '{relation}' has foreign object types {unknown_objects}"
                )
            if spec.get("layer") != profile.layer:
                errors.append(f"{profile_id}: relation '{relation}' has wrong layer")
            if spec.get("relation_id") != f"{profile_id}.{relation}":
                errors.append(f"{profile_id}: relation '{relation}' has invalid relation_id")
        for code, spec in profile.metric_specs.items():
            if spec.get("layer") != profile.layer:
                errors.append(f"{profile_id}: metric '{code}' has wrong layer")
            if spec.get("external_layer_dependencies"):
                errors.append(f"{profile_id}: metric '{code}' depends on another layer")
        return errors

    def validate_profiles(self) -> list[str]:
        errors: list[str] = []
        for profile_id in sorted(self.profiles):
            errors.extend(self.validate_profile(profile_id))
        return errors

    def validate_l1_contracts(self) -> list[str]:
        """Validate the independent L1 contracts and cross-file references."""
        errors: list[str] = []
        for code, spec in self.assertion_specs.items():
            if not spec.get("name"):
                errors.append(f"assertion type '{code}' is missing name")
        for code, spec in self.context_specs.items():
            for assertion in spec.get("required_for", []):
                if assertion not in self.assertion_specs:
                    errors.append(f"context '{code}' references unknown assertion '{assertion}'")
        for code, spec in self.operation_specs.items():
            if not spec.get("input") or not spec.get("output"):
                errors.append(f"operation '{code}' must define input and output")
            if spec.get("write_mode") not in {"read_only", "candidate_only", "proposal_only"}:
                errors.append(f"operation '{code}' has invalid write_mode")
        allowed_roles = {"producer", "validator", "consumer", "governor"}
        for role, spec in self.role_specs.items():
            if role not in allowed_roles:
                errors.append(f"unknown operation role '{role}'")
            write_mode = spec.get("write_mode")
            if write_mode not in {"read_only", "candidate_only", "proposal_only"}:
                errors.append(f"role '{role}' has invalid write_mode '{write_mode}'")
            for op_code in spec.get("operations", []):
                if op_code not in self.operation_specs:
                    errors.append(f"role '{role}' references unknown operation '{op_code}'")
        required = set(self.retrieval_contract.get("context_package", {}).get("required_fields", []))
        if "query" not in required or "assertions" not in required:
            errors.append("retrieval contract must require query and assertions")
        lifecycle = self.update_protocol.get("change_lifecycle") or []
        if lifecycle[:1] != ["draft"] or lifecycle[-1:] != ["rejected"]:
            errors.append("update protocol lifecycle must start at draft and end at rejected")
        profile_rules = self.extraction_contract.get("profile_extraction_rules", {})
        for profile_id in profile_rules:
            if profile_id not in self.profiles:
                errors.append(f"extraction rules reference unknown profile '{profile_id}'")
        for chain in self.extraction_contract.get("narrative_chains", []):
            layer = chain.get("layer")
            if layer and layer not in self.profiles:
                errors.append(f"narrative chain references unknown profile '{layer}'")
        return errors


@lru_cache(maxsize=1)
def get_l1_registry() -> L1Registry:
    return L1Registry()


def reset_l1_registry_cache() -> None:
    get_l1_registry.cache_clear()
