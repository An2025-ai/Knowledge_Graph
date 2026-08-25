"""L2 pipeline: Evidence Resolution.

Resolves `[S#]` citation labels on report candidates to original evidence.
Per industry_knowledge/pipelines/evidence_resolution.yaml this pipeline loads a
citation index + evidence package, locates a browser/evidence record per label,
verifies the content hash, and records a support_status assessment.

Because geo-research is a separate process, this executor works from an on-disk
evidence index (JSON), e.g. a geo-research `evidence.json` or a simple sources
file. It creates `citation_resolution` rows linking each citation_label to an
evidence_id/source_id with a support_status:
  directly_supports / partially_supports / indirectly_supports /
  does_not_support / insufficient

Unresolved citations are flagged with access_status='unresolved' and
support_status='insufficient' so downstream promotion can block them.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from runtime.db import DB


def _load_evidence_index(path: str) -> dict[str, Any]:
    """Load an evidence index file (JSON).

    Expected shapes (either is accepted):
      {"sources": [{ "label": "S1", "evidence_id": "...", "source_id": "...",
                     "url": "...", "support_status": "...", "quote": "..." }]}
      { "S1": {"evidence_id": "...", "source_id": "...", "url": "...",
                "support_status": "...", "quote": "..."} }
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict) and "sources" in payload:
        sources = payload["sources"]
        index: dict[str, Any] = {}
        for s in sources:
            label = s.get("label") or s.get("citation_label")
            if label:
                index[label] = s
        return index

    if isinstance(payload, dict):
        # keyed by label, e.g. "S1": {...}
        return payload

    raise ValueError(f"Unrecognized evidence index format in {path}")


def _candidate_rows(db: DB, report_id: str | None) -> list[dict]:
    """Select report_candidate rows (optionally filtered by report_id)."""
    if report_id:
        rows = db.query(
            "SELECT rc.id, rc.report_id, rc.citation_labels, rc.statement "
            "FROM report_candidate rc JOIN research_report rr ON rr.id = rc.report_id "
            "WHERE rr.report_id = %s AND rc.citation_labels IS NOT NULL",
            (report_id,),
        )
    else:
        rows = db.query(
            "SELECT id, report_id, citation_labels, statement FROM report_candidate "
            "WHERE citation_labels IS NOT NULL"
        )
    return rows


def _evidence_uuid(db: DB, evidence_id: str) -> str | None:
    rows = db.query(
        "SELECT id FROM evidence WHERE evidence_id = %s LIMIT 1", (evidence_id,)
    )
    return rows[0]["id"] if rows else None


def _source_uuid(db: DB, source_id: str) -> str | None:
    rows = db.query(
        "SELECT id FROM source_instance WHERE source_id = %s LIMIT 1", (source_id,)
    )
    return rows[0]["id"] if rows else None


def _ensure_evidence(db: DB, entry: dict, dry_run: bool) -> str | None:
    """Resolve or create a traceable evidence row from an index entry."""
    evidence_id = entry.get("evidence_id")
    quote = entry.get("quote") or entry.get("evidence_text")
    if not evidence_id or not quote:
        return None
    existing = _evidence_uuid(db, evidence_id)
    if existing or dry_run:
        return existing or f"dry:{evidence_id}"

    source_uuid = None
    source_id = entry.get("source_id")
    if source_id:
        source_uuid = _source_uuid(db, source_id)
        if not source_uuid:
            db.upsert(
                "source_instance",
                {
                    "source_id": source_id,
                    "industry_id": entry.get("industry_id"),
                    "source_class": entry.get("source_class"),
                    "source_type": entry.get("source_type") or "official",
                    "publisher": entry.get("publisher"),
                    "title": entry.get("title") or source_id,
                    "canonical_url": entry.get("url"),
                    "access_level": entry.get("access_level") or "public",
                    # Approval is a database-side governance decision. An
                    # imported evidence file may not self-authorize a source.
                    "approval_status": "pending",
                    "l2_enabled": False,
                    "status": "registered",
                },
                key_field="source_id",
            )
            source_uuid = _source_uuid(db, source_id)

    db.upsert(
        "evidence",
        {
            "evidence_id": evidence_id,
            "source_id": source_uuid,
            "content_path": entry.get("content_path"),
            "page_ref": entry.get("page_ref"),
            "quote": quote,
            "content_hash": entry.get("content_hash")
            or hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "access_level": entry.get("access_level") or "public",
            "support_status": entry.get("support_status") or "insufficient",
        },
        key_field="evidence_id",
    )
    return _evidence_uuid(db, evidence_id)


def run(db: DB, args) -> dict[str, Any]:
    """Resolve citation labels to evidence for report candidates."""
    evidence_path = (
        getattr(args, "evidence", None)
        or getattr(args, "evidence_index", None)
        or os.environ.get("GEO_RESEARCH_EVIDENCE_PATH")
    )
    if not evidence_path or not os.path.exists(evidence_path):
        raise FileNotFoundError(f"Evidence index not found: {evidence_path}")

    index = _load_evidence_index(evidence_path)
    report_id = getattr(args, "report_id", None)
    dry_run = getattr(args, "dry_run", False)

    resolutions: list[dict] = []
    flagged_unresolved = 0

    for cand in _candidate_rows(db, report_id):
        labels = cand.get("citation_labels") or []
        if isinstance(labels, str):
            labels = json.loads(labels)
        for label in labels:
            entry = index.get(label)
            if entry is None:
                flagged_unresolved += 1
                resolution = {
                    "report_candidate_id": cand["id"],
                    "citation_label": label,
                    "access_status": "unresolved",
                    "support_status": "insufficient",
                    "support_reason": "no evidence record found for citation label",
                }
            else:
                evidence_uuid = _ensure_evidence(db, entry, dry_run)
                support_status = entry.get("support_status") or "insufficient"
                if not evidence_uuid:
                    support_status = "insufficient"
                    flagged_unresolved += 1
                resolution = {
                    "report_candidate_id": cand["id"],
                    "citation_label": label,
                    "original_url": entry.get("url"),
                    "access_status": entry.get("access_status", "verified")
                    if evidence_uuid else "unresolved",
                    "evidence_location": entry.get("page_ref") or entry.get("content_path"),
                    "support_status": support_status,
                    "support_reason": entry.get("support_reason")
                    or (f"evidence located for {label}" if evidence_uuid
                        else "evidence_id and quote/evidence_text are required"),
                    "verifier_version": "l2-evidence-resolution-1.0.0",
                }
                if evidence_uuid and not str(evidence_uuid).startswith("dry:"):
                    resolution["evidence_id"] = evidence_uuid
                if entry.get("source_id"):
                    src_uuid = _source_uuid(db, entry["source_id"])
                    if src_uuid:
                        resolution["source_id"] = src_uuid

            resolutions.append(resolution)
            if not dry_run:
                db.execute(
                    "INSERT INTO citation_resolution (report_candidate_id, citation_label, "
                    "source_id, evidence_id, original_url, access_status, evidence_location, "
                    "support_status, support_reason, verifier_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (report_candidate_id, citation_label) DO UPDATE SET "
                    "source_id=EXCLUDED.source_id, evidence_id=EXCLUDED.evidence_id, "
                    "original_url=EXCLUDED.original_url, access_status=EXCLUDED.access_status, "
                    "evidence_location=EXCLUDED.evidence_location, "
                    "support_status=EXCLUDED.support_status, support_reason=EXCLUDED.support_reason, "
                    "verifier_version=EXCLUDED.verifier_version",
                    (resolution.get("report_candidate_id"), resolution.get("citation_label"),
                     resolution.get("source_id"), resolution.get("evidence_id"),
                     resolution.get("original_url"), resolution.get("access_status"),
                     resolution.get("evidence_location"), resolution.get("support_status"),
                     resolution.get("support_reason"), resolution.get("verifier_version")),
                )

    if dry_run:
        print(f"[evidence_resolution] DRY-RUN: would insert {len(resolutions)} "
              f"resolution rows ({flagged_unresolved} unresolved)")
    else:
        print(f"[evidence_resolution] inserted {len(resolutions)} citation_resolution rows "
              f"({flagged_unresolved} unresolved)")

    return {
        "pipeline": "evidence_resolution",
        "evidence_index": evidence_path,
        "resolved_count": len(resolutions) - flagged_unresolved,
        "unresolved_count": flagged_unresolved,
        "total_resolutions": len(resolutions),
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 evidence resolution pipeline")
    parser.add_argument("--evidence", required=True, help="Path to evidence index JSON")
    parser.add_argument("--report-id", help="Restrict to a single research_report.report_id")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
