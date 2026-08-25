"""L2 pipeline: first-pass enrichment from report-cited source full text.

This step runs after the report has formed a seed skeleton (`report_candidate`
+ extraction) and before promotion. It does not run a second web crawl. Instead
it uses only the full text already referenced by report citations (`[S#]`) to:

1. ask the LLM which skeleton facts need more detail,
2. locate precise source spans from the cited full text,
3. extract supplemental candidate statements,
4. run a light graph validation, and
5. write accepted candidates with evidence lineage for later promotion.

The final active/inactive decision still belongs to `promotion`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from runtime.db import DB
from runtime.extract import extract_entities_relations, extract_json, load_llm
from runtime.industry.pipelines.extraction import (
    DEFAULT_PROFILE_ID,
    _add_entity_candidate,
    _entity_uuid,
    _link_relation_evidence,
    _link_statement_evidence_uuid,
    _upsert_entity,
    _valid_relation_types,
)
from runtime.industry.pipelines.report_ingestion import _statement_hash


SUPPLEMENTAL_TYPE = "source_enrichment"
SPAN_SENTENCE_MAX = 5
MAX_SOURCE_CHARS = 120_000


def _load_evidence_index(path: str) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict) and "sources" in payload:
        return {
            (row.get("label") or row.get("citation_label")): row
            for row in payload["sources"]
            if row.get("label") or row.get("citation_label")
        }
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Unrecognized evidence index format in {path}")


def _report_uuid_and_industry(db: DB, report_id: str) -> tuple[str, str | None]:
    rows = db.query(
        "SELECT rr.id, ir.industry_id FROM research_report rr "
        "LEFT JOIN industry_requirement ir ON ir.id = rr.requirement_id "
        "WHERE rr.report_id = %s LIMIT 1",
        (report_id,),
    )
    if not rows:
        raise ValueError(f"research_report not found: {report_id}")
    return rows[0]["id"], rows[0].get("industry_id")


def _seed_candidates(db: DB, report_id: str, limit: int) -> list[dict]:
    return db.query(
        "SELECT rc.id, rc.statement, rc.citation_labels, rc.candidate_type, "
        "rc.confidence, rc.section_code "
        "FROM report_candidate rc JOIN research_report rr ON rr.id = rc.report_id "
        "WHERE rr.report_id = %s AND rc.status IN ('candidate','promoted') "
        "AND COALESCE(rc.knowledge_candidate_type, '') <> %s "
        "ORDER BY rc.confidence DESC NULLS LAST, rc.created_at ASC LIMIT %s",
        (report_id, SUPPLEMENTAL_TYPE, limit),
    )


def _plan_enrichment(client, seeds: list[dict]) -> list[dict]:
    compact = []
    for row in seeds:
        labels = row.get("citation_labels") or []
        if isinstance(labels, str):
            labels = json.loads(labels)
        if not labels:
            continue
        compact.append(
            {
                "candidate_id": str(row["id"]),
                "statement": row["statement"],
                "citations": labels[:5],
            }
        )
    if not compact:
        return []

    system = (
        "你是行业知识图谱的补充规划器。基于报告骨架候选，判断哪些候选需要从其已引用的"
        "信源全文补充细节。只规划可由引用来源补充的内容，不要提出二次爬虫需求。输出 JSON："
        "{\"items\":[{\"candidate_id\":\"...\",\"citation_label\":\"S1\","
        "\"focus\":\"需要补充的细节维度\",\"why\":\"原因\"}]}。"
        "focus 优先覆盖数值、时间、地区、厂商、产品、技术、供应链、竞争格局、风险。"
    )
    user = json.dumps({"seed_candidates": compact}, ensure_ascii=False)
    try:
        payload = extract_json(client, system, user, max_tokens=1400)
    except Exception:
        return _fallback_plan(compact)
    items = payload.get("items") or []
    cleaned = []
    known_ids = {row["candidate_id"] for row in compact}
    for item in items:
        cid = str(item.get("candidate_id") or "")
        label = str(item.get("citation_label") or "")
        if cid in known_ids and re.fullmatch(r"S\d+", label):
            cleaned.append(
                {
                    "candidate_id": cid,
                    "citation_label": label,
                    "focus": str(item.get("focus") or "补充事实细节"),
                    "why": str(item.get("why") or ""),
                }
            )
    return cleaned or _fallback_plan(compact)


def _fallback_plan(compact: list[dict]) -> list[dict]:
    items = []
    for row in compact:
        for label in row.get("citations") or []:
            items.append(
                {
                    "candidate_id": row["candidate_id"],
                    "citation_label": label,
                    "focus": "补充与该骨架陈述直接相关的事实、数值、时间、主体和条件",
                    "why": "fallback from cited source",
                }
            )
    return items


def _source_text(entry: dict, evidence_path: str) -> tuple[str, str | None]:
    content_path = entry.get("content_path")
    if content_path:
        candidates = _resolve_content_paths(content_path, evidence_path)
        for path in candidates:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")[:MAX_SOURCE_CHARS], str(path)

    for key in ("text", "content", "html_text", "evidence_text", "quote", "snippet"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:MAX_SOURCE_CHARS], entry.get("content_path")
    return "", content_path


def _resolve_content_paths(content_path: str, evidence_path: str) -> list[Path]:
    raw = Path(content_path)
    if raw.is_absolute():
        return [raw]
    evidence_dir = Path(evidence_path).resolve().parent
    cwd = Path.cwd().resolve()
    roots = [evidence_dir, cwd, cwd.parent, Path("D:/Brand Atlas/geo-research").resolve()]
    return [root / raw for root in roots]


def _split_spans(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.replace("\r", "\n")).strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?;；.])\s+", text) if p.strip()]
    if not parts:
        parts = [text]
    spans = []
    current: list[str] = []
    for sentence in parts:
        current.append(sentence)
        if len(current) >= SPAN_SENTENCE_MAX:
            spans.append(" ".join(current))
            current = []
    if current:
        spans.append(" ".join(current))
    return [span for span in spans if len(span) >= 40]


def _terms(text: str) -> set[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", text.casefold())
    return {t for t in tokens if len(t) >= 2}


def _rank_spans(source_text: str, seed_statement: str, focus: str, limit: int) -> list[str]:
    query_terms = _terms(seed_statement + " " + focus)
    scored = []
    for span in _split_spans(source_text):
        st = _terms(span)
        overlap = len(query_terms & st)
        numerics = len(re.findall(r"\d+(?:\.\d+)?%?|\d{4}", span))
        score = overlap + min(numerics, 5) * 0.8
        if score > 0:
            scored.append((score, span))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [span for _, span in scored[: max(limit * 4, limit)]]


def _extract_supplements(client, seed_statement: str, focus: str, spans: list[str], max_items: int) -> list[dict]:
    if not spans:
        return []
    system = (
        "你是行业知识图谱补充抽取器。只从给定 source_spans 中抽取可直接由原文支持、"
        "且能补充 seed_statement 的事实陈述。不要复述 seed_statement 本身。"
        "每条 statement 必须有原文 evidence_quote，quote 必须逐字来自 source_spans。"
        "输出 JSON：{\"items\":[{\"statement\":\"...\",\"statement_class\":\"fact|claim|observation|inference\","
        "\"evidence_quote\":\"...\",\"relevant_to_skeleton\":true,\"confidence\":0.0}]}"
    )
    user = json.dumps(
        {
            "seed_statement": seed_statement,
            "focus": focus,
            "source_spans": spans,
            "max_items": max_items,
        },
        ensure_ascii=False,
    )
    try:
        payload = extract_json(client, system, user, max_tokens=1800)
    except Exception:
        return []
    items = []
    for item in payload.get("items") or []:
        statement = str(item.get("statement") or "").strip()
        quote = str(item.get("evidence_quote") or "").strip()
        klass = item.get("statement_class") or "observation"
        if klass not in ("fact", "claim", "observation", "inference"):
            klass = "observation"
        try:
            confidence = float(item.get("confidence") or 0.6)
        except (TypeError, ValueError):
            confidence = 0.6
        if statement and quote and item.get("relevant_to_skeleton") is not False:
            items.append(
                {
                    "statement": statement,
                    "statement_class": klass,
                    "evidence_quote": quote,
                    "confidence": max(0.0, min(confidence, 0.95)),
                }
            )
    return items[:max_items]


def _ensure_source(db: DB, entry: dict, dry_run: bool) -> str | None:
    source_id = entry.get("source_id")
    if not source_id:
        source_id = _source_id_from_url(entry.get("url") or entry.get("canonical_url") or "")
        if not source_id:
            return None
    rows = db.query("SELECT id FROM source_instance WHERE source_id = %s LIMIT 1", (source_id,))
    if rows:
        return rows[0]["id"]
    if dry_run:
        return f"dry:{source_id}"
    db.upsert(
        "source_instance",
        {
            "source_id": source_id,
            "industry_id": entry.get("industry_id"),
            "source_class": entry.get("source_class") or "industry_research",
            "source_type": entry.get("source_type") or "official",
            "publisher": entry.get("publisher") or entry.get("source"),
            "title": entry.get("title") or source_id,
            "canonical_url": entry.get("url") or entry.get("canonical_url"),
            "access_level": entry.get("access_level") or "public",
            "approval_status": entry.get("approval_status") or "pending",
            "l2_enabled": bool(entry.get("l2_enabled", False)),
            "status": "registered",
        },
        key_field="source_id",
    )
    rows = db.query("SELECT id FROM source_instance WHERE source_id = %s LIMIT 1", (source_id,))
    return rows[0]["id"] if rows else None


def _source_id_from_url(url: str) -> str | None:
    if not url:
        return None
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def _ensure_evidence(db: DB, entry: dict, source_uuid: str | None, quote: str, dry_run: bool) -> str | None:
    evidence_id = entry.get("evidence_id")
    if evidence_id:
        evidence_id = f"{evidence_id}_enrich_{hashlib.sha256(quote.encode('utf-8')).hexdigest()[:10]}"
    else:
        evidence_id = f"ev_enrich_{hashlib.sha256(((entry.get('url') or '') + quote).encode('utf-8')).hexdigest()[:24]}"
    rows = db.query("SELECT id FROM evidence WHERE evidence_id = %s LIMIT 1", (evidence_id,))
    if rows:
        return rows[0]["id"]
    if dry_run:
        return f"dry:{evidence_id}"
    db.upsert(
        "evidence",
        {
            "evidence_id": evidence_id,
            "source_id": None if source_uuid and str(source_uuid).startswith("dry:") else source_uuid,
            "content_path": entry.get("content_path"),
            "page_ref": entry.get("page_ref"),
            "quote": quote,
            "content_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "access_level": entry.get("access_level") or "public",
            "support_status": "directly_supports",
        },
        key_field="evidence_id",
    )
    rows = db.query("SELECT id FROM evidence WHERE evidence_id = %s LIMIT 1", (evidence_id,))
    return rows[0]["id"] if rows else None


def _light_validate(
    db: DB,
    client,
    *,
    report_uuid: str,
    industry_id: str | None,
    source_uuid: str | None,
    source_text: str,
    seed_statement: str,
    statement: str,
    quote: str,
) -> tuple[bool, dict]:
    checks = {
        "source_recognizable": bool(source_uuid),
        "chunk_relevant_to_skeleton": _relevant(seed_statement, quote),
        "statement_has_evidence_span": _quote_in_text(quote, source_text),
        "not_duplicate": not _is_duplicate(db, report_uuid, industry_id, statement),
        "no_active_or_candidate_conflict": not _has_conflict(db, client, industry_id, statement),
    }
    return all(checks.values()), checks


def _quote_in_text(quote: str, source_text: str) -> bool:
    if not quote or not source_text:
        return False
    if quote in source_text:
        return True
    compact_quote = re.sub(r"\s+", "", quote)
    compact_source = re.sub(r"\s+", "", source_text)
    return bool(compact_quote and compact_quote in compact_source)


def _relevant(seed_statement: str, quote: str) -> bool:
    seed_terms = _terms(seed_statement)
    quote_terms = _terms(quote)
    return bool(seed_terms & quote_terms) or SequenceMatcher(None, seed_statement, quote).ratio() >= 0.25


def _is_duplicate(db: DB, report_uuid: str, industry_id: str | None, statement: str) -> bool:
    h = _statement_hash(statement)
    rows = db.query(
        "SELECT 1 FROM report_candidate WHERE report_id = %s "
        "AND normalized_statement_hash = %s LIMIT 1",
        (report_uuid, h),
    )
    if rows:
        return True
    existing = db.query(
        "SELECT rc.statement FROM report_candidate rc "
        "JOIN research_report rr ON rr.id = rc.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id = rr.requirement_id "
        "WHERE rc.status IN ('candidate','promoted') "
        "AND (%s IS NULL OR ir.industry_id = %s) "
        "ORDER BY rc.updated_at DESC LIMIT 300",
        (industry_id, industry_id),
    )
    normalized = " ".join(statement.casefold().split())
    for row in existing:
        other = " ".join((row.get("statement") or "").casefold().split())
        if normalized and other and SequenceMatcher(None, normalized, other).ratio() >= 0.9:
            return True
    return False


def _has_conflict(db: DB, client, industry_id: str | None, statement: str) -> bool:
    rows = db.query(
        "SELECT statement_text FROM statement "
        "WHERE status IN ('candidate','active') "
        "AND (%s IS NULL OR scope->>'industry_id' = %s) "
        "ORDER BY updated_at DESC LIMIT 80",
        (industry_id, industry_id),
    )
    if not rows:
        return False
    context = [row["statement_text"] for row in rows if row.get("statement_text")]
    system = (
        "你是行业知识图谱轻量冲突检查器。判断 new_statement 是否与 existing_statements "
        "存在明确事实冲突。只有数值、时间、主体、方向、归属明显相反才算冲突。"
        "输出 JSON：{\"conflict\":true|false,\"reason\":\"...\"}"
    )
    try:
        payload = extract_json(
            client,
            system,
            json.dumps({"new_statement": statement, "existing_statements": context}, ensure_ascii=False),
            max_tokens=500,
        )
    except Exception:
        return False
    return bool(payload.get("conflict"))


def _insert_candidate(
    db: DB,
    *,
    report_uuid: str,
    seed_candidate_id: str,
    label: str,
    statement: str,
    statement_class: str,
    confidence: float,
    checks: dict,
    dry_run: bool,
) -> str | None:
    if dry_run:
        return f"dry-candidate-{hashlib.sha256(statement.encode('utf-8')).hexdigest()[:10]}"
    return db.insert_returning_id(
        "INSERT INTO report_candidate (report_id, report_span, statement, candidate_type, "
        "citation_labels, normalized_statement_hash, knowledge_candidate_type, confidence, "
        "promotion_gate_results, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'candidate') "
        "ON CONFLICT (report_id, normalized_statement_hash) "
        "WHERE normalized_statement_hash IS NOT NULL DO UPDATE SET "
        "report_span=EXCLUDED.report_span, candidate_type=EXCLUDED.candidate_type, "
        "citation_labels=EXCLUDED.citation_labels, knowledge_candidate_type=EXCLUDED.knowledge_candidate_type, "
        "confidence=GREATEST(COALESCE(report_candidate.confidence, 0), EXCLUDED.confidence), "
        "promotion_gate_results=EXCLUDED.promotion_gate_results "
        "RETURNING id",
        (
            report_uuid,
            f"source_enrichment:{label}:seed={seed_candidate_id}",
            statement,
            statement_class,
            db._json([label]),
            _statement_hash(statement),
            SUPPLEMENTAL_TYPE,
            confidence,
            db._json({"light_graph_validation": checks}),
        ),
    )


def _insert_citation_resolution(
    db: DB,
    *,
    candidate_uuid: str,
    label: str,
    entry: dict,
    source_uuid: str | None,
    evidence_uuid: str | None,
    dry_run: bool,
) -> None:
    if dry_run or str(candidate_uuid).startswith("dry"):
        return
    db.execute(
        "INSERT INTO citation_resolution (report_candidate_id, citation_label, source_id, "
        "evidence_id, original_url, access_status, evidence_location, support_status, "
        "support_reason, verifier_version) VALUES (%s, %s, %s, %s, %s, 'crawled', %s, "
        "'directly_supports', %s, 'l2-source-enrichment-1.0.0') "
        "ON CONFLICT (report_candidate_id, citation_label) DO UPDATE SET "
        "source_id=EXCLUDED.source_id, evidence_id=EXCLUDED.evidence_id, "
        "original_url=EXCLUDED.original_url, access_status=EXCLUDED.access_status, "
        "evidence_location=EXCLUDED.evidence_location, support_status=EXCLUDED.support_status, "
        "support_reason=EXCLUDED.support_reason, verifier_version=EXCLUDED.verifier_version",
        (
            candidate_uuid,
            label,
            None if source_uuid and str(source_uuid).startswith("dry:") else source_uuid,
            None if evidence_uuid and str(evidence_uuid).startswith("dry:") else evidence_uuid,
            entry.get("url") or entry.get("canonical_url"),
            entry.get("page_ref") or entry.get("content_path"),
            "supplemental statement extracted from report-cited source full text",
        ),
    )


def _extract_candidate_knowledge(
    db: DB,
    client,
    *,
    report_id: str,
    candidate_uuid: str,
    statement: str,
    statement_class: str,
    confidence: float,
    industry_id: str | None,
    dry_run: bool,
) -> dict:
    stats = {"entities": 0, "relations": 0, "statements": 0}
    if str(candidate_uuid).startswith("dry"):
        print(f"  [dry] supplemental candidate {candidate_uuid}: {statement}")
        return stats

    existing_ids: set[str] = set()
    entity_registry: dict[tuple[str, str], str] = {}
    entity_map: dict[str, str] = {}
    result = extract_entities_relations(client, statement, profile_id=DEFAULT_PROFILE_ID)

    for ent in result.get("entities") or []:
        entity_id = _upsert_entity(
            db, ent, existing_ids, entity_registry, candidate_uuid, industry_id, dry_run,
            profile_id=DEFAULT_PROFILE_ID,
        )
        if entity_id:
            ext_id = ent.get("id") or entity_id
            entity_map[ext_id] = entity_id
            entity_map[entity_id] = entity_id
            _add_entity_candidate(db, entity_id, str(candidate_uuid))
            stats["entities"] += 1

    statements = result.get("statements") or [{"text": statement, "statement_class": statement_class}]
    for item in statements:
        text = item.get("text") or item.get("statement_text") or statement
        klass = item.get("statement_class") or statement_class
        if klass not in ("fact", "claim", "observation", "inference"):
            klass = statement_class
        statement_uuid = db.insert_returning_id(
            "INSERT INTO statement (statement_id, statement_text, statement_class, object_value, "
            "confidence, scope, status) VALUES (%s, %s, %s, %s, %s, %s, 'candidate') "
            "ON CONFLICT ((scope->>'report_candidate_id'), statement_text) "
            "WHERE scope->>'report_candidate_id' IS NOT NULL DO UPDATE SET "
            "statement_class=EXCLUDED.statement_class, object_value=EXCLUDED.object_value, "
            "confidence=EXCLUDED.confidence RETURNING id",
            (
                f"st_enrich_{hashlib.sha256((str(candidate_uuid) + text).encode('utf-8')).hexdigest()[:24]}",
                text,
                klass,
                db._json({"statement": text}),
                confidence,
                db._json(
                    {
                        "report_id": report_id,
                        "report_candidate_id": str(candidate_uuid),
                        "industry_id": industry_id,
                        "knowledge_candidate_type": SUPPLEMENTAL_TYPE,
                    }
                ),
            ),
        )
        _link_statement_evidence_uuid(db, statement_uuid, str(candidate_uuid))
        stats["statements"] += 1

    for rel in result.get("relations") or []:
        rel_type = rel.get("relation")
        if rel_type not in _valid_relation_types(DEFAULT_PROFILE_ID):
            continue
        subj_id = entity_map.get(rel.get("subject"))
        obj_id = entity_map.get(rel.get("object"))
        subj_uuid = _entity_uuid(db, subj_id) if subj_id else None
        obj_uuid = _entity_uuid(db, obj_id) if obj_id else None
        if not subj_uuid or not obj_uuid:
            continue
        relation_uuid = db.insert_returning_id(
            "INSERT INTO relation (subject_id, relation_type, object_id, confidence, status, scope) "
            "VALUES (%s, %s, %s, %s, 'candidate', %s) "
            "ON CONFLICT (subject_id, relation_type, object_id, (scope->>'report_candidate_id')) "
            "WHERE scope->>'report_candidate_id' IS NOT NULL DO UPDATE SET "
            "confidence=EXCLUDED.confidence RETURNING id",
            (
                subj_uuid,
                rel_type,
                obj_uuid,
                rel.get("confidence"),
                db._json(
                    {
                        "report_id": report_id,
                        "report_candidate_id": str(candidate_uuid),
                        "industry_id": industry_id,
                        "knowledge_candidate_type": SUPPLEMENTAL_TYPE,
                    }
                ),
            ),
        )
        _link_relation_evidence(db, relation_uuid, str(candidate_uuid))
        stats["relations"] += 1

    db.execute(
        "UPDATE report_candidate SET candidate_type=%s, confidence=%s WHERE id=%s",
        (statement_class, confidence, candidate_uuid),
    )
    return stats


def run(db: DB, args) -> dict[str, Any]:
    report_id = getattr(args, "report_id", None)
    evidence_path = getattr(args, "evidence", None) or os.environ.get("GEO_RESEARCH_EVIDENCE_PATH")
    if not report_id:
        raise ValueError("source_enrichment requires --report-id")
    if not evidence_path or not os.path.exists(evidence_path):
        raise FileNotFoundError(f"Evidence index not found: {evidence_path}")

    dry_run = bool(getattr(args, "dry_run", False))
    max_candidates = int(getattr(args, "enrichment_max_candidates", 40) or 40)
    max_spans = int(getattr(args, "enrichment_max_spans_per_source", 3) or 3)
    report_uuid, industry_id = _report_uuid_and_industry(db, report_id)
    seeds = _seed_candidates(db, report_id, max_candidates)
    if not seeds:
        print("[source_enrichment] no seed report candidates; skipped")
        return {"pipeline": "source_enrichment", "report_id": report_id, "skipped": True}

    client = load_llm()
    index = _load_evidence_index(evidence_path)
    plan = _plan_enrichment(client, seeds)
    seed_by_id = {str(seed["id"]): seed for seed in seeds}
    stats = {
        "planned": len(plan),
        "sources_read": 0,
        "spans_considered": 0,
        "accepted": 0,
        "rejected_light_check": 0,
        "entities": 0,
        "relations": 0,
        "statements": 0,
    }

    seen_source_labels: set[str] = set()
    for item in plan:
        seed = seed_by_id.get(item["candidate_id"])
        entry = index.get(item["citation_label"])
        if not seed or not entry:
            continue

        source_text, resolved_path = _source_text(entry, evidence_path)
        if not source_text:
            continue
        if item["citation_label"] not in seen_source_labels:
            stats["sources_read"] += 1
            seen_source_labels.add(item["citation_label"])
        if resolved_path and not entry.get("content_path"):
            entry["content_path"] = resolved_path

        spans = _rank_spans(source_text, seed["statement"], item["focus"], max_spans)
        stats["spans_considered"] += len(spans)
        supplements = _extract_supplements(
            client, seed["statement"], item["focus"], spans, max_spans
        )
        source_uuid = _ensure_source(db, entry, dry_run)
        for supplement in supplements:
            quote = supplement["evidence_quote"]
            ok, checks = _light_validate(
                db,
                client,
                report_uuid=report_uuid,
                industry_id=industry_id,
                source_uuid=source_uuid,
                source_text=source_text,
                seed_statement=seed["statement"],
                statement=supplement["statement"],
                quote=quote,
            )
            if not ok:
                stats["rejected_light_check"] += 1
                continue

            evidence_uuid = _ensure_evidence(db, entry, source_uuid, quote, dry_run)
            candidate_uuid = _insert_candidate(
                db,
                report_uuid=report_uuid,
                seed_candidate_id=str(seed["id"]),
                label=item["citation_label"],
                statement=supplement["statement"],
                statement_class=supplement["statement_class"],
                confidence=supplement["confidence"],
                checks=checks,
                dry_run=dry_run,
            )
            if not candidate_uuid:
                continue
            _insert_citation_resolution(
                db,
                candidate_uuid=str(candidate_uuid),
                label=item["citation_label"],
                entry=entry,
                source_uuid=source_uuid,
                evidence_uuid=evidence_uuid,
                dry_run=dry_run,
            )
            extracted = _extract_candidate_knowledge(
                db,
                client,
                report_id=report_id,
                candidate_uuid=str(candidate_uuid),
                statement=supplement["statement"],
                statement_class=supplement["statement_class"],
                confidence=supplement["confidence"],
                industry_id=industry_id,
                dry_run=dry_run,
            )
            stats["accepted"] += 1
            stats["entities"] += extracted["entities"]
            stats["relations"] += extracted["relations"]
            stats["statements"] += extracted["statements"]

    print(f"[source_enrichment] {json.dumps(stats, ensure_ascii=False)}")
    return {
        "pipeline": "source_enrichment",
        "report_id": report_id,
        "evidence_index": evidence_path,
        "dry_run": dry_run,
        "stats": stats,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 cited-source enrichment pipeline")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--enrichment-max-candidates", type=int, default=40)
    parser.add_argument("--enrichment-max-spans-per-source", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    namespace = parser.parse_args()
    with DB.from_env() as database:
        print(json.dumps(run(database, namespace), ensure_ascii=False, indent=2))
