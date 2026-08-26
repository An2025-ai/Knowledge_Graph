"""X-Zone schema compatibility guard (审查 Action Plan “新增内容”).

Parse ``database/l2_l3_schema.sql`` so the tests know the *real* column set of the
tables the pipelines write, then assert each pipeline's INSERT column list only
mentions real columns and supplies every NOT NULL (no-default) column. This is a
dumb SQL-text parser (enough for this case); it does not execute against PG.

Guards:
- content_inventory (Critical #1): no phantom ``attributes``, must include
  NOT NULL ``brand_id``.
- gate_candidate_knowledge (High #7): write path must carry ``schema_valid``.
- knowledge_candidates / candidate_embedding: write columns are real.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "database" / "l2_l3_schema.sql"


# ---------------------------------------------------------------------------
# Minimal `CREATE TABLE` column-set extractor
# ---------------------------------------------------------------------------

def _table_columns(schema_text: str, table_name: str) -> dict[str, dict[str, str]]:
    """Return {column: {type, not_null, has_default, default}} for a table.

    Only the immediate definition body (up to the closing ``)``) of
    ``CREATE TABLE IF NOT EXISTS <table_name>`` is parsed. Column rows start with
    a bare identifier followed by a type; constraint rows start with
    ``CONSTRAINT`` / ``UNIQUE`` / ``CHECK`` / ``PRIMARY KEY`` and are skipped.
    """
    m = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table_name)}\s*\((.*?)\n\)",
        schema_text, re.S,
    )
    if not m:
        raise KeyError(f"table {table_name!r} not found in schema")
    cols: dict[str, dict[str, str]] = {}
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith(("CONSTRAINT", "UNIQUE", "CHECK", "PRIMARY", "FOREIGN")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        if name.startswith(("--", "#")):
            continue
        rest = " ".join(parts[1:])
        not_null = "NOT NULL" in rest
        has_default = "DEFAULT" in rest
        default = rest.split("DEFAULT ", 1)[1] if has_default else ""
        cols[name] = {
            "type": parts[1],
            "not_null": not_null,
            "has_default": has_default,
            "default": default,
        }
    return cols


def _required_columns(cols: dict[str, dict[str, str]]) -> set[str]:
    """Columns that MUST be supplied by an INSERT (NOT NULL and no default)."""
    return {c for c, meta in cols.items() if meta["not_null"] and not meta["has_default"]}


def _insert_columns(sql: str) -> list[str]:
    """Extract the explicit column list of an ``INSERT INTO t (a, b, c)``."""
    m = re.search(r"INSERT INTO \w+\s*\(([^)]*)\)", sql)
    if not m:
        raise ValueError(f"no INSERT column list in: {sql}")
    return [c.strip().strip('"') for c in m.group(1).split(",") if c.strip()]


class SchemaCompatTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema_text = SCHEMA.read_text(encoding="utf-8")

    def test_content_inventory_insert_columns_match_schema(self):
        """Critical #1: sensitive_content_warning INSERT must not use a phantom
        ``attributes`` column and must supply NOT NULL ``brand_id``."""
        from engine.brand.pipelines.sensitive_content_warning import run as run_sensitive
        from types import SimpleNamespace

        from tests.test_runtime_regressions import RecordingDB

        db = RecordingDB()
        args = SimpleNamespace(
            brand="Acme", tenant="default",
            text="本项目是行业唯一，获得 ISO 27001 认证，ROI 提升 30%。",
            document_id="doc-1", dry_run=False,
        )
        result = run_sensitive(db, args)
        self.assertEqual(result["warning_count"], 3)

        cols_spec = _table_columns(self.schema_text, "content_inventory")
        for sql, _ in db.executions:
            if "content_inventory" in sql:
                used = _insert_columns(sql)
                self.assertTrue(used, "INSERT must carry an explicit column list")
                unknown = set(used) - set(cols_spec)
                self.assertEqual(
                    unknown, set(),
                    f"INSERT references non-schema columns: {sorted(unknown)}",
                )
                self.assertIn("brand_id", used, "requires NOT NULL brand_id")
                self.assertNotIn("attributes", used, "content_inventory has no attributes")

    def test_gate_candidate_knowledge_has_schema_valid_column(self):
        """High #7: gate_candidate_knowledge must expose schema_valid and the fusion
        write path must set it (default FALSE, explicit True to pass the gate)."""
        cols_spec = _table_columns(self.schema_text, "gate_candidate_knowledge")
        self.assertIn("schema_valid", cols_spec)
        self.assertTrue(cols_spec["schema_valid"]["not_null"])
        self.assertIn("false", cols_spec["schema_valid"]["default"].lower())

        # fusion write path carries schema_valid through the upsert row
        from engine.fusion.fusion_service import group_and_emit, resolve_entities
        from tests.test_runtime_regressions import RecordingDB

        db = RecordingDB()
        candidates = [
            {"candidate_id": "KC1", "candidate_type": "statement",
             "subject": {"entity_type": "brand", "name": "Acme"},
             "statement": {"text": "Acme 提供云服务"}, "confidence": 0.9,
             "evidence_text": "云服务", "evidence_unit_id": "EU1",
             "schema_valid": True},
        ]
        entities = resolve_entities(db, candidates, profile_id="l3_brand",
                                    layer="l3_brand", tenant_id=None)
        group_and_emit(db, candidates, entities, profile_id="l3_brand",
                       layer="l3_brand", tenant_id=None)
        gate_rows = [r for t, r in db.inserts if t == "gate_candidate_knowledge"]
        self.assertTrue(gate_rows, "fusion must emit gate rows")
        self.assertTrue(gate_rows[0].get("schema_valid"),
                        "fusion must pass schema_valid=True through to the gate row")

    def test_knowledge_candidates_write_uses_real_columns(self):
        """build_candidate_rows rows map onto real knowledge_candidates columns,
        and schema_valid is a real, defaulted column."""
        cols_spec = _table_columns(self.schema_text, "knowledge_candidates")
        from engine.extraction.candidate_extraction import build_candidate_rows

        context = {"document_uuid": "duuid", "document_id": "doc1",
                   "profile_id": "l3_brand", "layer": "l3_brand"}
        rows = build_candidate_rows(
            context, {"unit_id": "EU1", "source_span_ids": ["ES1"], "text": "营收 12 亿元。"},
            [{"candidate_type": "metric", "candidate_payload": {"value": "12", "name": "营收"},
              "confidence": 0.85, "generator": "regex:numeric_metric"}],
        )
        self.assertTrue(rows)
        for row in rows:
            for k in (k for k in row if k not in ("document_id", "document_uuid")):
                self.assertIn(k, cols_spec, f"candidate row key {k!r} not a schema column")
        self.assertIn("schema_valid", cols_spec)


if __name__ == "__main__":
    unittest.main()