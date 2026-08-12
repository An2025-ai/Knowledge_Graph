"""L3 pipeline: Layout-Aware Parsing.

Per brand_knowledge/pipelines/layout_aware_parsing.yaml, the parser converts a
gated original (markdown / text / html) into a structured content tree that
preserves heading hierarchy and heading_path for evidence traceability.

This executor is a pragmatic text-level parser:
  - Markdown: split on ATX headings (#..######),
  - HTML: split on <h1>..<h6> tags (headings retained in the path),
  - plain text: fall back to paragraph-level sections.

For each section it upserts a ``document_chunk`` row with
``chunk_type='section_chunk'``, a sequential ``chunk_index``, the ``heading_path``
and the section ``text``. Existing section_chunks for the document are cleared
first so re-runs are idempotent.
"""
from __future__ import annotations

import re
from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context, sha256_text


def _split_sections(text: str, mime_hint: str) -> list[tuple[str, str]]:
    """Return ``(heading_path, section_text)`` list for a markdown/html/txt file."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if mime_hint in ("text/markdown", "text/plain") or not mime_hint:
        return _split_markdown(text)
    if "html" in mime_hint:
        return _split_html(text)
    return _split_markdown(text)


MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_markdown(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        m = MD_HEADING.match(line)
        if not m:
            idx += 1
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        body: list[str] = []
        idx += 1
        while idx < len(lines) and not MD_HEADING.match(lines[idx]):
            body.append(lines[idx])
            idx += 1
        sections.append((title, "\n".join(body).strip()))
    # If no headings were found, fall back to paragraph-level sections.
    if not sections:
        para = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        sections = [(f"{i + 1}", p) for i, p in enumerate(para)]
    return sections


HTML_HEADING = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)


def _split_html(text: str) -> list[tuple[str, str]]:
    # Strip tags to plain text, then reuse markdown heading splitting on a
    # temporary ATX representation so headings are preserved.
    def repl(m):
        return "\n" + "#" * int(m.group(1)) + " " + re.sub(r"<[^>]+>", "", m.group(2)).strip() + "\n"
    converted = HTML_HEADING.sub(repl, text)
    return _split_markdown(converted)


def run(db: DB, args) -> dict[str, Any]:
    """Parse the file into heading sections and upsert section_chunks."""
    file_path = getattr(args, "file", None)
    if not file_path:
        raise ValueError("layout_aware_parsing requires --file <path>")

    ctx = resolve_brand_context(db, args)
    document_id = getattr(args, "document_id", None)
    if not document_id:
        raise ValueError("layout_aware_parsing requires --document-id (source_registration output)")

    mime_hint = getattr(args, "mime_type", None) or ""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    sections = _split_sections(raw, mime_hint)

    # resolve document UUID
    doc_rows = db.query("SELECT id FROM document WHERE document_id = %s LIMIT 1", (document_id,))
    if not doc_rows:
        raise ValueError(f"document not found: {document_id}. Run source_registration first.")
    doc_uuid = doc_rows[0]["id"]

    if getattr(args, "dry_run", False):
        print(f"[layout_aware_parsing] DRY-RUN would upsert {len(sections)} section_chunks")
        for i, (title, body) in enumerate(sections[:5]):
            print(f"  [{i}] #{title} ({len(body)} chars)")
        return {
            "pipeline": "layout_aware_parsing",
            "dry_run": True,
            "document_id": document_id,
            "section_count": len(sections),
        }

    # Clear prior section_chunks for this document so re-runs are idempotent.
    db.execute(
        "DELETE FROM document_chunk WHERE document_id = %s AND chunk_type = 'section_chunk'",
        (doc_uuid,),
    )

    for i, (title, body) in enumerate(sections):
        db.execute(
            "INSERT INTO document_chunk "
            "(id, document_id, chunk_index, chunk_type, heading_path, text, content_hash, access_level) "
            "VALUES (uuid_generate_v4(), %s, %s, 'section_chunk', %s, %s, %s, %s)",
            (doc_uuid, i, title, body, sha256_text(body),
             getattr(args, "access_level", None) or "internal"),
        )

    print(f"[layout_aware_parsing] parsed {len(sections)} sections into document_chunk ({document_id})")
    return {
        "pipeline": "layout_aware_parsing",
        "document_id": document_id,
        "section_count": len(sections),
        "sections": [{"heading_path": t, "chars": len(b)} for t, b in sections],
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 layout-aware parsing pipeline")
    parser.add_argument("--file", required=True, help="Path to the brand source file")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--document-id", required=True, help="document_id from source_registration")
    parser.add_argument("--mime-type", help="MIME hint (text/markdown|text/plain|text/html)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2))