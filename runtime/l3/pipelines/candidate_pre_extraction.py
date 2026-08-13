"""L3 pipeline: Candidate Pre-Extraction (rules + dictionary).

Per OPTIMIZATION_TECH_PLAN.md §4.2, this inserts a rule/dictionary/small-model
layer BEFORE the LLM candidate_extraction step. It deterministically extracts
simple facts (URLs, dates, versions, prices, certifications, organizations,
products, capabilities) using regex + dictionary matching, so the LLM only
handles hard cases.

Writes to the `extraction_candidate` table (see runtime/migrations/vector_migration.sql).
"""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

import yaml

from runtime.db import DB
from runtime.l3.pipelines._helpers import resolve_brand_context

ROOT = Path(__file__).resolve().parents[3]  # Knowledge_Graph root
RULES_DIR = ROOT / "brand_knowledge" / "rules"
DICT_DIR = ROOT / "brand_knowledge" / "dictionaries"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _regex_entities(text: str, rules: dict) -> list[dict]:
    """Apply entity/phone/url/version/price regex rules."""
    candidates = []
    for pat in rules.get("entity_patterns", []):
        try:
            rx = re.compile(pat["regex"])
        except re.error:
            continue
        for m in rx.finditer(text):
            candidates.append({
                "candidate_type": pat.get("type", "entity"),
                "candidate_payload": {"value": m.group(0), "regex": pat.get("note", "")},
                "confidence": 0.9,
                "generator": f"regex:{pat.get('type', 'entity')}",
            })
    return candidates


def _metric_entities(text: str, rules: dict) -> list[dict]:
    candidates = []
    for pat in rules.get("metric_patterns", []):
        try:
            rx = re.compile(pat["regex"])
        except re.error:
            continue
        for m in rx.finditer(text):
            candidates.append({
                "candidate_type": "metric",
                "candidate_payload": {"metric": pat.get("type"), "value": m.group(0)},
                "confidence": 0.85,
                "generator": f"regex:{pat.get('type')}",
            })
    return candidates


def _certification_entities(text: str, rules: dict, dicts: dict) -> list[dict]:
    candidates = []
    for pat in rules.get("certification_patterns", []):
        try:
            rx = re.compile(pat["regex"])
        except re.error:
            continue
        for m in rx.finditer(text):
            candidates.append({
                "candidate_type": "certification",
                "candidate_payload": {"name": m.group(0)},
                "confidence": 0.9,
                "generator": f"regex:{pat.get('type')}",
            })
    # Dictionary lookup
    for term in dicts.get("certification_terms", {}).get("terms", []):
        if term in text:
            candidates.append({
                "candidate_type": "certification",
                "candidate_payload": {"name": term},
                "confidence": 0.95,
                "generator": "dictionary:certification_terms",
            })
    return candidates


def _organization_entities(text: str, dicts: dict) -> list[dict]:
    candidates = []
    zh = dicts.get("organization_suffixes", {}).get("zh_pattern")
    en = dicts.get("organization_suffixes", {}).get("en_pattern")
    for pat in (zh, en):
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error:
            continue
        for m in rx.finditer(text):
            candidates.append({
                "candidate_type": "organization",
                "candidate_payload": {"name": m.group(0)},
                "confidence": 0.8,
                "generator": "dictionary:organization_suffixes",
            })
    return candidates


def _product_entities(text: str, dicts: dict) -> list[dict]:
    candidates = []
    pat = dicts.get("product_terms", {}).get("product_pattern")
    if pat:
        try:
            rx = re.compile(pat)
        except re.error:
            pass
        else:
            for m in rx.finditer(text):
                candidates.append({
                    "candidate_type": "product",
                    "candidate_payload": {"name": m.group(0)},
                    "confidence": 0.7,
                    "generator": "dictionary:product_terms",
                })
    return candidates


def _capability_entities(text: str, dicts: dict) -> list[dict]:
    candidates = []
    for term in dicts.get("capability_terms", {}).get("terms", []):
        if term in text:
            candidates.append({
                "candidate_type": "capability",
                "candidate_payload": {"name": term},
                "confidence": 0.9,
                "generator": "dictionary:capability_terms",
            })
    return candidates


def pre_extract(text: str) -> list[dict]:
    """Run all rule + dictionary extractors over a text chunk."""
    rules = {
        "entity_patterns": _load_yaml(RULES_DIR / "entity_patterns.yaml").get("entity_patterns", []),
        "metric_patterns": _load_yaml(RULES_DIR / "metric_patterns.yaml").get("metric_patterns", []),
        "certification_patterns": _load_yaml(RULES_DIR / "certification_patterns.yaml").get("certification_patterns", []),
    }
    dicts = {
        "organization_suffixes": _load_yaml(DICT_DIR / "organization_suffixes.yaml"),
        "product_terms": _load_yaml(DICT_DIR / "product_terms.yaml"),
        "capability_terms": _load_yaml(DICT_DIR / "capability_terms.yaml"),
        "certification_terms": _load_yaml(DICT_DIR / "certification_terms.yaml"),
    }
    all_candidates = []
    all_candidates += _regex_entities(text, rules)
    all_candidates += _metric_entities(text, rules)
    all_candidates += _certification_entities(text, rules, dicts)
    all_candidates += _organization_entities(text, dicts)
    all_candidates += _product_entities(text, dicts)
    all_candidates += _capability_entities(text, dicts)
    return all_candidates


def run(db: DB, args) -> dict[str, Any]:
    """Pre-extract candidates for a document's evidence spans into extraction_candidate."""
    document_id_str = getattr(args, "document_id", None)
    if not document_id_str:
        raise ValueError("--document-id required for candidate_pre_extraction")

    # Resolve brand context (tenant_id / brand_id as UUIDs) for RLS + FK writes.
    ctx = resolve_brand_context(db, args)
    tenant_id, brand_id = ctx["tenant_id"], ctx["brand_id"]

    # Resolve the string document_id to its UUID (document_id is a UUID FK).
    doc_rows = db.query("SELECT id FROM document WHERE document_id = %s LIMIT 1", (document_id_str,))
    if not doc_rows:
        raise ValueError(f"document not found: {document_id_str}. Run source_registration first.")
    document_uuid = doc_rows[0]["id"]

    chunks = db.query(
        "SELECT id, chunk_index, text FROM document_chunk "
        "WHERE document_id = %s AND chunk_type = 'evidence_span' ORDER BY chunk_index",
        (document_uuid,),
    )
    if not chunks:
        print(f"[candidate_pre_extraction] no evidence spans for {document_id_str}")
        return {**ctx, "pipeline": "candidate_pre_extraction", "document_id": document_id_str,
                "candidate_count": 0}

    total = 0
    for chunk in chunks:
        candidates = pre_extract(chunk["text"] or "")
        if not candidates:
            continue
        for c in candidates:
            if getattr(args, "dry_run", False):
                total += 1
                continue
            # candidate_payload is JSONB; serialize dict to JSON string.
            payload_json = json.dumps(c["candidate_payload"], ensure_ascii=False)
            db.execute(
                "INSERT INTO extraction_candidate "
                "(tenant_id, brand_id, document_id, chunk_id, candidate_type, "
                "candidate_payload, generator, confidence, status) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'candidate') "
                "ON CONFLICT DO NOTHING",
                (tenant_id, brand_id, document_uuid, chunk["id"],
                 c["candidate_type"], payload_json, c["generator"], c["confidence"]),
            )
            total += 1

    print(f"[candidate_pre_extraction] {total} candidates from {len(chunks)} spans")
    return {**ctx, "pipeline": "candidate_pre_extraction", "document_id": document_id_str,
            "span_count": len(chunks), "candidate_count": total,
            "dry_run": bool(getattr(args, "dry_run", False))}


if __name__ == "__main__":
    import json
    import sys

    sample = (
        "DeepCleer 深澈智算（上海智算云图科技有限公司）提供 AI 业财财报平台，"
        "支持多法人合并核算、自动对账，获得 ISO 27001 认证和等保三级资质，"
        "官网 https://www.deepcleer.ai，联系方式 400-123-8888，版本 V2.1。"
    )
    print(json.dumps(pre_extract(sample), ensure_ascii=False, indent=1))