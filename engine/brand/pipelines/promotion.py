"""L3 pipeline: promotion — L1 门禁晋级到 active graph（方案 §10.2 / §11.2）。

合并原 review_promotion 与 evidence_verification 职责：读取 ``gate_candidate_knowledge``
中 gate_status=pending 的门禁知识，按 L1 promotion policy 逐条 evaluate → promote/review/reject
（规则源改为 L1，修复旧 evidence_verification 字符串包含/深模型重复定义缺陷）。

L3 额外（§10.2）对每条晋级知识记录敏感/公开风险标记：
- sensitive_warning_status：命中敏感提醒（sensitive_content_warning）即标记
- public_quote_risk：evidence 引言含高风险内容（绝对化宣称/财务/认证）标记
- user_notice_required：需要人工复核/对外发布前提示

这些字段写入晋级后的 active graph 行的 scope JSONB 与 gate_candidate_knowledge。
"""
from __future__ import annotations

from typing import Any

from engine.core.db import DB
from engine.brand.pipelines._helpers import resolve_brand_context
from engine.core.knowledge_service import pending_gate_candidates
from engine.common.policy_engine import load_promotion_policy
from engine.promotion.promotion_service import (
    evaluate_instance,
    disposition,
    promote,
    queue_review,
    stable_short,
)

# §10.2 高风险标记（用于 public_quote_risk / user_notice_required）
_HIGH_RISK_MARKERS = [
    "唯一", "首个", "第一", "领先", "最全", "最准", "最好", "最佳",
    "ROI", "投资回报", "节省", "提升", "百分比", "%", "认证", "资质",
    "ISO", "等保", "SLA", "响应", "竞品", "对比", "第一名",
]


def _risk_flags(k: dict) -> dict[str, bool]:
    """Derive §10.2 risk flags from the candidate's text + scope + warnings."""
    stmt = k.get("statement_text") or ""
    quote = (k.get("evidence_refs") or [{}])[0].get("quote") if k.get("evidence_refs") else ""
    scope = k.get("scope") or {}
    risky_text = (stmt or "") + (quote or "")
    high = any(m in risky_text for m in _HIGH_RISK_MARKERS)
    warnings = scope.get("sensitive_warnings") or []
    return {
        "sensitive_warning_status": "flagged" if (warnings or high) else "clean",
        "public_quote_risk": 1 if (high or bool(warnings)) else 0,
        "user_notice_required": 1 if high else 0,
    }


def run(db: DB, args) -> dict[str, Any]:
    from engine.common.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or "l3_brand"
    get_common_registry().require_profile(profile_id)
    ctx = resolve_brand_context(db, args)
    tenant_id = ctx["tenant_id"]
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
        # §10.2 风险标记
        risk = _risk_flags(k)
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
                # 记录 §10.2 风险标记到晋级后的 active 行 scope（含证据、公开风险）
                _record_risk(db, k, risk, tenant_id)
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
        "brand_id": ctx["brand_id"],
        "tenant_id": tenant_id,
        "pending": len(pending),
        "promoted": promoted,
        "review": review,
        "rejected": rejected,
        "dry_run": dry_run,
    }


def _record_risk(db: DB, k: dict, risk: dict, tenant_id: Any | None) -> None:
    """Annotate the gated candidate + promoted active rows with §10.2 risk flags."""
    # 1) gate_candidate_knowledge 行记录
    db.execute(
        "UPDATE gate_candidate_knowledge SET scope = COALESCE(scope, '{}'::jsonb) || %s::jsonb "
        "WHERE knowledge_id = %s",
        (db._json({
            "sensitive_warning_status": risk["sensitive_warning_status"],
            "public_quote_risk": risk["public_quote_risk"],
            "user_notice_required": risk["user_notice_required"],
        }), k["knowledge_id"]),
    )
    # 2) 晋级后的 active statement（若 subject 落地的行带 scope JSONB）
    statement_id = f"stmt_{stable_short(k.get('statement_text') or '')}"
    db.execute(
        "UPDATE statement SET scope = COALESCE(scope, '{}'::jsonb) || %s::jsonb "
        "WHERE statement_id = %s AND status = 'active'",
        (db._json({
            "sensitive_warning_status": risk["sensitive_warning_status"],
            "public_quote_risk": risk["public_quote_risk"],
            "user_notice_required": risk["user_notice_required"],
        }), statement_id),
    )


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 L1-gated promotion to active graph")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--profile-id", default="l3_brand")
    parser.add_argument("--confidence-threshold", type=float)
    parser.add_argument("--knowledge-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))