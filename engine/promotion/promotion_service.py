"""L1-gated promotion service: gate_candidate_knowledge → active graph.

Implement 方案 §10（门禁与晋级）的共享机械：读取 L1 promotion_policy 与 L1 ontology，
对门禁候选知识逐项做 schema / ontology / evidence / confidence / 冲突 / 去重 门禁，
命中则写入 active graph（entity / relation / statement / assertion + evidence），
否则进入 review_queue。L2 与 L3 各自的 ``promotion.py`` 只做薄编排，规则来源统一在 L1。
"""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any

from engine.core.db import DB
from engine.common.policy_engine import PromotionPolicy
from engine.common.registry import get_common_registry


DEFAULT_CONFIDENCE_THRESHOLD = 0.5
NEAR_DUPLICATE_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# 门禁求值
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _valid_entity_types(profile_id: str) -> set[str]:
    try:
        return get_common_registry().entity_types(profile_id, extractable_only=True)
    except Exception:  # noqa: BLE001 - degraded fallback
        return set()


def _valid_relation_types(profile_id: str) -> set[str]:
    try:
        return get_common_registry().relation_types(profile_id, extractable_only=True)
    except Exception:  # noqa: BLE001 - degraded fallback
        return set()


def _relation_domain_range(profile_id: str, relation: str) -> tuple[set[str], set[str]]:
    try:
        return get_common_registry().relation_domain_range(relation, profile_id)
    except Exception:  # noqa: BLE001
        return set(), set()


def _result(gate_id: str, passed: bool, detail: str, action: str = "pass") -> dict:
    return {"gate_id": gate_id, "passed": passed, "detail": detail, "action": action}


def _entity_type_of(db: DB, entity_id: str) -> str:
    rows = db.query(
        "SELECT entity_type FROM gate_candidate_entities WHERE entity_id = %s",
        (entity_id,),
    )
    return rows[0]["entity_type"] if rows else ""


def evaluate_instance(
    db: DB,
    k: dict,
    *,
    profile_id: str,
    policy: PromotionPolicy,
) -> list[dict]:
    """Run the L1 gates against one gate_candidate_knowledge row. Returns gate list."""
    registry = get_common_registry()
    results: list[dict] = []
    threshold = policy.confidence_threshold

    # gate_schema：候选须显式标记 schema_valid=True（抽取/融合时校验并落库，审查 High #7）。
    # 默认 False —— 未校验候选在门禁阶段被挡下，而不是静默通过。
    schema_ok = bool(k.get("schema_valid", False))
    results.append(_result("gate_schema", schema_ok, f"schema_valid={schema_ok}"))

    # gate_ontology：实体/关系类型必须属于 L1 ontology（§10.1）
    ent_ok = True
    ent_detail = "entities registered"
    valid_entities = _valid_entity_types(profile_id)
    valid_relations = _valid_relation_types(profile_id)
    subject_id = k.get("subject_entity_id")
    object_id = k.get("object_entity_id")
    predicate = k.get("predicate_type")
    ktype = k.get("knowledge_type")
    if subject_id:
        st = _entity_type_of(db, subject_id)
        if st and valid_entities and st not in valid_entities:
            ent_ok = False
            ent_detail = f"unknown entity type '{st}'"
    if object_id:
        ot = _entity_type_of(db, object_id)
        if ent_ok and ot and valid_entities and ot not in valid_entities:
            ent_ok = False
            ent_detail = f"unknown entity type '{ot}'"
    if (
        ent_ok
        and ktype == "relation"
        and predicate
        and subject_id
        and object_id
        and valid_relations
    ):
        if predicate not in valid_relations:
            ent_ok = False
            ent_detail = f"unknown relation type '{predicate}'"
        else:
            sub_types, obj_types = _relation_domain_range(profile_id, predicate)
            if sub_types or obj_types:
                st = _entity_type_of(db, subject_id)
                ot = _entity_type_of(db, object_id)
                if (sub_types and st not in sub_types) or (obj_types and ot not in obj_types):
                    ent_ok = False
                    ent_detail = f"domain/range violation: {st}->{ot} for {predicate}"
    results.append(_result("gate_ontology", ent_ok, ent_detail))

    # gate_evidence：evidence_refs 必须支持本候选（§10.1 evidence 直接支持）
    evidence_refs = _as_list(k.get("evidence_refs")) or []
    supported_ev = [
        ref
        for ref in evidence_refs
        if policy.evidence_ok(ref.get("access_status"), ref.get("support_status"))
    ]
    evidence_ok = bool(evidence_refs) and len(supported_ev) == len(evidence_refs)
    results.append(_result(
        "gate_evidence", evidence_ok,
        f"evidence={len(supported_ev)}/{len(evidence_refs)}",
    ))

    # gate_duplicate：与 active graph 中已晋级的陈述/关系做字符级去重
    dup = _existing_active_duplicate(db, k, ktype)
    dup_ok = dup is None
    results.append(_result(
        "gate_duplicate", dup_ok,
        "no duplicate" if dup is None else f"duplicate={dup['aggregate_id']}",
        "pass" if dup is None else "review",
    ))

    # gate_conflict：与 active graph 已存在的同主题 relation 冲突（one-to-one）
    conflict = _existing_conflict(db, k)
    results.append(_result(
        "gate_conflict", conflict is None,
        "no conflict" if conflict is None else f"conflict={conflict['id']}",
        "pass" if conflict is None else "review",
    ))

    # gate_confidence：confidence >= L1 阈值
    confidence = k.get("confidence")
    conf_ok = confidence is not None and float(confidence) >= threshold
    results.append(_result(
        "gate_confidence", conf_ok,
        f"confidence={confidence} threshold={threshold}",
        "pass" if conf_ok else "review",
    ))

    return results


def _existing_active_duplicate(db: DB, k: dict, ktype: str) -> dict | None:
    """Nearest active statement/relation text match in the active graph.
    Kept cheap and dependency-free (character-level), matching §12 NER 复用原则."""
    norm = " ".join((k.get("statement_text") or "").casefold().split()).strip()
    if not norm:
        return None
    subjects = db.query(
        "SELECT id, statement_id, statement_text FROM statement WHERE status='active' "
        "ORDER BY created_at DESC LIMIT 500"
    )
    for row in subjects:
        other = " ".join((row.get("statement_text") or "").casefold().split())
        if other and SequenceMatcher(None, norm, other).ratio() >= NEAR_DUPLICATE_THRESHOLD:
            return {"aggregate_type": "statement", "aggregate_id": row["statement_id"]}
    return None


def _existing_conflict(db: DB, k: dict) -> dict | None:
    if k.get("knowledge_type") != "relation":
        return None
    sub = k.get("subject_entity_id")
    obj = k.get("object_entity_id")
    pred = k.get("predicate_type")
    if not (sub and obj and pred):
        return None
    # entity_id in gate candidates vs entity.entity_id in active graph
    sub_uuid = _active_entity_uuid(db, sub)
    obj_uuid = _active_entity_uuid(db, obj)
    if not (sub_uuid and obj_uuid):
        return None
    rows = db.query(
        "SELECT id FROM relation WHERE status='active' AND subject_id=%s "
        "AND relation_type=%s AND object_id<>%s LIMIT 1",
        (sub_uuid, pred, obj_uuid),
    )
    return rows[0] if rows else None


def _active_entity_uuid(db: DB, gate_entity_id: str) -> Any | None:
    rows = db.query("SELECT id FROM entity WHERE entity_id=%s LIMIT 1", (gate_entity_id,))
    return rows[0]["id"] if rows else None


def disposition(results: list[dict]) -> tuple[str, dict | None]:
    """Map gate results to promote / review / reject."""
    failures = [r for r in results if not r["passed"]]
    if not failures:
        return "promote", None
    rejection = next((r for r in failures if r["action"] == "reject"), None)
    if rejection:
        return "reject", rejection
    rev = next((r for r in failures if r["action"] == "review"), None)
    return ("review", rev) if rev else ("reject", failures[0])


# ---------------------------------------------------------------------------
# 晋级写入 active graph
# ---------------------------------------------------------------------------

def _entity_pk(db: DB, entity_id: str) -> Any | None:
    rows = db.query("SELECT id FROM entity WHERE entity_id=%s", (entity_id,))
    return rows[0]["id"] if rows else None


def _ensure_evidence(
    db: DB, k: dict, *, tenant_id: Any | None
) -> dict[str, Any]:
    """Create/return evidence rows for each evidence_ref, keyed by evidence_id."""
    out: dict[str, Any] = {}
    for i, ref in enumerate(_as_list(k.get("evidence_refs")) or []):
        quote = ref.get("quote") or (k.get("evidence_text") or "")
        if not quote:
            continue
        existing = db.query(
            "SELECT id FROM evidence WHERE content_hash=%s AND quote=%s LIMIT 1",
            (k.get("content_hash"), quote),
        )
        if existing:
            out[ref.get("evidence_id") or f"ev_{i}"] = existing[0]
            continue
        vid = db.insert_returning_id(
            "INSERT INTO evidence (id, evidence_id, tenant_id, quote, content_hash, "
            " support_status, access_status) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                ref.get("evidence_id") or f"ev_{i}", tenant_id, quote,
                k.get("content_hash"),
                ref.get("support_status") or "partially_supports",
                ref.get("access_status") or "ok",
            ),
        )
        out[ref.get("evidence_id") or f"ev_{i}"] = vid
    return out


def promote(db: DB, k: dict, *, profile_id: str, tenant_id: Any | None = None) -> dict:
    """Write one gate knowledge row into the active graph and mark it passed."""
    ktype = k.get("knowledge_type")
    evidence_map = _ensure_evidence(db, k, tenant_id=tenant_id)

    if ktype == "relation":
        sub_pk = _entity_pk(db, k.get("subject_entity_id"))
        obj_pk = _entity_pk(db, k.get("object_entity_id"))
        if not (sub_pk and obj_pk):
            raise ValueError(
                f"relation endpoints missing in active graph: "
                f"{k.get('subject_entity_id')}->{k.get('object_entity_id')}"
            )
        rid = db.insert_returning_id(
            "INSERT INTO relation (id, subject_id, relation_type, object_id, tenant_id, "
            " scope, confidence, status) VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s::jsonb, %s, 'active') "
            "RETURNING id",
            (sub_pk, k.get("predicate_type"), obj_pk, tenant_id,
             json.dumps(k.get("scope") or {}, ensure_ascii=False), k.get("confidence")),
        )
        for evidence_id in evidence_map.values():
            db.execute(
                "INSERT INTO relation_evidence (relation_id, evidence_id, support_status) "
                "VALUES (%s, %s, 'supported')",
                (rid, evidence_id),
            )
    elif ktype == "statement":
        sub_pk = _entity_pk(db, k.get("subject_entity_id"))
        stmt = k.get("statement_text") or ""
        sid = db.insert_returning_id(
            "INSERT INTO statement (id, statement_id, tenant_id, subject_entity_id, "
            " predicate, statement_text, statement_class, scope, confidence, status) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'active') "
            "RETURNING id",
            (
                f"stmt_{stable_short(stmt)}", tenant_id, sub_pk,
                k.get("predicate_type"), stmt,
                k.get("statement_class") or "observation",
                json.dumps(k.get("scope") or {}, ensure_ascii=False), k.get("confidence"),
            ),
        )
        for evidence_id in evidence_map.values():
            db.execute(
                "INSERT INTO statement_evidence (statement_id, evidence_id, support_status) "
                "VALUES (%s, %s, 'supported')",
                (sid, evidence_id),
            )
    elif ktype == "metric":
        # 指标作为 active statement（带 metric_name/value）
        sub_pk = _entity_pk(db, k.get("subject_entity_id"))
        text = k.get("statement_text") or (
            f"{k.get('metric_name') or ''}: {k.get('metric_value') or ''}".strip()
        )
        sid = db.insert_returning_id(
            "INSERT INTO statement (id, statement_id, tenant_id, subject_entity_id, "
            " predicate, object_value, statement_text, statement_class, scope, confidence, status) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, 'has_metric', %s::jsonb, %s, %s, %s::jsonb, %s, 'active') "
            "RETURNING id",
            (
                f"stmt_{stable_short(text)}", tenant_id, sub_pk,
                json.dumps(k.get("metric_value") or {}, ensure_ascii=False),
                text, k.get("statement_class") or "observation",
                json.dumps(k.get("scope") or {}, ensure_ascii=False), k.get("confidence"),
            ),
        )
        for evidence_id in evidence_map.values():
            db.execute(
                "INSERT INTO statement_evidence (statement_id, evidence_id, support_status) "
                "VALUES (%s, %s, 'supported')",
                (sid, evidence_id),
            )
    elif ktype == "event":
        sub_pk = _entity_pk(db, k.get("subject_entity_id"))
        event = k.get("event") or {}
        text = k.get("statement_text") or str(event.get("name") or "event")
        sid = db.insert_returning_id(
            "INSERT INTO statement (id, statement_id, tenant_id, subject_entity_id, "
            " predicate, object_value, statement_text, statement_class, scope, confidence, status) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, 'has_event', %s::jsonb, %s, %s, %s::jsonb, %s, 'active') "
            "RETURNING id",
            (
                f"stmt_{stable_short(text)}", tenant_id, sub_pk,
                json.dumps(event, ensure_ascii=False), text,
                k.get("statement_class") or "observation",
                json.dumps(k.get("scope") or {}, ensure_ascii=False), k.get("confidence"),
            ),
        )
        for evidence_id in evidence_map.values():
            db.execute(
                "INSERT INTO statement_evidence (statement_id, evidence_id, support_status) "
                "VALUES (%s, %s, 'supported')",
                (sid, evidence_id),
            )

    db.execute(
        "UPDATE gate_candidate_knowledge SET gate_status='passed' WHERE knowledge_id=%s",
        (k.get("knowledge_id"),),
    )
    return {"knowledge_id": k.get("knowledge_id"), "action": "promote", "type": ktype}


def stable_short(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def queue_review(db: DB, k: dict, reason: str) -> None:
    """Move a gate candidate to review (enqueue review_queue; keep pending gating).

    ``review_queue.target_id`` is UUID-typed, so derive a stable UUID from the
    varchar ``knowledge_id`` (uuid5), enabling the unique pending enqueue guard.
    """
    import uuid

    stable_uuid = uuid.uuid5(uuid.NAMESPACE_URL,
                             f"brand-atlas:gate:{k.get('knowledge_id')}")
    db.execute(
        "INSERT INTO review_queue (target_type, target_id, tenant_id, review_type, "
        " priority, reason, status) "
        "VALUES ('gate_candidate_knowledge', %s, %s, 'promotion_review', 8, %s, 'pending') "
        "ON CONFLICT (target_type, target_id, review_type) WHERE status='pending' "
        "DO UPDATE SET reason=EXCLUDED.reason, priority=EXCLUDED.priority",
        (stable_uuid, k.get("tenant_id"), reason),
    )


if __name__ == "__main__":
    print("promotion_service ok")