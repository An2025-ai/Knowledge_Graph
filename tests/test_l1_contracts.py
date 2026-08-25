import unittest

from runtime.l1.change_proposals import validate_change_proposal
from runtime.l1.registry import get_l1_registry
from runtime.l1.operations import list_operation_roles, get_role, write_mode_for
from runtime.l1.retrieval import build_context_package, validate_context_package
from runtime.l1.validate import validate_l1
from runtime.l1.profiles import list_profiles
from runtime.l1.policies import list_policies


class L1ContractTests(unittest.TestCase):
    def test_l1_contracts_are_valid(self):
        self.assertEqual(validate_l1(), [])

    def test_registry_exposes_independent_contracts(self):
        registry = get_l1_registry()
        l2 = registry.profile("l2_industry")
        l3 = registry.profile("l3_brand")
        self.assertEqual(len(l2.entity_specs), 15)
        self.assertEqual(len(l2.relation_specs), 17)
        self.assertEqual(len(l2.metric_specs), 17)
        self.assertEqual(len(l3.entity_specs), 15)
        self.assertEqual(len(l3.relation_specs), 17)
        self.assertEqual(len(l3.metric_specs), 17)
        for profile in (l2, l3):
            self.assertNotIn("metric", profile.entity_specs)
            self.assertNotIn("evidence", profile.entity_specs)
            self.assertFalse(profile.cross_layer_access)
        self.assertIn("fact", registry.assertion_specs)
        self.assertIn("valid_time", registry.context_specs)
        self.assertIn("extract_knowledge", registry.operation_specs)
        self.assertEqual(registry.operation_specs["extract_knowledge"]["role"], "producer")
        for expected_role in {"producer", "validator", "consumer", "governor"}:
            self.assertIn(expected_role, registry.role_specs)
        self.assertEqual(registry.write_mode_for_role("consumer"), "read_only")
        self.assertEqual(registry.write_mode_for_role("governor"), "proposal_only")
        self.assertIn("retrieve_context", registry.operations_for_role("consumer"))
        self.assertEqual(write_mode_for("propose_update"), "proposal_only")
        self.assertEqual(get_role("consumer")["write_mode"], "read_only")
        self.assertTrue(list_operation_roles())
        self.assertIn("evidence_coverage", registry.quality_metric_specs)
        self.assertTrue(registry.semantic_terms())
        self.assertTrue(registry.narrative_chains("l3_brand"))
        self.assertIn("focus", registry.extraction_rules("l2_industry"))
        self.assertTrue(registry.layer_dimensions("l2_industry"))
        self.assertIn("opportunity", registry.entity_types("l2_industry"))
        self.assertIn("brand_claim", registry.entity_types("l3_brand"))
        self.assertIn("responds_to", registry.relation_types("l3_brand"))
        self.assertTrue(list_profiles())
        self.assertTrue(list_policies())
        self.assertEqual(registry.retrieval_contract["meta"]["version"], "1.0.0")

    def test_business_ontology_requires_a_profile(self):
        registry = get_l1_registry()
        with self.assertRaises(ValueError):
            registry.entity_types()
        with self.assertRaises(ValueError):
            registry.relation_types()

    def test_l3_metrics_have_no_l2_dependency(self):
        metrics = get_l1_registry().profile("l3_brand").metric_specs
        self.assertNotIn("technical_barrier", metrics)
        self.assertNotIn("differentiation_degree", metrics)
        self.assertTrue(all(not spec.get("external_layer_dependencies") for spec in metrics.values()))

    def test_context_package_has_stable_shape(self):
        package = build_context_package("产品适用场景", scope={"industry_id": "crm"})
        self.assertEqual(validate_context_package(package), [])
        self.assertEqual(package["scope"]["industry_id"], "crm")

    def test_layer_dimensions_fully_cover_the_ontology(self):
        # layer_dimensions is now derived from each profile ontology's ontology_group,
        # so it must partition every entity/relation/metric with no gaps.
        registry = get_l1_registry()
        for profile_id in ("l2_industry", "l3_brand"):
            profile = registry.profile(profile_id)
            dimensions = registry.layer_dimensions(profile_id)
            self.assertTrue(dimensions)
            entities = {e for d in dimensions for e in d["entity_types"]}
            relations = {r for d in dimensions for r in d["relation_types"]}
            metrics = {m for d in dimensions for m in d["metrics"]}
            self.assertEqual(entities, set(profile.entity_specs), profile_id)
            self.assertEqual(relations, set(profile.relation_specs), profile_id)
            self.assertEqual(metrics, set(profile.metric_specs), profile_id)

    def test_narrative_chain_paths_only_reference_valid_entities(self):
        registry = get_l1_registry()
        for chain in registry.narrative_chains():
            profile_id = chain.get("layer")
            entities = registry.entity_types(profile_id)
            for node in chain.get("path") or []:
                self.assertIn(node, entities, f"{chain.get('chain_id')}: {node}")

    def test_change_proposal_never_bypasses_evidence(self):
        errors = validate_change_proposal({
            "proposal_id": "p1",
            "proposal_type": "modify_policy",
            "status": "published",
        })
        self.assertIn("evidence is required", errors)
        self.assertIn("rollback_plan", " ".join(errors))


if __name__ == "__main__":
    unittest.main()
