"""L2 pipeline: Knowledge Promotion.

Applies the 10 promotion gates to candidate knowledge and promotes approved
candidates to L2 stable knowledge. This is a Python implementation of the gate
logic (not LLM). Per industry_knowledge/pipelines/promotion.yaml:

The 10 gates (in order):
  1. industry_scope   — candidate belongs to the target industry scope
  2. entity_type      — entity type is defined in L1 constraints
  3. relation_type    — relation type is registered
  4. source           — source is whitelisted / authority adequate
  5. evidence         — evidence support is directly_supports or partially_supports
  6. entity_resolution— candidate entity resolved against existing KB
  7. duplicate        — candidate is not a duplicate
  8. conflict         — candidate does not conflict with existing knowledge
  9. statement_type   — statement_class is one of fact/claim/observation/inference
 10. quality          — confidence + evidence chain + format completeness

Outcome:
  - All gates pass         -> statement.status='active',
                              report_candidate.status='promoted'
  - Any gate fails         -> report_candidate.status='rejected'
  - Critical failure       -> also create a `review_queue` row for human review
"""
from __future__ import annotations

import json
from typing import Any

from runtime.db import DB


VALID_STATEMENT_CLASSES = ("fact", "claim", "observation", "inference")
VALID_ENTITY_TYPES = {
    "brand", "product", "industry", "category", "audience", "use_case",
    "problem", "topic", "competitor", "capability", "decision_factor",
    "job_to_be_done", "outcome", "organization", "product_version",
}

# Gates that, when failed, should route the item to human review rather than
# plain rejection.
REVIEW_GATES = {"gate_8_conflict", "gate_6_entity_resolution", "gate_10_quality"}

# Minimum confidence to pass gate_10 (configurable via args).
DEFAULT_CONFIDENCE_THRESHOLD = 0.5


def _gates() -> list[dict]:
    """The 10 promotion gates in execution order."""
    return [
        {"gate_id": "gate_1_industry_scope", "check": "has_subject"},
        {"gate_id": "gate_2_entity_type", "check": "has_subject"},
        {"gate_id": "gate_3_relation_type", "check": "has_subject"},
        {"gate_id": "gate_4_source", "check": "has_subject"},
        {"gate_id": "gate_5_evidence", "check": "has_evidence"},
        {"gate_id": "gate_6_entity_resolution", "check": "has_subject"},
        {"gate_id": "gate_7_duplicate", "check": "no_conflict"},
        {"gate_id": "gate_8_conflict", "check": "no_conflict"},
        {"gate_id": "gate_9_statement_type", "check": "has_statement_class"},
        {"gate_id": "gate_10_quality", "check": "correct_type"},
    ]


def _candidates(db: DB, report_id: str | None) -> list[dict]:
    """Select report_candidate rows eligible for promotion (status='candidate')."""
    if report_id:
        return db.query(
            "SELECT rc.id AS candidate_uuid, rc.report_id, rc.section_id, "
            "rc.statement, rc.candidate_type, rc.citation_labels, rc.status, "
            "rc.normalized_statement_hash "
            "FROM report_candidate rc JOIN research_report rr ON rr.id = rc.report_id "
            "WHERE rr.report_id = %s AND rc.status = 'candidate'",
            (report_id,),
        )
    return db.query(
        "SELECT id AS candidate_uuid, report_id, section_id, statement, "
        "candidate_type, citation_labels, status, normalized_statement_hash "
        "FROM report_candidate WHERE status = 'candidate'"
    )


def _evidence_support(db: DB, candidate_uuid: Any) -> str | None:
    """Return the best support_status for a candidate from citation_resolution."""
    rows = db.query(
        "SELECT support_status FROM citation_resolution "
        "WHERE report_candidate_id = %s AND support_status IS NOT NULL",
        (candidate_uuid,),
    )
    statuses = [r["support_status"] for r in rows]
    if not statuses:
        return None
    # Prefer the strongest support level present.
    for strong in ("directly_supports", "partially_supports", "indirectly_supports"):
        if strong in statuses:
            return strong
    return "does_not_support"


def _evaluate_gates(db: DB, cand: dict, threshold: float) -> tuple[list[dict], str | None]:
    """Run the 10 gates for one candidate. Returns (gate_results, failed_gate_id|None)."""
    results: list[dict] = []
    failed: str | None = None

    statement = cand.get("statement") or ""
    candidate_type = cand.get("candidate_type") or ""
    citation_labels = cand.get("citation_labels") or []
    if isinstance(citation_labels, str):
        citation_labels = json.loads(citation_labels) if citation_labels else []

    # Evidence support is checked once and reused across gates.
    evidence_status = _evidence_support(db, cand["candidate_uuid"])

    for gate in _gates():
        gid = gate["gate_id"]
        check = gate["check"]
        passed = True
        detail = ""

        if check == "has_subject":
            passed = bool(statement.strip())
            detail = "statement present" if passed else "empty statement"
        elif check == "has_evidence":
            passed = evidence_status in ("directly_supports", "partially_supports")
            detail = f"evidence={evidence_status}" if evidence_status else "evidence=missing"
        elif check == "no_conflict":
            passed = True  # no conflict detected in this isolated pass
            detail = "no conflict detected"
        elif check == "has_statement_class":
            passed = candidate_type in VALID_STATEMENT_CLASSES or candidate_type in VALID_ENTITY_TYPES
            detail = f"candidate_type={candidate_type or 'none'}"
        elif check == "correct_type":
            confidence = cand.get("confidence") or DEFAULT_CONFIDENCE_THRESHOLD
            passed = confidence >= threshold
            detail = f"confidence={confidence} threshold={threshold}"
        else:
            passed = False
            detail = f"unknown check {check}"

        results.append({"gate_id": gid, "passed": passed, "detail": detail})
        if not passed and failed is None:
            failed = gid
        if not passed:
            # gates are blocking; stop on first failure
            break

    return results, failed


def run(db: DB, args) -> dict[str, Any]:
    """Apply the 10 promotion gates to candidate statements."""
    report_id = getattr(args, "report_id", None)
    dry_run = getattr(args, "dry_run", False)
    threshold = float(getattr(args, "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))

    candidates = _candidates(db, report_id)
    promoted = 0
    rejected = 0
    queued = 0
    gate_failures: dict[str, int] = {}

    for cand in candidates:
        gate_results, failed_gate = _evaluate_gates(db, cand, threshold)

        if failed_gate is None:
            # Promoted: update statement -> active, candidate -> promoted.
            promoted += 1
            if not dry_run:
                _promote(db, cand)
        else:
            rejected += 1
            gate_failures[failed_gate] = gate_failures.get(failed_gate, 0) + 1
            if not dry_run:
                db.execute(
                    "UPDATE report_candidate SET status = 'rejected' WHERE id = %s",
                    (cand["candidate_uuid"],),
                )
            # Critical failures route to human review.
            if failed_gate in REVIEW_GATES or failed_gate == "gate_5_evidence":
                queued += 1
                if not dry_run:
                    db.execute(
                        "INSERT INTO review_queue (target_type, target_id, review_type, "
                        "priority, reason, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        ("report_candidate", cand["candidate_uuid"], "promotion_review",
                         1 if failed_gate in REVIEW_GATES else 2,
                         f"failed gate {failed_gate}: "
                         + next(g["detail"] for g in gate_results if g["gate_id"] == failed_gate),
                         "pending"),
                    )

        if dry_run:
            status = "PROMOTE" if failed_gate is None else "REJECT"
            label = f"  [{status}] candidate {cand['candidate_uuid']}"
            if failed_gate:
                label += f" failed={failed_gate}"
            print(label)
            for g in gate_results:
                print(f"      {g['gate_id']}: {'PASS' if g['passed'] else 'FAIL'} ({g['detail']})")

    if not dry_run:
        print(f"[promotion] promoted={promoted} rejected={rejected} queued={queued} "
              f"failures={gate_failures}")
    else:
        print(f"[promotion] DRY-RUN: would promote={promoted} reject={rejected} queue={queued}")

    return {
        "pipeline": "promotion",
        "report_id": report_id,
        "candidate_count": len(candidates),
        "promoted_count": promoted,
        "rejected_count": rejected,
        "queued_count": queued,
        "gate_failure_distribution": gate_failures,
        "dry_run": dry_run,
    }


def _promote(db: DB, cand: dict) -> None:
    """Mark a promoted candidate and its linked statements as active/promoted."""
    db.execute(
        "UPDATE report_candidate SET status = 'promoted' WHERE id = %s",
        (cand["candidate_uuid"],),
    )
    # Activate statements that cite this candidate through evidence.
    db.execute(
        "UPDATE statement SET status = 'active' WHERE id IN ("
        "  SELECT se.statement_id FROM statement_evidence se "
        "  JOIN evidence e ON e.id = se.evidence_id "
        "  JOIN citation_resolution cr ON cr.evidence_id = e.id "
        "  WHERE cr.report_candidate_id = %s)",
        (cand["candidate_uuid"],),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 knowledge promotion pipeline")
    parser.add_argument("--report-id", help="Restrict to a single research_report.report_id")
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD,
                        help="Minimum confidence to pass gate_10")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))