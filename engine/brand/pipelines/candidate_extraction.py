"""L3 pipeline: candidate_extraction — L1-aware 候选知识抽取（方案 §11.2）。

合并原 candidate_pre_extraction / candidate_extraction / assertion_classification 的
抽取职责为一次 L1-aware（profile=l3_brand）抽取：读取文档 evidence_units，
NER + 正则/规则预筛 → L1 映射过滤 →（可选）LLM 结构化抽取，写入 ``knowledge_candidates``
（§9.2），保留 evidence_text 与完整溯源。过滤与 L1 品牌本体无关的 unit（§6.3.1）。

注意：L3 不做标题断言分类——断言级别由 L1 门禁在 promotion 阶段统一裁决（§10.2）。
"""
from __future__ import annotations

from typing import Any

from engine.core.db import DB
from engine.extraction.candidate_extraction import pre_extract, build_candidate_rows
from engine.core.knowledge_service import (
    document_provenance,
    upsert_knowledge_candidate,
)


DEFAULT_PROFILE_ID = "l3_brand"
DEFAULT_UNIT_LIMIT = 200


def _resolve_document_uuid(db: DB, args) -> Any:
    document_uuid = getattr(args, "document_uuid", None)
    if document_uuid:
        return document_uuid
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("candidate_extraction requires --document-uuid or a known --document-id")
    return rows[0]["id"]


def run(db: DB, args) -> dict[str, Any]:
    from engine.common.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or DEFAULT_PROFILE_ID
    get_common_registry().require_profile(profile_id)
    layer = getattr(args, "layer", None) or "l3_brand"

    document_uuid = _resolve_document_uuid(db, args)
    document_id = getattr(args, "document_id", None)
    prov = document_provenance(db, document_uuid)

    ner_client = None
    ner_enabled = not getattr(args, "skip_ner", False)
    if ner_enabled:
        try:
            from engine.clients.ner_client import get_ner_client

            ner_client = get_ner_client()
        except Exception as exc:  # noqa: BLE001 - optional layer
            print(f"[candidate_extraction] NER disabled: {exc}")

    units = db.query(
        "SELECT unit_id, source_span_ids, text, heading_path, token_count "
        "FROM evidence_units WHERE document_id=%s ORDER BY unit_id "
        "LIMIT %s",
        (document_uuid, getattr(args, "unit_limit", DEFAULT_UNIT_LIMIT)),
    )
    if not units:
        print(f"[candidate_extraction] no evidence units for {document_id or document_uuid}")
        return {"pipeline": "candidate_extraction", "candidate_count": 0,
                "unit_count": 0, "document_uuid": str(document_uuid)}

    context = {
        "document_uuid": document_uuid,
        "document_id": document_id or str(document_uuid),
        "profile_id": profile_id,
        "layer": layer,
        "published_at": prov.get("published_at"),
        "original_url": prov.get("original_url"),
        "content_hash": prov.get("content_hash"),
    }

    total = 0
    ner_count = 0
    for unit in units:
        text = unit.get("text", "")
        cands = pre_extract(text, ner_client=ner_client, profile_id=profile_id)
        if not cands:
            continue
        per_unit = {
            "unit_id": unit["unit_id"],
            "source_span_ids": unit.get("source_span_ids", []),
            "text": text,
        }
        rows = build_candidate_rows(context, per_unit, cands)
        for r in rows:
            if any("paddlenlp:ner" in m for m in r["extraction_method"]):
                ner_count += 1
            if getattr(args, "dry_run", False):
                total += 1
                continue
            upsert_knowledge_candidate(db, r)
            total += 1

    print(f"[candidate_extraction] {total} candidates from {len(units)} units (ner={ner_count})")
    return {
        "pipeline": "candidate_extraction",
        "profile_id": profile_id,
        "document_uuid": str(document_uuid),
        "document_id": document_id,
        "unit_count": len(units),
        "candidate_count": total,
        "ner_count": ner_count,
        "ner_enabled": ner_client is not None,
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 L1-aware candidate extraction")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--uuid", dest="document_uuid")
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--layer", default="l3_brand")
    parser.add_argument("--unit-limit", type=int, default=DEFAULT_UNIT_LIMIT)
    parser.add_argument("--skip-ner", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))