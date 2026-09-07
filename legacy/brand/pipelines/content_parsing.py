"""L3 pipeline: content_parsing — 正文解析到 evidence_spans（方案 §11.2）。

原 layout_aware_parsing 的解析能力统一到此处：读取品牌文档正文，按结构（标题/段落/
列表/表格/标题路径/字符定位）切分为 ``evidence_spans``（§4），为后续证据单元合并与
候选抽取提供带溯源的基础单元。依赖 ``--document-id``（由 document_registration 产生）。

复用共享 ``shared.extraction.evidence_parsing``（与 L2 content_parsing 同一套证据层机械，但流程独立）。
"""
from __future__ import annotations

from typing import Any

from legacy.core.db import DB
from shared.extraction.evidence_parsing import parse_to_span_rows
from legacy.core.extraction_persistence import write_spans


def _resolve_document_uuid(db: DB, args) -> Any:
    document_uuid = getattr(args, "document_uuid", None)
    if document_uuid:
        return document_uuid
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("content_parsing requires --document-uuid or a known --document-id")
    return rows[0]["id"]


def _read_text(args) -> str:
    file_path = getattr(args, "file", None)
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    text = getattr(args, "text", None)
    if text:
        return text
    raise ValueError("content_parsing requires --file or --text")


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = _resolve_document_uuid(db, args)
    text = _read_text(args)
    doc_id = getattr(args, "document_id", None) or str(document_uuid)

    span_rows = parse_to_span_rows(text, span_prefix=getattr(args, "span_prefix", "ES"))
    count = 0
    if not getattr(args, "dry_run", False):
        count = write_spans(db, document_uuid, span_rows)
    else:
        count = len(span_rows)

    print(f"[content_parsing] {count} spans from document {doc_id}")
    return {
        "pipeline": "content_parsing",
        "document_uuid": str(document_uuid),
        "document_id": doc_id,
        "span_count": count,
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 content parsing pipeline")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--uuid", dest="document_uuid")
    parser.add_argument("--file", help="Path to source file")
    parser.add_argument("--text", help="Raw document text")
    parser.add_argument("--span-prefix", default="ES")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))
