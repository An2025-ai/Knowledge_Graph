"""L3 pipeline: evidence_unit_merge — span → evidence_unit 合并（方案 §11.2）。

原 semantic_chunking 从「深语义切块」降级为与 L2 一致的结构规则合并（§5.2.1），
把该文档的 evidence_spans 合并为 ``evidence_units``，记录 source_span_ids /
heading_path / merge_reason / token_count。小 LLM 合并边界判断为可选优化（§5.2.2）。

复用共享 ``shared.extraction.evidence_parsing``（结构优先，可控成本）。
"""
from __future__ import annotations

from typing import Any

from legacy.core.db import DB
from shared.extraction.evidence_parsing import merge_spans_to_unit_rows
from legacy.core.extraction_persistence import write_units


def _resolve_document_uuid(db: DB, args) -> Any:
    document_uuid = getattr(args, "document_uuid", None)
    if document_uuid:
        return document_uuid
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("evidence_unit_merge requires --document-uuid or a known --document-id")
    return rows[0]["id"]


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = _resolve_document_uuid(db, args)
    document_id = getattr(args, "document_id", None) or str(document_uuid)

    spans = db.query(
        "SELECT span_id, span_type, text, heading_path, order_index, char_start, "
        "char_end, locator FROM evidence_spans WHERE document_id=%s ORDER BY order_index",
        (document_uuid,),
    )
    if not spans:
        print(f"[evidence_unit_merge] no evidence spans for {document_id}")
        return {"pipeline": "evidence_unit_merge", "unit_count": 0,
                "document_uuid": str(document_uuid)}

    unit_rows = merge_spans_to_unit_rows(
        spans, unit_prefix=getattr(args, "unit_prefix", "EU"))
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


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 evidence unit merge")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--uuid", dest="document_uuid")
    parser.add_argument("--unit-prefix", default="EU")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))
