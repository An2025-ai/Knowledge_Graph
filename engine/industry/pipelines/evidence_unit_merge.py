"""L2 pipeline: evidence_unit_merge — span → evidence_unit 合并（方案 §5）。

把 ``content_parsing`` 产生的 evidence_spans 用结构规则合并为 evidence_unit（§5.2.1），
每个单元保留 source_span_ids / heading_path / merge_reason / token_count（§9.1）。
小 LLM 合并边界判断为可选优化（§5.2.2）；默认只做结构合并以控成本。
"""
from __future__ import annotations

from typing import Any

from engine.core.db import DB
from engine.extraction.evidence_parsing import merge_spans_to_unit_rows, write_units
from engine.core.knowledge_service import document_provenance


DEFAULT_UNIT_PREFIX = "EU"


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = getattr(args, "document_uuid", None) or _resolve_document_uuid(db, args)
    document_id = getattr(args, "document_id", None)

    # 读取该文档所有 evidence_spans
    spans = db.query(
        "SELECT span_id, span_type, text, heading_path, order_index, char_start, "
        "char_end, locator FROM evidence_spans WHERE document_id=%s ORDER BY order_index",
        (document_uuid,),
    )
    if not spans:
        print(f"[evidence_unit_merge] no evidence spans for {document_id or document_uuid}")
        return {"pipeline": "evidence_unit_merge", "unit_count": 0,
                "document_uuid": str(document_uuid)}

    unit_rows = merge_spans_to_unit_rows(spans, unit_prefix=getattr(args, "unit_prefix", DEFAULT_UNIT_PREFIX))
    if not getattr(args, "dry_run", False):
        count = write_units(db, document_uuid, unit_rows)
    else:
        count = len(unit_rows)

    print(f"[evidence_unit_merge] {count} evidence units from {len(spans)} spans")
    return {
        "pipeline": "evidence_unit_merge",
        "document_uuid": str(document_uuid),
        "document_id": document_id,
        "span_count": len(spans),
        "unit_count": count,
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


def _resolve_document_uuid(db: DB, args) -> Any:
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("evidence_unit_merge requires --document-uuid or a known --document-id")
    return rows[0]["id"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 evidence unit merge")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--unit-prefix", default=DEFAULT_UNIT_PREFIX)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))