"""L3 pipeline: document_registration — 文档最小建档 + 品牌上下文（方案 §11.2）。

合并原 source_registration 的建档职责与品牌上下文解析（resolve_brand_context）：
- 解析 ``--brand`` / ``--tenant`` → tenant_id / brand_id（建 tenant/brand_workspace）
- 由 ``--file`` 派生稳定 source_id / document_id，SHA-256 计算内容哈希
- 幂等 upsert ``source_instance`` + ``document``（layer=l3_brand，品牌上下文记入 properties）

不在此做敏感内容/来源质量断（由 sensitive_content_warning 提醒）。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from engine.core.db import DB
from engine.brand.pipelines._helpers import (
    resolve_brand_context,
    sha256_bytes,
    now_iso,
)


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


def _derive_source_info(args) -> dict:
    file_path = getattr(args, "file", None)
    source_id = getattr(args, "source_id", None)
    document_id = getattr(args, "document_id", None)
    if not file_path:
        raise ValueError("document_registration requires --file <path>")

    fname = os.path.basename(file_path) if file_path else "unknown"
    if not source_id:
        source_id = f"src_{fname}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    if not document_id:
        document_id = f"doc_{os.path.splitext(fname)[0]}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"

    return {
        "source_id": source_id,
        "document_id": document_id,
        "source_type": getattr(args, "source_type", None) or "document",
        "publisher": getattr(args, "publisher", None) or "unknown",
        "canonical_url": getattr(args, "canonical_url", None),
        "external_path": getattr(args, "external_path", None) or file_path,
        "retrieved_at": getattr(args, "retrieved_at", None) or now_iso(),
        "published_at": getattr(args, "published_at", None),
        "document_version": getattr(args, "document_version", None) or "1.0.0",
        "language": getattr(args, "language", None) or "zh-CN",
        "mime_type": getattr(args, "mime_type", None) or _mime_for(fname),
        "access_level": getattr(args, "access_level", None) or "internal",
        "title": getattr(args, "title", None) or fname,
        "file_path": file_path,
    }


def run(db: DB, args) -> dict[str, Any]:
    src = _derive_source_info(args)
    ctx = resolve_brand_context(db, args)

    with open(src["file_path"], "rb") as f:
        content_hash = sha256_bytes(f.read())

    existing = db.query(
        "SELECT id, content_hash FROM source_instance WHERE source_id = %s LIMIT 1",
        (src["source_id"],),
    )
    if existing and existing[0]["content_hash"] == content_hash:
        print(f"[document_registration] idempotent skip for {src['source_id']} (same hash)")
        return {
            "pipeline": "document_registration",
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
        print("[document_registration] DRY-RUN would upsert source_instance + document")
        return {
            "pipeline": "document_registration",
            "dry_run": True,
            "document_id": src["document_id"],
            "content_hash": content_hash,
            "brand_id": ctx["brand_id"],
            "tenant_id": ctx["tenant_id"],
        }

    db.upsert("source_instance", source_row, key_field="source_id")

    src_rows = db.query(
        "SELECT id FROM source_instance WHERE source_id = %s LIMIT 1",
        (src["source_id"],),
    )
    source_uuid = src_rows[0]["id"] if src_rows else None

    document_row = {
        "document_id": src["document_id"],
        "tenant_id": ctx["tenant_id"],
        "source_id": source_uuid,
        "layer": "l3_brand",
        "canonical_url": src["canonical_url"],
        "original_url": src["canonical_url"],
        "document_version": src["document_version"],
        "title": src["title"],
        "language": src["language"],
        "mime_type": src["mime_type"],
        "published_at": src["published_at"],
        "content_hash": content_hash,
        "source_status": "active",
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

    print(f"[document_registration] registered source {src['source_id']} -> document {src['document_id']}")
    return {
        "pipeline": "document_registration",
        "document_id": src["document_id"],
        "source_id": src["source_id"],
        "source_uuid": source_uuid,
        "content_hash": content_hash,
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
        "status": "registered",
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 document registration pipeline")
    parser.add_argument("--file", required=True, help="Path to the brand source file")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key (default: 'default')")
    parser.add_argument("--source-id", help="Optional source_id")
    parser.add_argument("--document-id", help="Optional document_id")
    parser.add_argument("--source-type")
    parser.add_argument("--publisher")
    parser.add_argument("--canonical-url")
    parser.add_argument("--document-version")
    parser.add_argument("--access-level", choices=["public", "internal", "confidential", "restricted"])
    parser.add_argument("--language")
    parser.add_argument("--published-at")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args()

    with DB.from_env() as db:
        print(json.dumps(run(db, ns), ensure_ascii=False, indent=2))