"""L2 pipeline: Report Ingestion.

Parses a Markdown industry report into structured report sections and
knowledge candidates. Per industry_knowledge/pipelines/report_ingestion.yaml:

  1. Split the Markdown into sections by `# ` / `## ` (etc.) headings
  2. For each section, record a `report_section` row (title, order, span)
  3. Extract candidate statements — sentences/lines carrying `[S#]` citation
     labels — and upsert them as `report_candidate` rows.

Candidates that carry no `[S#]` citation are still recorded but flagged with
status 'candidate' and an empty citation list (uncited) so downstream
evidence resolution can handle them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from runtime.db import DB


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
CITATION_RE = re.compile(r"\[(S\d+)\]")


def _split_sections(text: str) -> list[dict]:
    """Split markdown text into (title, level, start_line, lines) sections.

    Lines before the first heading are collected as a 'preamble' section.
    Returns a list of dicts: {title, level, start_line, end_line, body}.
    """
    lines = text.splitlines()
    sections: list[dict] = []
    current = {"title": "preamble", "level": 0, "start_line": 1, "end_line": 0, "body": []}

    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            # close previous section
            current["end_line"] = idx - 1
            sections.append(current)
            current = {
                "title": m.group(2).strip(),
                "level": len(m.group(1)),
                "start_line": idx,
                "end_line": idx,
                "body": [],
            }
        else:
            current["body"].append(line)
    current["end_line"] = len(lines)
    sections.append(current)
    return sections


def _sentences(text: str) -> list[str]:
    """Very small sentence splitter: split non-empty lines / sentence ends."""
    parts = re.split(r"(?<=[。！？.!?])\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _statement_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _report_uuid(db: DB, report_id: str) -> str | None:
    rows = db.query(
        "SELECT id FROM research_report WHERE report_id = %s LIMIT 1", (report_id,)
    )
    return rows[0]["id"] if rows else None


def parse_report(text: str) -> dict[str, Any]:
    """Parse markdown into sections and candidates (db-independent)."""
    sections = _split_sections(text)
    candidates: list[dict] = []
    for section in sections:
        body = "\n".join(section["body"])
        for sent in _sentences(body):
            citations = CITATION_RE.findall(sent)
            candidates.append(
                {
                    "statement": sent,
                    "citation_labels": citations,
                    "section_title": section["title"],
                    "section_level": section["level"],
                    "start_line": section["start_line"],
                    "end_line": section["end_line"],
                }
            )
    return {
        "sections": sections,
        "candidates": candidates,
        "total_lines": len(text.splitlines()),
    }


def run(db: DB, args) -> dict[str, Any]:
    """Ingest a markdown report into report_section + report_candidate rows."""
    report_path = getattr(args, "report", None)
    if not report_path or not os.path.exists(report_path):
        raise FileNotFoundError(f"Report not found: {report_path}")

    report_id = getattr(args, "report_id", None)
    if not report_id:
        raise ValueError("report_id is required for report ingestion")

    with open(report_path, "r", encoding="utf-8") as f:
        text = f.read()

    parsed = parse_report(text)
    report_uuid = _report_uuid(db, report_id)
    if report_uuid is None and not getattr(args, "create_report_if_missing", False):
        raise ValueError(
            f"No research_report row found for report_id '{report_id}'. "
            "Run geo_research_report_job first or pass --create-report."
        )

    dry_run = getattr(args, "dry_run", False)

    # --- sections ---
    section_fks: dict[int, str] = {}  # section_order -> section uuid/id
    for i, section in enumerate(parsed["sections"], start=1):
        if section["start_line"] > section["end_line"] or not section["body"]:
            continue
        section_row = {
            "report_id": report_uuid,
            "section_code": f"sec_{i:03d}",
            "section_title": section["title"],
            "section_order": i,
            "start_line": section["start_line"],
            "end_line": section["end_line"],
            "content_type": "markdown",
            "metadata": {"level": section["level"]},
        }
        if not dry_run:
            section_id = db.insert_returning_id(
                "INSERT INTO report_section (report_id, section_code, section_title, "
                "section_order, start_line, end_line, content_type, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (report_uuid, section_row["section_code"], section_row["section_title"],
                 section_row["section_order"], section_row["start_line"],
                 section_row["end_line"], section_row["content_type"],
                 db._json(section_row["metadata"])),
            )
        else:
            section_id = f"dry-sec-{i}"
        section_fks[i] = section_id

    # --- candidates ---
    candidate_count = 0
    for cand in parsed["candidates"]:
        sec_order = _section_order_for_line(parsed["sections"], cand["start_line"])
        section_id = section_fks.get(sec_order)
        cand_row = {
            "report_id": report_uuid,
            "section_id": section_id,
            "section_code": f"sec_{sec_order:03d}" if sec_order else None,
            "report_span": f"{cand['start_line']}-{cand['end_line']}",
            "statement": cand["statement"],
            "candidate_type": "statement",
            "citation_labels": cand["citation_labels"],
            "normalized_statement_hash": _statement_hash(cand["statement"]),
            "status": "candidate",
        }
        candidate_count += 1
        if not dry_run:
            # report_candidate has no natural unique key; insert a fresh row.
            db.execute(
                "INSERT INTO report_candidate (report_id, section_id, section_code, "
                "report_span, statement, candidate_type, citation_labels, "
                "normalized_statement_hash, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (report_uuid, section_id, cand_row["section_code"],
                 cand_row["report_span"], cand_row["statement"],
                 cand_row["candidate_type"], db._json(cand_row["citation_labels"]),
                 cand_row["normalized_statement_hash"], cand_row["status"]),
            )

    if dry_run:
        print(f"[report_ingestion] DRY-RUN: parsed {len(parsed['sections'])} sections, "
              f"would insert {candidate_count} candidates from {report_path}")
    else:
        print(f"[report_ingestion] ingested {report_path}: "
              f"{len(parsed['sections'])} sections, {candidate_count} candidates")

    return {
        "pipeline": "report_ingestion",
        "report_id": report_id,
        "report_path": report_path,
        "section_count": len(parsed["sections"]),
        "candidate_count": candidate_count,
        "dry_run": dry_run,
    }


def _section_order_for_line(sections: list[dict], line: int) -> int | None:
    """Return the 1-based section index containing the given line."""
    for i, s in enumerate(sections, start=1):
        if s["start_line"] <= line <= max(s["end_line"], s["start_line"]):
            return i
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 report ingestion pipeline")
    parser.add_argument("--report", required=True, help="Path to markdown report")
    parser.add_argument("--report-id", required=True, help="research_report.report_id to attach to")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))