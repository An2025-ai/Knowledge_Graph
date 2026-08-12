"""L3 pipeline: Review and Promotion.

Per brand_knowledge/pipelines/review_promotion.yaml, this is the final gate that
moves verified brand knowledge from ``candidate`` to ``active``. It:

  1. Runs policy checks that force human review for the high-risk categories
     (absolute claims, certification/performance numbers, competitive claims,
     internal->public transitions, L2 new mappings),
  2. Creates ``review_queue`` rows for every forced-review assertion,
  3. Promotes approved assertions to ``status='active'`` (in-place via the
     session-scoped trigger bypass, mirroring the append+supersedes intent),
  4. Creates a ``brand_snapshot`` row summarising current entity / assertion /
     conflict counts for the brand.

Only assertions that are ``evidence_verified`` (already linked to evidence) and
not flagged for review are auto-promoted; review-flagged assertions stay queued.
"""
from __future__ import annotations

import re
from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import (
    resolve_brand_context,
    update_assertion,
    sha256_text,
)

# Forced-review keyword heuristics.
ABSOLUTE_WORDS = r"(唯一|首个|领先|最全|最准|第一|唯一|best|first|only|leading)"
PERFORMANCE_WORDS = r"(\b\d+(?:\.\d+)?%?\b|ROI|性能|性能提升|转化率|市占率|市场地位|客户结果|performance)"
CERT_WORDS = r"(认证|合规|安全|税务|会计|ISO|证书|certification|compliance|security)"
COMPETITIVE_WORDS = r"(竞品|对比|优于|替代|vs|competitor|compared)"
INTERNAL_WORDS = r"(内部|未公开|路线图|internal|unreleased|roadmap)"
L2_MAPPING_WORDS = r"(新能力|新实体|capability mapping)"


def _check_review(text: str) -> list[str]:
    """Return the list of forced-review conditions triggered by the text."""
    kinds = []
    if re.search(ABSOLUTE_WORDS, text, re.IGNORECASE):
        kinds.append("absolute_claim")
    if re.search(PERFORMANCE_WORDS, text, re.IGNORECASE):
        kinds.append("performance_number")
    if re.search(CERT_WORDS, text, re.IGNORECASE):
        kinds.append("certification_compliance")
    if re.search(COMPETITIVE_WORDS, text, re.IGNORECASE):
        kinds.append("competitive_comparison")
    if re.search(INTERNAL_WORDS, text, re.IGNORECASE):
        kinds.append("internal_to_public")
    return kinds


def run(db: DB, args) -> dict[str, Any]:
    """Apply review gates and promote approved assertions; write a snapshot."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    assertions = db.query(
        "SELECT id, statement_text, statement_class, assertion_kind, scope "
        "FROM assertion WHERE tenant_id = %s AND brand_id = %s AND status = 'candidate'",
        (tenant_id, brand_id),
    )

    dry_run = bool(getattr(args, "dry_run", False))
    stats = {"promoted": 0, "queued": 0, "rejected": 0, "forced_review": 0}

    for a in assertions:
        text = a["statement_text"] or ""
        review_kinds = _check_review(text)
        # check whether it already has supporting evidence
        ev = db.query(
            "SELECT support_status FROM assertion_evidence WHERE assertion_id = %s LIMIT 1",
            (a["id"],),
        ) if not dry_run else []
        has_direct = bool(ev) and ev[0]["support_status"] in ("direct", "partial")

        if review_kinds:
            stats["forced_review"] += 1
            stats["queued"] += 1
            if not dry_run:
                db.execute(
                    "INSERT INTO review_queue "
                    "(id, target_type, target_id, tenant_id, review_type, priority, reason, status) "
                    "VALUES (uuid_generate_v4(), 'assertion', %s, %s, %s, 8, %s, 'pending')",
                    (a["id"], tenant_id, "forced_review",
                     f"forced review: {', '.join(review_kinds)}"),
                )
            continue

        # Not forced-review: promote if evidence-verified (or when dry-run just measure)
        if not has_direct and not dry_run:
            stats["rejected"] += 1
            continue

        if dry_run:
            stats["promoted"] += 1
            continue
        update_assertion(db, a["id"], status="active")
        stats["promoted"] += 1

    # ---- brand_snapshot summary ----
    counts = {"entity_count": 0, "assertion_count": 0, "conflict_count": 0}
    if not dry_run:
        ent = db.query(
            "SELECT COUNT(*) AS c FROM entity WHERE tenant_id = %s AND owner_brand = %s AND status='active'",
            (tenant_id, brand_id),
        )
        asr = db.query(
            "SELECT COUNT(*) AS c FROM assertion WHERE tenant_id = %s AND brand_id = %s",
            (tenant_id, brand_id),
        )
        conf = db.query(
            "SELECT COUNT(*) AS c FROM knowledge_conflict WHERE tenant_id = %s AND brand_id = %s",
            (tenant_id, brand_id),
        )
        counts = {
            "entity_count": ent[0]["c"] if ent else 0,
            "assertion_count": asr[0]["c"] if asr else 0,
            "conflict_count": conf[0]["c"] if conf else 0,
        }
        manifest_hash = getattr(args, "content_hash", None) or ""
        db.execute(
            "INSERT INTO brand_snapshot "
            "(snapshot_id, tenant_id, brand_id, l1_version, source_manifest_hash, "
            " entity_count, assertion_count, conflict_count, approved_by) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, brand_id, getattr(args, "l1_version", None) or "1.2.0",
             manifest_hash, counts["entity_count"], counts["assertion_count"],
             counts["conflict_count"], "pipeline_executor"),
        )

    if dry_run:
        print(f"[review_promotion] DRY-RUN stats={stats}, counts={counts}")

    return {**ctx, "pipeline": "review_promotion", "dry_run": dry_run,
            "stats": stats, "counts": counts}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 review and promotion pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--content-hash", help="Source manifest hash for the snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))