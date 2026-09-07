"""L2 pipeline: candidate_normalization — 候选知识归一化（方案 §6.3.5）。

对 ``knowledge_candidates`` 做轻量归一：
- 实体 mention 别名标准化（去空白/顿号列表拆分）
- 指标数值类型统一（无法解析则保留原值）
- 语句去首尾空白、规范标点
归一化不改变候选语义，只收敛表示，降低下游去重/融合噪音。
"""
from __future__ import annotations

import re
from typing import Any

from legacy.core.db import DB


_NUMERIC_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def normalize_candidate(row: dict) -> dict:
    """Return a normalized copy of a knowledge_candidate row (in-memory)."""
    normalized = dict(row)
    # subject 名称清洗
    subject = dict(row.get("subject") or {})
    if isinstance(subject.get("name"), str):
        subject["name"] = re.sub(r"\s+", " ", subject["name"]).strip()
        subject["name"] = subject["name"].rstrip("。；，、")
    normalized["subject"] = subject
    # metric 数值规范化
    metric = dict(row.get("metric") or {})
    if metric.get("value") is None:
        metric = row.get("metric") or {}
    if isinstance(metric.get("value"), str):
        v = metric["value"].strip()
        metric["value"] = float(v) if _NUMERIC_RE.match(v) else v
    normalized["metric"] = metric
    # statement 文本规范化
    stmt = dict(row.get("statement") or {})
    if isinstance(stmt.get("text"), str):
        stmt["text"] = " ".join(stmt["text"].split())
    normalized["statement"] = stmt
    return normalized


def run(db: DB, args) -> dict[str, Any]:
    document_uuid = getattr(args, "document_uuid", None) or _resolve_document_uuid(db, args)
    candidates = db.query(
        "SELECT * FROM knowledge_candidates WHERE document_id=%s ORDER BY candidate_id",
        (document_uuid,),
    )
    if not candidates:
        print(f"[candidate_normalization] no candidates for {document_uuid}")
        return {"pipeline": "candidate_normalization", "normalized_count": 0}

    count = 0
    for raw in candidates:
        norm = normalize_candidate(raw)
        if not getattr(args, "dry_run", False):
            db.execute(
                "UPDATE knowledge_candidates SET subject=%s::jsonb, metric=%s::jsonb, "
                " statement=%s::jsonb WHERE candidate_id=%s",
                (
                    db._json(norm.get("subject") or {}),
                    db._json(norm.get("metric") or {}),
                    db._json(norm.get("statement") or {}),
                    raw["candidate_id"],
                ),
            )
        count += 1

    print(f"[candidate_normalization] normalized {count} candidates")
    return {"pipeline": "candidate_normalization", "normalized_count": count,
            "dry_run": bool(getattr(args, "dry_run", False))}


def _resolve_document_uuid(db: DB, args) -> Any:
    document_uuid = getattr(args, "document_uuid", None)
    if document_uuid:
        return document_uuid
    document_id = getattr(args, "document_id", None)
    rows = db.query("SELECT id FROM document WHERE document_id=%s LIMIT 1", (document_id,))
    if not rows:
        raise ValueError("candidate_normalization requires --document-uuid or a known --document-id")
    return rows[0]["id"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 candidate normalization")
    parser.add_argument("--document-id")
    parser.add_argument("--document-uuid")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))