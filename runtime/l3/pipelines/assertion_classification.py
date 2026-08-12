"""L3 pipeline: Assertion Classification.

Per brand_knowledge/pipelines/assertion_classification.yaml, this classifies each
candidate assertion along two dimensions:

  - ``statement_class``: fact / claim / observation / inference,
  - ``assertion_kind``: the L3 business kind
    (identity_fact, product_spec, self_claim, attributed_claim, third_party_fact,
     internal_fact, draft_claim, inference).

The classification core is *independent verifiability + source stake*, not
whether the source is "official". A small LLM prompt is used to pick the
``assertion_kind`` (and can refine ``statement_class``); the decision plus a
reason are recorded.

Because the L3 ``assertion`` table is append+supersedes (``trg_assertion_no_update``
raises on UPDATE), in-place refinement is done through a session-scoped trigger
bypass (:func:`runtime.l3.pipelines._helpers.update_assertion`). ``inference``
assertions are flagged for review (``requires_review`` via ``scope``).
"""
from __future__ import annotations

import json
from typing import Any

from runtime.db import DB
from runtime.extract import load_llm, extract_json
from runtime.l3.pipelines._helpers import resolve_brand_context, update_assertion

VALID_KINDS = {
    "identity_fact", "product_spec", "self_claim", "attributed_claim",
    "third_party_fact", "internal_fact", "draft_claim", "inference",
}
VALID_CLASSES = {"fact", "claim", "observation", "inference"}

CLASSIFY_SYSTEM = """\
你是品牌知识库的断言分类器。根据陈述文本与来源类型，判定两条信息：
1. statement_class：fact（可独立验证的事实）、claim（主体自身的声称）、
   observation（观察）、inference（推断）。
2. assertion_kind：identity_fact（官方品牌名/域名/产品名）、product_spec（产品规格）、
   self_claim（品牌自我声称）、attributed_claim（第三方/客户陈述）、
   third_party_fact（第三方可验证事实）、internal_fact（内部事实）、
   draft_claim（草稿/未发布主张）、inference（模型推断）。
输出必须是 JSON 对象：{"statement_class": "...", "assertion_kind": "...", "reason": "..."}
只从上述枚举中取值。
"""


def _classify(client, text: str, source_type: str) -> dict:
    user = f"来源类型: {source_type}\\n陈述: {text}"
    payload = extract_json(client, CLASSIFY_SYSTEM, user)
    sc = payload.get("statement_class", "inference")
    kind = payload.get("assertion_kind", "internal_fact")
    if sc not in VALID_CLASSES:
        sc = "inference"
    if kind not in VALID_KINDS:
        kind = "internal_fact"
    return {"statement_class": sc, "assertion_kind": kind,
            "reason": payload.get("reason", "")}


def run(db: DB, args) -> dict[str, Any]:
    """Classify statement_class + assertion_kind for candidate assertions."""
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    assertions = db.query(
        "SELECT id, statement_text, statement_class, assertion_kind, scope, "
        "       access_level, publication_status "
        "FROM assertion WHERE tenant_id = %s AND brand_id = %s AND status = 'candidate'",
        (tenant_id, brand_id),
    )

    client = load_llm()
    dry_run = bool(getattr(args, "dry_run", False))
    stats = {"classified": 0, "inference": 0, "skipped": 0}

    for a in assertions:
        try:
            prediction = _classify(client, a["statement_text"],
                                   getattr(args, "source_type", None) or "brand_document")
        except Exception as exc:  # pragma: no cover - LLM failure
            print(f"[assertion_classification] LLM failed for {a['id']}: {exc}")
            stats["skipped"] += 1
            continue

        kind = prediction["assertion_kind"]
        sclass = prediction["statement_class"]
        requires_review = sclass == "inference" or kind == "inference"

        if dry_run:
            stats["classified"] += 1
            if requires_review:
                stats["inference"] += 1
            print(f"[assertion_classification][dry] {a['id']}: "
                  f"{sclass}/{kind} ({prediction['reason'][:40]})")
            continue

        # refine assertion_kind (+ optionally statement_class) and record reason
        update_assertion(
            db, a["id"],
            assertion_kind=kind,
            statement_class=sclass,
            scope=_merge_scope(a["scope"], {
                "classification_reason": prediction["reason"],
                "requires_review": requires_review,
            }),
        )
        if kind in ("internal_fact", "internal_claim"):
            update_assertion(db, a["id"], publication_status="draft",
                             access_level="internal")
        stats["classified"] += 1
        if requires_review:
            stats["inference"] += 1

    print(f"[assertion_classification] {json.dumps(stats, ensure_ascii=False)}")
    return {**ctx, "pipeline": "assertion_classification", "dry_run": dry_run,
            "stats": stats, "asset_count": len(assertions)}


def _merge_scope(scope, updates: dict) -> str:
    base = scope or {}
    merged = dict(base)
    merged.update(updates)
    return json.dumps(merged, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 assertion classification pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--source-type", help="Source type for classification context")
    parser.add_argument("--dry-run", action="store_true", help="Run LLM but do not write")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))