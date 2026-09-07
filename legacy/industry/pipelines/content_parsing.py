"""L2 pipeline: content_parsing — 正文解析为 evidence_spans（方案 §4）。

把 ``article_registration`` 建档的文章正文切分为证据片段（heading/paragraph/list_item/table/caption），
写入 ``evidence_spans``（§9.1），并计算 heading_path / order_index / char 定位。
不做深语义判断（§3.2）。
"""
from __future__ import annotations

from typing import Any

from legacy.core.db import DB
from shared.extraction.evidence_parsing import parse_to_span_rows
from legacy.core.extraction_persistence import write_spans


DEFAULT_SPAN_PREFIX = "ES"


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = getattr(args, "document_uuid", None)
    document_id = getattr(args, "document_id", None)
    if not document_uuid:
        # 允许按 document_id 回查 UUID
        rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
        if not rows:
            raise ValueError("content_parsing requires --document-uuid or a known --document-id")
        document_uuid = rows[0]["id"]

    text = getattr(args, "text", None)
    if not text:
        article_path = getattr(args, "file", None)
        if article_path:
            with open(article_path, "r", encoding="utf-8") as f:
                text = f.read()
    if not text:
        raise ValueError(
            "content_parsing requires --text <article body> (or --file <article.md>). "
            "article_registration can keep the body on the namespace."
        )

    span_rows = parse_to_span_rows(text, span_prefix=getattr(args, "span_prefix", DEFAULT_SPAN_PREFIX))
    if not getattr(args, "dry_run", False):
        count = write_spans(db, document_uuid, span_rows)
    else:
        count = len(span_rows)

    print(f"[content_parsing] {count} evidence spans for document {document_id}")
    return {
        "pipeline": "content_parsing",
        "document_uuid": str(document_uuid),
        "document_id": document_id,
        "span_count": count,
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 content parsing")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--text")
    parser.add_argument("--span-prefix", default=DEFAULT_SPAN_PREFIX)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))
