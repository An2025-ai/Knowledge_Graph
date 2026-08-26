"""L3 pipeline: candidate_vectorization — 候选知识向量化（方案 §11.2 / §6.3.5）。

对 ``knowledge_candidates`` 生成向量写入 ``candidate_embedding``（pgvector 1024 维），
向量化发生在跨文档融合之前，供实体消解/关系对齐/冲突检测复用同一批 embedding。
复用 ``runtime.clients.embeddings``（bge-m3）。与 L2 同名管道同一套向量层。
"""
from __future__ import annotations

from typing import Any

from runtime.core.db import DB


def _resolve_document_uuid(db: DB, args) -> Any:
    document_uuid = getattr(args, "document_uuid", None)
    if document_uuid:
        return document_uuid
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("candidate_vectorization requires --document-uuid or a known --document-id")
    return rows[0]["id"]


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = _resolve_document_uuid(db, args)

    candidates = db.query(
        "SELECT candidate_id, evidence_text, confidence FROM knowledge_candidates "
        "WHERE document_id=%s ORDER BY candidate_id",
        (document_uuid,),
    )
    if not candidates:
        print(f"[candidate_vectorization] no candidates for {document_uuid}")
        return {"pipeline": "candidate_vectorization", "vectorized_count": 0}

    from runtime.clients.embeddings import get_embedding_client
    from runtime.core.knowledge_service import stable_hash

    def _embed_one(candidate_id: str, text: str) -> list[float] | None:
        try:
            return get_embedding_client().embed_one(text)
        except Exception as exc:  # noqa: BLE001 - optional vector layer
            print(f"[candidate_vectorization] embed skip for {candidate_id}: {exc}")
            return None

    count = 0
    missing = 0
    for cand in candidates:
        text = (cand.get("evidence_text") or "").strip()
        if not text:
            missing += 1
            continue
        vec = _embed_one(cand["candidate_id"], text)
        if vec is None:
            continue
        if getattr(args, "dry_run", False):
            count += 1
            continue
        embedding_id = f"emb_{stable_hash(cand['candidate_id'])}"
        db.execute(
            "INSERT INTO candidate_embedding (candidate_id, tenant_id, embedding_model, "
            " embedding, embedded_text) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (candidate_id) DO UPDATE SET "
            "embedding=EXCLUDED.embedding, embedded_text=EXCLUDED.embedded_text, "
            "embedding_model=EXCLUDED.embedding_model, updated_at=NOW()",
            (cand["candidate_id"], None, "BAAI/bge-m3", vec, text),
        )
        db.execute(
            "UPDATE knowledge_candidates SET embedding_id=%s WHERE candidate_id=%s",
            (embedding_id, cand["candidate_id"]),
        )
        count += 1

    print(f"[candidate_vectorization] vectorized {count} candidates (skipped {missing})")
    return {
        "pipeline": "candidate_vectorization",
        "vectorized_count": count,
        "no_text_count": missing,
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 candidate vectorization")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--uuid", dest="document_uuid")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))