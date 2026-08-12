"""L3 pipeline: Semantic Chunking.

Per brand_knowledge/pipelines/semantic_chunking.yaml, the chooser splits a parsed
document into semantic blocks. This executor produces the ``Evidence Span`` block
type from the ``Section Chunk`` blocks written by layout_aware_parsing.

An Evidence Span is the minimal contiguous span of original text that directly
supports one statement — generally 1-5 sentences or a single table row. We honor
the "no fixed-character-count chunking" rule by splitting on sentence boundaries
and grouping consecutive sentences into spans of 1-5, never breaking a table row.

Each span is stored in ``document_chunk`` with ``chunk_type='evidence_span'``,
a sequential ``chunk_index``, the parent section ``heading_path`` and the span
``text``. Prior evidence spans for the document are cleared first (idempotent).
"""
from __future__ import annotations

import re
from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context, sha256_text

# Sentence delimiters covering CJK and Latin punctuation.
_SENT_END = re.compile(r"(?<=[。！？!?.;；])")

# Evidence Span size bounds (sentences), per the YAML (usually 1-5).
_SPAN_MIN = 1
_SPAN_MAX = 5


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence units, preserving table rows whole."""
    segments = _SENT_END.split(text)
    sentences = []
    for seg in segments:
        s = seg.strip()
        if not s:
            continue
        # do not break a table row: keep a leading '|' row as one unit
        if sentences and _is_table_row(s) and not _is_table_row(sentences[-1]):
            sentences[-1] += " " + s
        else:
            sentences.append(s)
    return sentences


def _is_table_row(s: str) -> bool:
    return s.startswith("|") and "|" in s[1:]


def _group_spans(sentences: list[str]) -> list[str]:
    """Group sentences into 1-5 sentence spans (never splitting table rows)."""
    spans: list[str] = []
    current: list[str] = []
    for s in sentences:
        if not current:
            current.append(s)
            continue
        # force break if adding would exceed the max, unless current is a table
        # row group that must stay together
        if len(current) >= _SPAN_MAX:
            if _is_table_row(s) and len(current) <= _SPAN_MAX:
                current.append(s)
            else:
                spans.append(" ".join(current))
                current = [s]
        else:
            current.append(s)
    if current:
        spans.append(" ".join(current))
    return spans


def run(db: DB, args) -> dict[str, Any]:
    """Read section_chunks and write evidence_span chunks."""
    ctx = resolve_brand_context(db, args)
    document_id = getattr(args, "document_id", None)
    if not document_id:
        raise ValueError("semantic_chunking requires --document-id")

    doc_rows = db.query("SELECT id FROM document WHERE document_id = %s LIMIT 1", (document_id,))
    if not doc_rows:
        raise ValueError(f"document not found: {document_id}. Run source_registration first.")
    doc_uuid = doc_rows[0]["id"]

    sections = db.query(
        "SELECT chunk_index, heading_path, text FROM document_chunk "
        "WHERE document_id = %s AND chunk_type = 'section_chunk' ORDER BY chunk_index",
        (doc_uuid,),
    )
    if not sections:
        raise ValueError(f"no section_chunks found for {document_id}. Run layout_aware_parsing first.")

    spans: list[dict] = []
    span_idx = 0
    for sec in sections:
        for span_text in _group_spans(_split_sentences(sec["text"])):
            if not span_text.strip():
                continue
            spans.append(
                {
                    "chunk_index": span_idx,
                    "heading_path": sec["heading_path"],
                    "text": span_text,
                    "char_count": len(span_text),
                }
            )
            span_idx += 1

    if getattr(args, "dry_run", False):
        print(f"[semantic_chunking] DRY-RUN would write {len(spans)} evidence_span chunks")
        for sp in spans[:5]:
            print(f"  [{sp['chunk_index']}] {sp['heading_path']} ({sp['char_count']} chars): {sp['text'][:60]}...")
        return {
            "pipeline": "semantic_chunking",
            "dry_run": True,
            "document_id": document_id,
            "span_count": len(spans),
        }

    db.execute(
        "DELETE FROM document_chunk WHERE document_id = %s AND chunk_type = 'evidence_span'",
        (doc_uuid,),
    )
    for sp in spans:
        db.execute(
            "INSERT INTO document_chunk "
            "(id, document_id, chunk_index, chunk_type, heading_path, text, content_hash, access_level) "
            "VALUES (uuid_generate_v4(), %s, %s, 'evidence_span', %s, %s, %s, %s)",
            (doc_uuid, sp["chunk_index"], sp["heading_path"], sp["text"],
             sha256_text(sp["text"]), getattr(args, "access_level", None) or "internal"),
        )

    print(f"[semantic_chunking] wrote {len(spans)} evidence_span chunks ({document_id})")
    return {
        "pipeline": "semantic_chunking",
        "document_id": document_id,
        "span_count": len(spans),
        "section_count": len(sections),
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 semantic chunking pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--document-id", required=True, help="document_id from source_registration")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2))