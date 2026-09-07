"""Persistence adapters for the legacy PostgreSQL extraction pipelines.

The parsing and candidate construction functions live in ``shared``.  This
module is deliberately kept in ``legacy`` because it knows about the old
PostgreSQL knowledge service and must not be imported by the desktop runtime.
"""
from __future__ import annotations

from typing import Any

from shared.extraction.candidate_extraction import build_candidate_rows, pre_extract
from legacy.core.knowledge_service import (
    upsert_evidence_span,
    upsert_evidence_unit,
    upsert_knowledge_candidate,
)


def write_spans(db, document_uuid: Any, span_rows: list[dict]) -> int:
    for span in span_rows:
        row = dict(span)
        row["document_uuid"] = document_uuid
        upsert_evidence_span(db, row)
    return len(span_rows)


def write_units(db, document_uuid: Any, unit_rows: list[dict]) -> int:
    for unit in unit_rows:
        row = dict(unit)
        row["document_uuid"] = document_uuid
        upsert_evidence_unit(db, row)
    return len(unit_rows)


def extract_and_store(
    db,
    context: dict,
    units: list[dict],
    *,
    ner_client=None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run shared extraction and persist rows through the legacy DB service."""
    total = 0
    ner_count = 0
    for unit in units:
        text = unit.get("text", "")
        candidates = pre_extract(
            text, ner_client=ner_client, profile_id=context["profile_id"]
        )
        if not candidates:
            continue
        evidence_unit = {
            "unit_id": unit.get("unit_id"),
            "source_span_ids": unit.get("source_span_ids", []),
            "text": text,
        }
        for row in build_candidate_rows(context, evidence_unit, candidates):
            if any("paddlenlp:ner" in method for method in row["extraction_method"]):
                ner_count += 1
            if not dry_run:
                upsert_knowledge_candidate(db, row)
            total += 1
    return {"candidate_count": total, "ner_count": ner_count}
