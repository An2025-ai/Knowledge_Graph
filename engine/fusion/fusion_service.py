"""Shared cross-document fusion service: knowledge_candidates → gate_candidates（方案 §8）。

L2 与 L3 各自的 ``knowledge_fusion.py`` pipeline 复用这里，实现跨文档四类动作：
- 融合（fuse）：同主题（subject+predicate+object）候选聚一条，聚合 evidence_refs / source_candidate_ids
- 冲突（conflict）：同 subject+predicate 但 object/value 不同的候选 → 分裂为冲突候选（供 promotion review）
- 补充（complement）：同 subject 的独立属性 → 独立候选，证据各自保留
- 跨实体建联（cross_entity_linking）：同一 mention/entity 的不同名别名聚为 gate_candidate_entity

输出写入 ``gate_candidate_entities`` / ``gate_candidate_knowledge``（§9.3），gate_status=pending。
不做深模型判断（§8.3 提到的 embedding/LLM 归并是可选的，这里提供确定性基线）。
"""
from __future__ import annotations

import re
from typing import Any

from engine.core.db import DB
from engine.core.knowledge_service import (
    stable_hash,
    upsert_gate_entity,
    upsert_gate_knowledge,
)

_MENTION_NORM_RE = re.compile(r"[\s，,、。;；：]+")


def _norm_name(name: str) -> str:
    return _MENTION_NORM_RE.sub("", name or "").casefold()


def _subject_key(subject: dict) -> str:
    return _norm_name(subject.get("name") or "")


def load_candidates(db: DB, profile_id: str) -> list[dict]:
    return db.query(
        "SELECT * FROM knowledge_candidates WHERE profile_id=%s ORDER BY created_at",
        (profile_id,),
    )


# ---------------------------------------------------------------------------
# 实体消解
# ---------------------------------------------------------------------------

def resolve_entities(
    db: DB,
    candidates: list[dict],
    *,
    profile_id: str,
    layer: str,
    tenant_id: Any | None,
) -> dict[str, dict]:
    """Merge same-type same-name entity mentions into one gate_candidate_entity.

    Returns {canonical_name: gate_entity_row}. Deterministic: first-seen type
    wins; aliases/evidence aggregated across mentions.
    """
    from engine.common.registry import get_common_registry
    from engine.core.knowledge_service import stable_hash

    allowed = set(get_common_registry().entity_types(profile_id))
    by_key: dict[str, dict] = {}
    for cand in candidates:
        subject = cand.get("subject") or {}
        name = subject.get("name")
        etype = subject.get("entity_type")
        if not name:
            continue
        if etype and etype not in allowed:
            continue
        etype = etype or "organization"
        key = f"{etype}::{_norm_name(name)}"
        ent = by_key.get(key)
        entity_id = f"ENT_{profile_id.split('_')[0].upper()}_{stable_hash(etype, name)}"
        if ent is None:
            ent = {
                "entity_id": entity_id,
                "profile_id": profile_id,
                "layer": layer,
                "tenant_id": tenant_id,
                "entity_type": etype,
                "name": name,
                "aliases": [],
                "description": "",
                "source_candidate_ids": [],
                "evidence_refs": [],
                "confidence": cand.get("confidence", 0.5),
            }
            by_key[key] = ent
        else:
            ent["confidence"] = max(ent["confidence"], cand.get("confidence", 0.0))
        # 聚合别名/候选/证据
        if name and name not in ent["aliases"]:
            ent["aliases"].append(name)
        if cand["candidate_id"] not in ent["source_candidate_ids"]:
            ent["source_candidate_ids"].append(cand["candidate_id"])
        if cand.get("evidence_unit_id") and cand["evidence_unit_id"] not in ent["evidence_refs"]:
            ent["evidence_refs"].append({"evidence_unit_id": cand["evidence_unit_id"]})
    return by_key


# ---------------------------------------------------------------------------
# 候选分组与门禁知识生成
# ---------------------------------------------------------------------------

def _emit_knowledge(
    db: DB,
    group_key: str,
    profile_id: str,
    layer: str,
    tenant_id: Any | None,
    members: list[dict],
) -> dict:
    """Merge one candidate group into a single gate_candidate_knowledge row.

    Uses the first member's shape (relation/metric/statement/event) and aggregates
    evidence_refs + source_candidate_ids + source_document_ids + latest_published_at.
    """
    first = members[0]
    ktype = first["candidate_type"]
    subject = first.get("subject") or {}
    # Fail-fast（审查 Critical #4）：relation 候选必须带非空 predicate.type，否则写出的
    # gate 行 predicate_type=None，融合/晋级全部丢失关系语义，且会造成名义上的“关系”却无
    # 谓词。宁可在这里显式报错，也不要静默写入坏数据。
    if ktype == "relation" and not (first.get("predicate") or {}).get("type"):
        raise ValueError(
            f"relation candidate {first.get('candidate_id')} has empty predicate.type; "
            f"won't emit a predicate-less gate row"
        )
    knowledge_id = f"GK_{profile_id.split('_')[0].upper()}_{stable_hash(group_key)}"

    evidence_refs: list[dict] = []
    source_candidate_ids: list[str] = []
    source_document_ids: list[str] = []
    latest_published = None
    for m in members:
        # 溯源语义：source_document_ids=来源 document（候选的 document_id/document_uuid，
        # 审查 Critical #5）。evidence_unit_id 只进 evidence_refs，绝不混入 document 列表，
        # 否则「文档溯源」字段被 evidence 单元 id 污染。
        doc_id = m.get("document_id") or m.get("document_uuid")
        if doc_id and doc_id not in source_document_ids:
            source_document_ids.append(doc_id)
        if m.get("candidate_id") not in source_candidate_ids:
            source_candidate_ids.append(m["candidate_id"])
        if m.get("evidence_text"):
            evidence_refs.append({
                "quote": m["evidence_text"][:4000],
                "evidence_unit_id": m.get("evidence_unit_id"),
                "access_status": "ok",
                "support_status": "directly_supports",
            })
        pub = m.get("published_at")
        if pub and (latest_published is None or pub > latest_published):
            latest_published = pub

    row = {
        "knowledge_id": knowledge_id,
        "profile_id": profile_id,
        "layer": layer,
        "tenant_id": tenant_id,
        "knowledge_type": ktype,
        "subject_entity_id": subject.get("entity_id") or (subject.get("name") or ""),
        "predicate_type": (first.get("predicate") or {}).get("type") if ktype in ("relation",) else
                          ((first.get("predicate") or {}).get("type") or None),
        "object_entity_id": (first.get("object") or {}).get("entity_id")
                            or ((first.get("object") or {}).get("name") or None),
        "statement_text": (first.get("statement") or {}).get("text")
                          if ktype == "statement" else
                          (first.get("predicate") or {}).get("text"),
        "metric_name": (first.get("metric") or {}).get("type")
                       if ktype == "metric" else None,
        "metric_value": first.get("metric") if ktype == "metric" else None,
        "event": first.get("event"),
        "scope": first.get("scope") or {},
        "time_scope": {},
        "evidence_refs": evidence_refs,
        "source_candidate_ids": source_candidate_ids,
        "source_document_ids": source_document_ids,
        "latest_published_at": latest_published,
        "confidence": max((m.get("confidence", 0.0) for m in members), default=0.5),
        # schema_valid：从候选透传（build_candidate_rows 抽取时显式赋值）。
        # 缺省 False —— 未标注 schema_valid 的聚合行在 promotion gate_schema 被挡下，
        # 而非静默通过（审查 High #7）。
        "schema_valid": bool(first.get("schema_valid", False)),
        "gate_status": "pending",
    }
    upsert_gate_knowledge(db, row)
    return row


def group_and_emit(
    db: DB,
    candidates: list[dict],
    entities: dict[str, dict],
    *,
    profile_id: str,
    layer: str,
    tenant_id: Any | None,
) -> dict[str, Any]:
    """Group candidates and emit gate_candidate_knowledge rows.

    Group key: (candidate_type, subject_entity_id, predicate)/ (metric name) /
    (statement normalized text) / (event name). Returns stats {fused, conflicted,
    emitted_who}.
    """
    from engine.core.knowledge_service import stable_hash

    groups: dict[str, list[dict]] = {}
    n_fused = 0
    n_conflicted = 0
    for cand in candidates:
        subject = cand.get("subject") or {}
        name = subject.get("name")
        # Normalize exactly like resolve_entities: a JSONB `null` entity_type must
        # fall back to the default type here too, otherwise the group key uses
        # "None::name" while the resolved-entity map uses "organization::name" and
        # the gate row never links to the gate entity it was resolved to.
        etype = subject.get("entity_type") or "organization"
        # 把候选 subject 关联到已消解的门禁实体 id
        key = f"{etype}::{_norm_name(name)}"
        gate_ent = entities.get(key, {})
        subject = dict(subject)
        subject["entity_id"] = gate_ent.get("entity_id") or name
        cand["subject"] = subject

        ctype = cand["candidate_type"]
        # 无锚点：候选的主语没有消解到 gate_candidate_entity（例如纯数值/日期规则抽取无
        # 名称，或名称类型不在 L1 本体 allowed 内）。写入 gate_candidate_knowledge 会以
        # 空串或原样 name 引用 subject_entity_id ≡ 无效外键（真实 Postgres 直接报错），
        # 且 promote 也找不到主体实体而无法晋级。直接丢弃这类无法落地的候选。
        if not gate_ent:
            continue
        if ctype == "relation":
            # 分组键：同 subject+predicate 归为一组（§8 冲突判定前提）；object 参与
            # 组内冲突判定而不进分组键，否则不同 object 的候选永远分不到一组。
            group_key = f"relation::{gate_ent.get('entity_id') or name}::" \
                        f"{(cand.get('predicate') or {}).get('type')}"
        elif ctype == "metric":
            group_key = f"metric::{gate_ent.get('entity_id') or name}::" \
                        f"{(cand.get('metric') or {}).get('type')}"
        elif ctype == "event":
            group_key = f"event::{gate_ent.get('entity_id') or name}::" \
                        f"{(cand.get('event') or {}).get('name') or ''}"
        else:  # statement
            group_key = f"statement::{gate_ent.get('entity_id') or name}::" \
                        f"{_norm_name((cand.get('statement') or {}).get('text') or '')}"
        groups.setdefault(group_key, []).append(cand)

    emitted = []
    conflict_keys = set()
    for group_key, members in groups.items():
        # 冲突检测：同 subject+predicate 但 object/value 不同 → 保留多条供 review
        distinct_objects = {m.get("object") and (m.get("object") or {}).get("name") or "∅"
                            for m in members}
        if len(members) > 1 and len(distinct_objects) > 1:
            n_conflicted += len(members)
            for m in members:
                emitted.append(_emit_knowledge_individual(
                    db, _emit_key(m), profile_id, layer, tenant_id, m))
            conflict_keys.add(group_key)
        else:
            n_fused += max(len(members) - 1, 0)
            # 融合行的稳定 id 仍应包含唯一 object（保证 id 稳定、可区分）
            emit_key = _emit_key(members[0])
            emitted.append(_emit_knowledge(
                db, emit_key, profile_id, layer, tenant_id, members))
    return {"fused": n_fused, "conflicted": n_conflicted,
            "emitted": len(emitted), "conflict_groups": len(conflict_keys)}


def _emit_key(cand: dict) -> str:
    """Stable emit-key (with object/value) used to build the gate row's knowledge_id.

    Distinct from the *grouping* key (without object) so conflict candidates keep
    distinct stable ids while still being grouped together for the conflict check.
    """
    ctype = cand["candidate_type"]
    subject = cand.get("subject") or {}
    name = subject.get("name")
    gate_id = subject.get("entity_id") or name
    if ctype == "relation":
        return f"relation::{gate_id}::" \
               f"{(cand.get('predicate') or {}).get('type')}::" \
               f"{(cand.get('object') or {}).get('name') or ''}"
    if ctype == "metric":
        return f"metric::{gate_id}::{(cand.get('metric') or {}).get('type')}"
    if ctype == "event":
        return f"event::{gate_id}::{(cand.get('event') or {}).get('name') or ''}"
    return f"statement::{gate_id}::" \
           f"{_norm_name((cand.get('statement') or {}).get('text') or '')}"


def _emit_knowledge_individual(
    db: DB, group_key: str, profile_id: str, layer: str, tenant_id: Any | None, member: dict,
) -> dict:
    """Emit a single conflict-flagged candidate (kept separate for manual review)."""
    return _emit_knowledge(db, group_key, profile_id, layer, tenant_id, [member])


def write_gate_entities(db: DB, entities: dict[str, dict]) -> int:
    for ent in entities.values():
        upsert_gate_entity(db, ent)
    return len(entities)


# ---------------------------------------------------------------------------
# Pipeline run 辅助
# ---------------------------------------------------------------------------

def run_fusion(
    db: DB,
    args,
    *,
    profile_id: str,
    layer: str,
    tenant_id: Any | None = None,
) -> dict[str, Any]:
    """Orchestrate fusion for a profile: load candidates, resolve entities, emit gates."""
    candidates = load_candidates(db, profile_id)
    if not candidates:
        return {"pipeline": "knowledge_fusion", "candidate_count": 0,
                "entity_count": 0, "emitted": 0, "fused": 0, "conflicted": 0}

    entities = resolve_entities(db, candidates, profile_id=profile_id, layer=layer,
                                tenant_id=tenant_id)
    ent_count = 0
    if not getattr(args, "dry_run", False):
        ent_count = write_gate_entities(db, entities)

    stats = group_and_emit(db, candidates, entities, profile_id=profile_id,
                           layer=layer, tenant_id=tenant_id,)

    print(f"[knowledge_fusion] {len(candidates)} candidates → {len(entities)} entities, "
          f"{stats['emitted']} gate knowledge (fused={stats['fused']}, "
          f"conflict_groups={stats['conflict_groups']})")
    return {
        "pipeline": "knowledge_fusion",
        "candidate_count": len(candidates),
        "entity_count": ent_count or len(entities),
        "emitted": stats["emitted"],
        "fused": stats["fused"],
        "conflicted": stats["conflicted"],
        "conflict_groups": stats["conflict_groups"],
        "dry_run": bool(getattr(args, "dry_run", False)),
    }


if __name__ == "__main__":
    print("fusion_service ok")