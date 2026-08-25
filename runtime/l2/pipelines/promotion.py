"""L2 pipeline: governed promotion from report candidates to active knowledge."""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any

from runtime.db import DB
from runtime.l1.policy_engine import PromotionPolicy, load_promotion_policy
from runtime.l1.registry import get_l1_registry


DEFAULT_CONFIDENCE_THRESHOLD = 0.5
DEFAULT_PROFILE_ID = "l2_industry"

# Default dedup thresholds, used only when a profile's promotion_policy does
# not define them. The authoritative values come from PromotionPolicy (L1 policy_engine).
NEAR_DUPLICATE_THRESHOLD = 0.85
# Semantic (embedding) near-duplicate threshold for gate_7 semantic dedup stage.
SEMANTIC_NEAR_DUPLICATE_THRESHOLD = 0.92


def _valid_statement_classes(profile_id: str = DEFAULT_PROFILE_ID) -> tuple[str, ...]:
    """Authoritative statement classes from L1 ontology (profile.statement_classes).

    Falls back to the four classic kinds when a profile does not constrain them.
    """
    classes = get_l1_registry().statement_classes(profile_id)
    return tuple(classes) if classes else ("fact", "claim", "observation", "inference")


def _candidates(db: DB, report_id: str | None) -> list[dict]:
    select = (
        "SELECT rc.id AS candidate_uuid, rc.report_id, rc.section_id, rc.statement, "
        "rc.candidate_type, rc.citation_labels, rc.status, "
        "rc.normalized_statement_hash, rc.knowledge_candidate_type, rc.confidence, ir.industry_id, "
        "ir.source_requirements "
        "FROM report_candidate rc "
        "JOIN research_report rr ON rr.id = rc.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id = rr.requirement_id "
    )
    if report_id:
        return db.query(
            select + "WHERE rr.report_id = %s AND rc.status = 'candidate'",
            (report_id,),
        )
    return db.query(select + "WHERE rc.status = 'candidate'")


def _candidate_entities(db: DB, candidate_uuid: Any) -> list[dict]:
    return db.query(
        "SELECT e.id, e.entity_type, e.industry_id, et.type_code AS registered_type "
        "FROM entity e LEFT JOIN entity_type et "
        "ON et.type_code=e.entity_type AND et.status='active' "
        "WHERE COALESCE(e.attributes->'report_candidate_ids', '[]'::jsonb) "
        "@> to_jsonb(%s::text)",
        (str(candidate_uuid),),
    )


def _candidate_relations(db: DB, candidate_uuid: Any) -> list[dict]:
    return db.query(
        "SELECT r.id, r.relation_type, r.subject_id, r.object_id, r.scope, "
        "rt.relation_code AS registered_type, rt.subject_types, rt.object_types, "
        "rt.cardinality, "
        "se.entity_type AS subject_type, oe.entity_type AS object_type "
        "FROM relation r "
        "LEFT JOIN relation_type rt ON rt.relation_code=r.relation_type AND rt.status='active' "
        "LEFT JOIN entity se ON se.id=r.subject_id "
        "LEFT JOIN entity oe ON oe.id=r.object_id "
        "WHERE r.scope->>'report_candidate_id' = %s",
        (str(candidate_uuid),),
    )


def _candidate_statements(db: DB, candidate_uuid: Any) -> list[dict]:
    return db.query(
        "SELECT id, statement_text, statement_class, subject_entity_id, predicate, "
        "object_entity_id, object_value, scope FROM statement "
        "WHERE scope->>'report_candidate_id' = %s",
        (str(candidate_uuid),),
    )


def _evidence_rows(db: DB, candidate_uuid: Any) -> list[dict]:
    return db.query(
        "SELECT cr.evidence_id, cr.support_status, cr.access_status, "
        "si.id AS source_uuid, si.source_class, si.source_type, si.approval_status, "
        "si.l2_enabled, sp.authority_level, sp.status AS policy_status "
        "FROM citation_resolution cr "
        "LEFT JOIN source_instance si ON si.id=cr.source_id "
        "LEFT JOIN source_policy sp ON sp.source_type=si.source_type "
        "WHERE cr.report_candidate_id=%s",
        (candidate_uuid,),
    )


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _allowed_source_classes(candidate: dict) -> set[str]:
    requirements = candidate.get("source_requirements") or {}
    if isinstance(requirements, str):
        requirements = json.loads(requirements)
    return set(requirements.get("allowed_source_classes") or [])


def _exact_duplicate(db: DB, candidate: dict) -> dict | None:
    rows = db.query(
        "SELECT other.id FROM report_candidate other "
        "JOIN research_report rr ON rr.id=other.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id=rr.requirement_id "
        "WHERE other.id <> %s AND other.normalized_statement_hash=%s "
        "AND other.status='promoted' AND ir.industry_id=%s LIMIT 1",
        (candidate["candidate_uuid"], candidate.get("normalized_statement_hash"),
         candidate.get("industry_id")),
    )
    return rows[0] if rows else None


def _near_duplicate(
    db: DB,
    candidate: dict,
    near_threshold: float = NEAR_DUPLICATE_THRESHOLD,
    semantic_threshold: float = SEMANTIC_NEAR_DUPLICATE_THRESHOLD,
) -> dict | None:
    rows = db.query(
        "SELECT other.id, other.statement FROM report_candidate other "
        "JOIN research_report rr ON rr.id=other.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id=rr.requirement_id "
        "WHERE other.id <> %s AND other.status='promoted' AND ir.industry_id=%s "
        "ORDER BY other.updated_at DESC LIMIT 500",
        (candidate["candidate_uuid"], candidate.get("industry_id")),
    )
    normalized = " ".join((candidate.get("statement") or "").casefold().split())
    # Character-level near-duplicate check (existing).
    for row in rows:
        other = " ".join((row.get("statement") or "").casefold().split())
        if normalized and other and SequenceMatcher(None, normalized, other).ratio() >= near_threshold:
            return row
    # Semantic near-duplicate check (pgvector/embedding): catches same-meaning
    # statements phrased differently that character similarity misses.
    cand_vec = _embed_statement(candidate.get("statement") or "")
    if cand_vec is None:
        return None
    for row in rows:
        other_text = row.get("statement") or ""
        if not other_text:
            continue
        other_vec = _embed_statement(other_text)
        if other_vec is None:
            continue
        if _cosine(cand_vec, other_vec) >= semantic_threshold:
            return row
    return None


_SEMANTIC_NN_CACHE: dict[str, list[float]] = {}


def _embed_statement(text: str) -> list[float] | None:
    """Embed statement text (cached per text) for semantic dedup; None if unavailable."""
    if not text:
        return None
    if text in _SEMANTIC_NN_CACHE:
        return _SEMANTIC_NN_CACHE[text]
    try:
        from runtime.embeddings import get_embedding_client

        vec = get_embedding_client().embed_one(text)
        _SEMANTIC_NN_CACHE[text] = vec
        return vec
    except Exception:  # noqa: BLE001 - optional vector layer
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    try:
        import numpy as np

        va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))
    except Exception:
        return 0.0


def _relation_conflict(db: DB, relations: list[dict]) -> dict | None:
    for relation in relations:
        if relation.get("cardinality") not in ("one-to-one", "many-to-one"):
            continue
        rows = db.query(
            "SELECT id, object_id FROM relation WHERE status='active' "
            "AND subject_id=%s AND relation_type=%s AND object_id<>%s LIMIT 1",
            (relation["subject_id"], relation["relation_type"], relation["object_id"]),
        )
        if rows:
            return rows[0]
    return None


def _result(gate_id: str, passed: bool, detail: str, action: str = "pass") -> dict:
    return {"gate_id": gate_id, "passed": passed, "detail": detail, "action": action}


def _evaluate_gates(
    db: DB, cand: dict, threshold: float, profile_id: str = DEFAULT_PROFILE_ID
) -> tuple[list[dict], str | None]:
    """Evaluate all gates in order and return results plus first failed gate."""
    policy: PromotionPolicy = load_promotion_policy(profile_id, threshold)
    entities = _candidate_entities(db, cand["candidate_uuid"])
    relations = _candidate_relations(db, cand["candidate_uuid"])
    statements = _candidate_statements(db, cand["candidate_uuid"])
    evidence = _evidence_rows(db, cand["candidate_uuid"])
    expected_industry = cand.get("industry_id")
    results: list[dict] = []

    scoped = bool(expected_industry) and all(
        (entity.get("industry_id") in (None, expected_industry)) for entity in entities
    ) and all(
        (relation.get("scope") or {}).get("industry_id") == expected_industry
        for relation in relations
    ) and all(
        (statement.get("scope") or {}).get("industry_id") == expected_industry
        for statement in statements
    )
    results.append(_result("gate_1_industry_scope", scoped,
                           f"industry={expected_industry or 'missing'}"))

    invalid_entities = [e["entity_type"] for e in entities if not e.get("registered_type")]
    results.append(_result(
        "gate_2_entity_type", not invalid_entities and bool(entities or statements),
        "registered entity types" if not invalid_entities else f"unregistered={invalid_entities}",
    ))

    invalid_relations = []
    for rel in relations:
        allowed_subjects = _as_list(rel.get("subject_types"))
        allowed_objects = _as_list(rel.get("object_types"))
        if (not rel.get("registered_type")
                or (allowed_subjects and rel.get("subject_type") not in allowed_subjects)
                or (allowed_objects and rel.get("object_type") not in allowed_objects)):
            invalid_relations.append(rel.get("relation_type"))
    results.append(_result(
        "gate_3_relation_type", not invalid_relations,
        "registered relation constraints" if not invalid_relations else f"invalid={invalid_relations}",
    ))

    allowed_classes = _allowed_source_classes(cand)
    if cand.get("knowledge_candidate_type") == "source_enrichment":
        # First-pass enrichment is constrained to sources already cited by the
        # report. It uses a light source gate here: the source must be resolved
        # into the graph, but it does not require manual l2_enabled approval.
        recognizable_sources = [
            row for row in evidence
            if row.get("source_uuid")
            and row.get("source_type")
            and (not allowed_classes or row.get("source_class") in allowed_classes)
        ]
        source_ok = bool(evidence) and len(recognizable_sources) == len(evidence)
        results.append(_result(
            "gate_4_source", source_ok,
            f"recognizable_sources={len(recognizable_sources)}/{len(evidence)}",
        ))
    else:
        valid_sources = [
            row for row in evidence
            if row.get("source_uuid")
            and row.get("approval_status") == "approved"
            and row.get("l2_enabled") is True
            and row.get("policy_status") == "active"
            and policy.source_authority_ok(row.get("authority_level"))
            and (not allowed_classes or row.get("source_class") in allowed_classes)
        ]
        source_ok = bool(evidence) and len(valid_sources) == len(evidence)
        results.append(_result(
            "gate_4_source", source_ok,
            f"approved_sources={len(valid_sources)}/{len(evidence)}",
        ))

    supported = [
        row for row in evidence
        if row.get("evidence_id")
        and policy.evidence_ok(row.get("access_status"), row.get("support_status"))
    ]
    evidence_ok = bool(evidence) and len(supported) == len(evidence)
    results.append(_result("gate_5_evidence", evidence_ok,
                           f"supported_evidence={len(supported)}/{len(evidence)}"))

    resolved = bool(statements or relations) and all(
        rel.get("subject_id") and rel.get("object_id") for rel in relations
    )
    results.append(_result("gate_6_entity_resolution", resolved,
                           f"entities={len(entities)} relations={len(relations)} statements={len(statements)}"))

    exact = _exact_duplicate(db, cand)
    near = None if exact else _near_duplicate(
        db, cand,
        near_threshold=policy.near_duplicate_threshold,
        semantic_threshold=policy.semantic_near_duplicate_threshold,
    )
    duplicate_ok = exact is None and near is None
    duplicate_action = "reject" if exact else ("review" if near else "pass")
    duplicate_detail = (
        f"exact_duplicate={exact['id']}" if exact
        else f"near_duplicate={near['id']}" if near
        else "no duplicate"
    )
    results.append(_result("gate_7_duplicate", duplicate_ok, duplicate_detail, duplicate_action))

    conflict = _relation_conflict(db, relations)
    results.append(_result(
        "gate_8_conflict", conflict is None,
        "no structural conflict" if not conflict else f"conflicts_with={conflict['id']}",
        "pass" if not conflict else "review",
    ))

    valid_statement_classes = _valid_statement_classes(profile_id)
    statement_classes = {s.get("statement_class") for s in statements}
    type_ok = cand.get("candidate_type") in valid_statement_classes and all(
        value in valid_statement_classes for value in statement_classes
    )
    results.append(_result("gate_9_statement_type", type_ok,
                           f"candidate_type={cand.get('candidate_type')}, statements={sorted(statement_classes)}"))

    confidence = cand.get("confidence")
    quality_ok = confidence is not None and float(confidence) >= threshold
    results.append(_result(
        "gate_10_quality", quality_ok,
        f"confidence={confidence} threshold={threshold}",
        "pass" if quality_ok else "review",
    ))

    failed = next((item["gate_id"] for item in results if not item["passed"]), None)
    return results, failed


def _disposition(results: list[dict]) -> tuple[str, dict | None]:
    failures = [result for result in results if not result["passed"]]
    if not failures:
        return "promote", None
    rejection = next((result for result in failures if result["action"] == "reject"), None)
    if rejection:
        return "reject", rejection
    review = next((result for result in failures if result["action"] == "review"), None)
    return ("review", review) if review else ("reject", failures[0])


def run(db: DB, args) -> dict[str, Any]:
    report_id = getattr(args, "report_id", None)
    dry_run = bool(getattr(args, "dry_run", False))
    profile_id = getattr(args, "profile_id", None) or DEFAULT_PROFILE_ID
    threshold = float(getattr(args, "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))
    # Fail fast on a typo'd/unknown profile: a misspelled --profile-id must not
    # silently make the strict layered whitelist behave like all-types-open.
    get_l1_registry().require_profile(profile_id)
    candidates = _candidates(db, report_id)
    stats = {"promoted": 0, "rejected": 0, "queued": 0}
    gate_failures: dict[str, int] = {}

    for cand in candidates:
        gate_results, _ = _evaluate_gates(db, cand, threshold, profile_id=profile_id)
        disposition, decisive = _disposition(gate_results)
        if decisive:
            gate_failures[decisive["gate_id"]] = gate_failures.get(decisive["gate_id"], 0) + 1

        if disposition == "promote":
            stats["promoted"] += 1
            if not dry_run:
                _promote(db, cand, gate_results)
        elif disposition == "review":
            stats["queued"] += 1
            if not dry_run:
                _queue_review(db, cand, gate_results, decisive)
        else:
            stats["rejected"] += 1
            if not dry_run:
                db.execute(
                    "UPDATE report_candidate SET status='rejected', "
                    "promotion_gate_results=%s, rejection_reason=%s, review_reason=NULL "
                    "WHERE id=%s",
                    (db._json(gate_results), decisive["detail"], cand["candidate_uuid"]),
                )

        if dry_run:
            print(f"  [{disposition.upper()}] candidate {cand['candidate_uuid']}")
            for gate in gate_results:
                print(f"    {gate['gate_id']}: {'PASS' if gate['passed'] else gate['action'].upper()} ({gate['detail']})")

    print(f"[promotion] promoted={stats['promoted']} rejected={stats['rejected']} "
          f"queued={stats['queued']} failures={gate_failures}")
    return {
        "pipeline": "promotion", "report_id": report_id,
        "candidate_count": len(candidates),
        "promoted_count": stats["promoted"], "rejected_count": stats["rejected"],
        "queued_count": stats["queued"], "gate_failure_distribution": gate_failures,
        "dry_run": dry_run,
    }


def _queue_review(db: DB, cand: dict, gate_results: list[dict], decisive: dict) -> None:
    reason = f"{decisive['gate_id']}: {decisive['detail']}"
    db.execute(
        "UPDATE report_candidate SET promotion_gate_results=%s, review_reason=%s, "
        "rejection_reason=NULL WHERE id=%s",
        (db._json(gate_results), reason, cand["candidate_uuid"]),
    )
    db.execute(
        "INSERT INTO review_queue (target_type, target_id, review_type, priority, reason, status) "
        "VALUES ('report_candidate', %s, 'promotion_review', 8, %s, 'pending') "
        "ON CONFLICT (target_type, target_id, review_type) WHERE status='pending' "
        "DO UPDATE SET reason=EXCLUDED.reason, priority=EXCLUDED.priority",
        (cand["candidate_uuid"], reason),
    )


def _promote(db: DB, cand: dict, gate_results: list[dict]) -> None:
    candidate_id = str(cand["candidate_uuid"])
    db.execute(
        "UPDATE report_candidate SET status='promoted', promotion_gate_results=%s, "
        "rejection_reason=NULL, review_reason=NULL WHERE id=%s",
        (db._json(gate_results), cand["candidate_uuid"]),
    )
    db.execute("UPDATE statement SET status='active' WHERE scope->>'report_candidate_id'=%s",
               (candidate_id,))
    db.execute("UPDATE relation SET status='active' WHERE scope->>'report_candidate_id'=%s",
               (candidate_id,))
    db.execute(
        "UPDATE entity SET status='active' WHERE status='candidate' AND "
        "COALESCE(attributes->'report_candidate_ids', '[]'::jsonb) @> to_jsonb(%s::text)",
        (candidate_id,),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 knowledge promotion pipeline")
    parser.add_argument("--report-id")
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    namespace = parser.parse_args()
    with DB.from_env() as database:
        print(json.dumps(run(database, namespace), ensure_ascii=False, indent=2))
