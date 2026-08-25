"""L3 pipeline: Original File Gate.

Per brand_knowledge/pipelines/original_file_gate.yaml, this is the compliance
gate before a brand document is parsed. It:
  1. computes the SHA-256 of the original file,
  2. checks hash idempotency (same hash -> skip; same URL different hash -> new
     version),
  3. flags PII / trade-secret / contract / unpublished-roadmap content using
     keyword heuristics,
  4. applies the access-level gate: if the document needs a higher access level
     than the current task allows, or exposes sensitive content that forbids
     parsing, the source is rejected (or metadata-only) rather than parsed.

The gate updates ``source_instance.status`` to ``gate_passed`` or ``rejected``
and mirrors the PII / trade-secret flags onto the linked ``document`` row.
"""
from __future__ import annotations

import os
import re
from typing import Any

from runtime.db import DB
from runtime.brand.pipelines._helpers import resolve_brand_context, sha256_bytes

# Keyword heuristics for sensitive content (pragmatic regex sets).
PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # email
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",  # IPv4
    r"\b(?:\+?\d[\d\s\-()]{7,}\d)\b",  # phone-ish
    r"\b(身份证|身份证号|护照号|社保号|银行卡|手机号|身份证号码)\b",
    r"\b(?:ID number|passport|social security|phone number)\b",
]
TRADE_SECRET_PATTERNS = [
    r"(商业秘密|专有技术|核心配方|源代码|未公开算法|内部机密)",
    r"(trade secret|proprietary|confidential algorithm|source code)",
]
CONTRACT_PATTERNS = [
    r"(合同号|协议|保密协议|NDA|条款与条件|价格条款)",
    r"(contract|agreement|non-disclosure|terms)",
]
ROADMAP_PATTERNS = [
    r"(路线图|未发布|内部规划|未来计划|roadmap|unreleased|internal plan)",
]

# Only these access levels may enter parsing un-gated.
ALLOWED_PARSE_ACCESS = {"public", "internal"}


def _scan_sensitive(text: str) -> dict:
    """Return sensitivity findings from keyword heuristics."""
    findings = []
    flags = {"contains_pii": False, "contains_trade_secret": False,
             "contains_contract": False, "contains_roadmap": False}
    for pat in PII_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            flags["contains_pii"] = True
            findings.append("pii")
            break
    for pat in TRADE_SECRET_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            flags["contains_trade_secret"] = True
            findings.append("trade_secret")
            break
    for pat in CONTRACT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            flags["contains_contract"] = True
            findings.append("contract")
            break
    for pat in ROADMAP_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            flags["contains_roadmap"] = True
            findings.append("roadmap")
            break
    flags["sensitivity_findings"] = findings
    return flags


def run(db: DB, args) -> dict[str, Any]:
    """Run the original-file gate over the input file."""
    file_path = getattr(args, "file", None)
    if not file_path:
        raise ValueError("original_file_gate requires --file <path>")
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    ctx = resolve_brand_context(db, args)
    source_id = getattr(args, "source_id", None)
    access_level = getattr(args, "access_level", None) or "internal"

    with open(file_path, "rb") as f:
        raw = f.read()
    content_hash = sha256_bytes(raw)
    text = raw.decode("utf-8", errors="replace")

    sensitivity = _scan_sensitive(text)

    # --- idempotency: same hash already gate-processed -> skip ---
    processed = db.query(
        "SELECT id, status FROM source_instance WHERE source_id = %s AND content_hash = %s LIMIT 1",
        (source_id, content_hash),
    ) if source_id else []
    if processed and processed[0]["status"] in ("gate_passed", "rejected"):
        print(f"[original_file_gate] idempotent skip for {source_id} (status={processed[0]['status']})")
        return {
            "pipeline": "original_file_gate",
            "source_id": source_id,
            "content_hash": content_hash,
            "idempotent": True,
            "status": processed[0]["status"],
            "sensitivity": sensitivity,
        }

    # --- gate decision ---
    # Reject outright if sensitive content exists but the source is intended to
    # be parsed, or if the access level is above what the pipeline may handle.
    reasons = []
    if sensitivity["contains_trade_secret"] or sensitivity["contains_contract"]:
        reasons.append("sensitive_content")
    if access_level not in ALLOWED_PARSE_ACCESS:
        reasons.append(f"access_level:{access_level}")
    if sensitivity["contains_roadmap"]:
        reasons.append("unpublished_roadmap")

    gate_decision = "parse_release" if not reasons else "metadata_only"
    status = "gate_passed" if gate_decision == "parse_release" else "rejected"

    if getattr(args, "dry_run", False):
        print("[original_file_gate] DRY-RUN gate decision")
        print(f"  source_id:    {source_id}")
        print(f"  content_hash: {content_hash}")
        print(f"  sensitivity:  {sensitivity['sensitivity_findings']}")
        print(f"  gate_decision:{gate_decision}")
        print(f"  status:       {status}")
        return {
            "pipeline": "original_file_gate",
            "dry_run": True,
            "source_id": source_id,
            "content_hash": content_hash,
            "gate_decision": gate_decision,
            "status": status,
            "sensitivity": sensitivity,
            "reasons": reasons,
        }

    # --- update source_instance status ---
    if source_id:
        db.execute(
            "UPDATE source_instance SET status = %s, content_hash = %s, "
            "access_level = %s, attributes = COALESCE(attributes,'{}'::jsonb) || %s::jsonb "
            "WHERE source_id = %s",
            (status, content_hash, access_level,
             _jsonstr({"gate_decision": gate_decision, "sensitivity": sensitivity}),
             source_id),
        )

    # --- mirror flags onto the linked document ---
    doc = db.query(
        "SELECT id FROM document WHERE document_id = %s OR source_id IN "
        "(SELECT id FROM source_instance WHERE source_id = %s) LIMIT 1",
        (getattr(args, "document_id", None), source_id),
    ) if source_id or getattr(args, "document_id", None) else []
    if doc:
        db.execute(
            "UPDATE document SET contains_pii = %s, contains_trade_secret = %s, "
            "content_hash = %s, access_level = %s WHERE id = %s",
            (sensitivity["contains_pii"], sensitivity["contains_trade_secret"],
             content_hash, access_level, doc[0]["id"]),
        )

    print(f"[original_file_gate] {gate_decision} for {source_id} -> status={status}")
    return {
        "pipeline": "original_file_gate",
        "source_id": source_id,
        "content_hash": content_hash,
        "gate_decision": gate_decision,
        "status": status,
        "sensitivity": sensitivity,
        "reasons": reasons,
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
    }


def _jsonstr(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 original file gate pipeline")
    parser.add_argument("--file", required=True, help="Path to the brand source file")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--source-id", help="source_id to gate (from source_registration)")
    parser.add_argument("--document-id", help="Optional document_id to mirror flags")
    parser.add_argument("--access-level", choices=["public", "internal", "confidential", "restricted"])
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    ns = parser.parse_args()

    with DB.from_env() as db:
        result = run(db, ns)
        print(json.dumps(result, ensure_ascii=False, indent=2))