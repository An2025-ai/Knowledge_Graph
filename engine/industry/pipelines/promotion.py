"""L2 pipeline: promotion — L1 门禁晋级（方案 §10.1 / §11.1）。

读取 ``gate_candidate_knowledge`` 中 gate_status=pending 的门禁知识，按 L1 promotion policy
逐条 evaluate → promote/review/reject：
- gate_schema：知识 shape 完整（subject/predicate/object 等必需字段）
- gate_ontology：实体/关系类型必须属于 L1 本体，且 domain/range 合法
- gate_evidence：evidence_refs 非空且 access/support 达标
- gate_duplicate：与 active graph 接近重复则不重复写入
- gate_conflict：与既有断言冲突 → 入 review_queue 阻塞
- gate_confidence：confidence ≥ policy.confidence_threshold
命中则写 active graph（relation/statement/metric/event + evidence），否则入 review_queue。
L2 不做来源质量门禁（§10.1：输入已在抽取阶段前置过滤）。

复用 ``engine.promotion.promotion_service.evaluate_instance / promote / queue_review``。
"""
from __future__ import annotations

from typing import Any

from engine.core.db import DB
from engine.core.knowledge_service import pending_gate_candidates
from engine.common.policy_engine import load_promotion_policy
from engine.promotion.promotion_service import (
    evaluate_instance,
    disposition,
    promote,
    queue_review,
)


def run(db: DB, args) -> dict[str, Any]:
    from engine.common.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or "l2_industry"
    get_common_registry().require_profile(profile_id)
    tenant_id = getattr(args, "tenant_id", None)
    threshold = getattr(args, "confidence_threshold", None) or 0.5
    policy = load_promotion_policy(profile_id, float(threshold))

    pending = pending_gate_candidates(db, profile_id=profile_id)
    dry_run = bool(getattr(args, "dry_run", False))

    promoted = review = rejected = 0
    for k in pending:
        if getattr(args, "knowledge_id", None) and k["knowledge_id"] != args.knowledge_id:
            continue
        results = evaluate_instance(db, k, profile_id=profile_id, policy=policy)
        decision, decisive = disposition(results)
        reason = decisive["detail"] if decisive else ""
        if dry_run:
            if decision == "promote":
                promoted += 1
            elif decision == "review":
                review += 1
            else:
                rejected += 1
            continue
        if decision == "promote":
            try:
                promote(db, k, profile_id=profile_id, tenant_id=tenant_id)
                promoted += 1
            except Exception as exc:  # noqa: BLE001 - surface without killing run
                print(f"[promotion] promote failed {k['knowledge_id']}: {exc}")
                review += 1
        elif decision == "review":
            queue_review(db, k, reason)
            review += 1
        else:
            rejected += 1

    print(f"[promotion] {len(pending)} pending → promoted={promoted} review={review} "
          f"rejected={rejected}")
    return {
        "pipeline": "promotion",
        "profile_id": profile_id,
        "pending": len(pending),
        "promoted": promoted,
        "review": review,
        "rejected": rejected,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 L1-gated promotion to active graph")
    parser.add_argument("--profile-id", default="l2_industry")
    parser.add_argument("--tenant-id")
    parser.add_argument("--confidence-threshold", type=float)
    parser.add_argument("--knowledge-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))