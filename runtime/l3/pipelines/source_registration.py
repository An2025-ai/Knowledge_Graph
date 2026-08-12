"""L3 pipeline: Source Registration.

Per brand_knowledge/pipelines/source_registration.yaml, this is the first step of
the L3 brand-docs -> brand-knowledge flow. Before any brand material is read or
parsed it registers the source instance and document metadata so every later L3
pipeline has a traceable source baseline.

What this executor does (pragmatic implementation of the YAML semantics):
  1. derives a stable ``source_id`` / ``document_id`` from the input file path
     or an explicit ``--source-id`` / ``--document-id`` arg,
  2. computes a SHA-256 content hash,
  3. upserts a ``source_instance`` row (source_id, tenant_id, source_type,
     publisher, canonical_url/external_path, retrieved_at, content_hash,
     access_level, status) and records the brand context in ``attributes``
     (the L2 ``source_instance`` table has no ``brand_id`` column),
  4. resolves the source UUID and upserts the linked ``document`` row
     (brand context carried in ``properties``),
  5. honors the idempotency rule: same source_id + same content_hash is skipped.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context, sha256_bytes, now_iso


def _derive_source_info(args) -> dict:
    """Build source metadata from args + the file path."""
    file_path = getattr(args, "file", None)
    source_id = getattr(args, "source_id", None)
    document_id = getattr(args, "document_id", None)
    canonical_url = getattr(args, "canonical_url", None)
    external_path = getattr(args, "external_path", None)

    if not file_path:
        raise ValueError("source_registration requires --file <path>")

    fname = os.path.basename(file_path) if file_path else "unknown"
    if not source_id:
        source_id = f"src_{fname}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    if not document_id:
        document_id = f"doc_{os.path.splitext(fname)[0]}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"

    mime = getattr(args, "mime_type", None) or _mime_for(fname)
    return {
        "source_id": source_id,
        "document_id": document_id,
        "source_type": getattr(args, "source_type", None) or "document",
        "publisher": getattr(args, "publisher", None) or "unknown",
        "canonical_url": canonical_url,
        "external_path": external_path or file_path,
        "retrieved_at": getattr(args, "retrieved_at", None) or now_iso(),
        "published_at": getattr(args, "published_at", None),
        "document_version": getattr(args, "document_version", None) or "1.0.0",
        "language": getattr(args, "language", None) or "zh-CN",
        "mime_type": mime,
        "access_level": getattr(args, "access_level", None) or "internal",
        "title": getattr(args, "title", None) or fname,
        "file_path": file_path,
    }


def _mime_for(fname: str) -> str:
    ext = os.path.splitext(fname)[1].lower()
    return {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def run(db: DB, args) -> dict[str, Any]:
    """Register a source instance + linked document row for the input file."""
    src = _derive_source_info(args)
    ctx = resolve_brand_context(db, args)

    with open(src["file_path"], "rb") as f:
        content_hash = sha256_bytes(f.read())

    # --- idempotency: same source_id + same content_hash -> skip ---
    existing = db.query(
        "SELECT id, content_hash FROM source_instance WHERE source_id = %s LIMIT 1",
        (src["source_id"],),
    )
    if existing and existing[0]["content_hash"] == content_hash:
        print(f"[source_registration] idempotent skip for {src['source_id']} (same hash)")
        return {
            "pipeline": "source_registration",
            "source_id": src["source_id"],
            "document_id": src["document_id"],
            "idempotent": True,
            "content_hash": content_hash,
            "brand_id": ctx["brand_id"],
            "tenant_id": ctx["tenant_id"],
        }

    source_row = {
        "source_id": src["source_id"],
        "tenant_id": ctx["tenant_id"],
        "source_type": src["source_type"],
        "publisher": src["publisher"],
        "canonical_url": src["canonical_url"],
        "external_path": src["external_path"],
        "retrieved_at": src["retrieved_at"],
        "published_at": src["published_at"],
        "document_version": src["document_version"],
        "language": src["language"],
        "mime_type": src["mime_type"],
        "title": src["title"],
        "content_hash": content_hash,
        "access_level": src["access_level"],
        "status": "registered",
        "attributes": {
            "brand_id": ctx["brand_id"],
            "brand_key": ctx["brand_key"],
            "registered_at": now_iso(),
        },
    }

    if getattr(args, "dry_run", False):
        print("[source_registration] DRY-RUN would upsert source_instance + document")
        print(f"  source_id:   {src['source_id']}")
        print(f"  document_id: {src['document_id']}")
        print(f"  source_type: {src['source_type']}")
        print(f"  content_hash:{content_hash}")
        print(f"  brand:       {ctx['brand_key']} ({ctx['brand_id']})")
        return {
            "pipeline": "source_registration",
            "dry_run": True,
            "source_id": src["source_id"],
            "document_id": src["document_id"],
            "content_hash": content_hash,
            "brand_id": ctx["brand_id"],
            "tenant_id": ctx["tenant_id"],
        }

    db.upsert("source_instance", source_row, key_field="source_id")

    # resolve the source_instance UUID for the document FK
    src_rows = db.query(
        "SELECT id FROM source_instance WHERE source_id = %s LIMIT 1",
        (src["source_id"],),
    )
    source_uuid = src_rows[0]["id"] if src_rows else None

    document_row = {
        "document_id": src["document_id"],
        "tenant_id": ctx["tenant_id"],
        "source_id": source_uuid,
        "canonical_url": src["canonical_url"],
        "document_version": src["document_version"],
        "title": src["title"],
        "language": src["language"],
        "mime_type": src["mime_type"],
        "content_hash": content_hash,
        "access_level": src["access_level"],
        "status": "active",
        "properties": {
            "brand_id": ctx["brand_id"],
            "brand_key": ctx["brand_key"],
            "external_path": src["external_path"],
            "registered_at": now_iso(),
        },
    }
    db.upsert("document", document_row, key_field="document_id")

    print(f"[source_registration] registered source {src['source_id']} -> document {src['document_id']}")
    return {
        "pipeline": "source_registration",
        "source_id": src["source_id"],
        "document_id": src["document_id"],
        "source_uuid": source_uuid,
        "content_hash": content_hash,
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
        "status": "registered",
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 source registration pipeline")
    parser.add_argument("--file", required=True, help="Path to the brand source file")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key (default: 'default')")
    parser.add_argument("--source-id", help="Optional source_id")
    parser.add_argument("--document-id", help="Optional document_id")
    parser.add_argument("--source-type", help="Source type (document/website/media/...)")
    parser.add_argument("--publisher", help="Publisher name")
    parser.add_argument("--canonical-url", help="Canonical URL")
    parser.add_argument("--document-version", help="Document version")
    parser.add_argument("--access-level", choices=["public", "internal", "confidential", "restricted"])
    parser.add_argument("--language", help="Document language (default zh-CN)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2))