"""L2 pipeline: article_registration — 信源文章最小建档（方案 §3.1）。

只做最小建档：document_id / layer=l2_industry / published_at / original_url。
L2 不做来源质量检查、不做 source authority、不做权限门禁（§3.1）：任何文章都进入解析流程。
"""
from __future__ import annotations

from typing import Any

from legacy.core.db import DB
from legacy.core.knowledge_service import register_document, sha256_text


DEFAULT_PROFILE_ID = "l2_industry"
DEFAULT_MARKET = "CN"


def run(db: DB, args) -> dict[str, Any]:
    from shared.knowledge.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or DEFAULT_PROFILE_ID
    get_common_registry().require_profile(profile_id)
    layer = getattr(args, "layer", None) or "l2_industry"

    # 文章正文来源：--article-text / --file / 直接文本
    text = getattr(args, "article_text", None) or getattr(args, "text", None) or ""
    file_path = getattr(args, "file", None)
    if file_path:
        import os

        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    if not text:
        raise ValueError(
            "article_registration requires --text <正文> or --file <article.md>"
        )

    title = getattr(args, "title", None) or "untitled"
    url = getattr(args, "original_url", None) or getattr(args, "canonical_url", None)
    published_at = getattr(args, "published_at", None)
    document_id = getattr(args, "document_id", None) or f"doc_article_{sha256_text(text)[:12]}"

    doc_uuid = register_document(
        db,
        {
            "document_id": document_id,
            "tenant_id": getattr(args, "tenant_id", None),
            "layer": layer,
            "title": title,
            "canonical_url": url,
            "original_url": url,
            "published_at": published_at,
            "content_hash": sha256_text(text),
            "source_status": "active",
            "mime_type": getattr(args, "mime_type", None) or "markdown",
            "language": getattr(args, "language", None) or "zh-CN",
        },
        key_field="document_id",
    )
    result = {
        "pipeline": "article_registration",
        "profile_id": profile_id,
        "layer": layer,
        "document_id": document_id,
        "document_uuid": str(doc_uuid),
        "title": title,
        "content_hash": sha256_text(text),
        "text": text,
    }
    print(f"[article_registration] registered {document_id} ({len(text)} chars)")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 article registration")
    parser.add_argument("--text", help="Article body text")
    parser.add_argument("--file", help="Path to article file (md)")
    parser.add_argument("--title")
    parser.add_argument("--original-url")
    parser.add_argument("--published-at")
    parser.add_argument("--document-id")
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--layer", default="l2_industry")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))