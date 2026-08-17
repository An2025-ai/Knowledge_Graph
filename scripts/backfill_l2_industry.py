# -*- coding: utf-8 -*-
"""Backfill L2 industry_id on entities that lost their industry tag.

The L2 e-commerce finance extraction produced entity rows whose top-level
`industry_id` column is NULL (only some carried it), which made
`visualize.export --layer L2` return an empty layer. This script restores the
industry tag so the L2 layer exports properly.

Criteria (conservative, only touches NULLs, never overwrites):
  1. Preferred: entity has `attributes->'report_candidate_ids'` lineage, and that
     candidate -> report -> requirement resolves to a real industry_id.
  2. Fallback: entity is non-brand (owner_brand IS NULL, no brand_id), active,
     and matches the industry keyword vocabulary — only used when lineage is
     unavailable. This is safe because there is currently a single industry
     (`ind_电商业财一体化软件`).
"""
import sys

sys.path.insert(0, r"d:\Brand Atlas\Knowledge_Graph")
from runtime.db import DB

INDUSTRY_ID = "ind_电商业财一体化软件"

# Fallback keyword vocabulary for e-commerce finance (used only when lineage
# cannot resolve the industry). Entity names matching any token are treated as
# belonging to the L2 industry.
VOCAB = [
    "财务", "电商", "账", "结算", "报表", "税务", "ERP", "会计", "对账",
    "GMV", "公司", "企业", "客户", "决策", "用户", "采购", "审批",
    "能力", "场景", "方案", "平台", "系统", "销售", "市场", "行业",
]


def _resolve_via_lineage(db) -> set[str]:
    """Return set of entity UUIDs whose report_candidate lineage resolves to a known
    industry_id. This is the highest-precision signal."""
    rows = db.query(
        "SELECT DISTINCT e.id AS eid "
        "FROM entity e "
        "CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(e.attributes->'report_candidate_ids','[]'::jsonb)) rc "
        "JOIN report_candidate r ON r.id::text = rc "
        "JOIN research_report rr ON rr.id = r.report_id "
        "LEFT JOIN industry_requirement ir ON ir.id = rr.requirement_id "
        "WHERE ir.industry_id = %s ",
        (INDUSTRY_ID,),
    )
    return {str(x["eid"]) for x in rows}


def _matches_vocab(canonical_name: str) -> bool:
    name = canonical_name or ""
    return any(token in name for token in VOCAB)


def main() -> None:
    with DB.from_env() as db:
        lineage_ids = _resolve_via_lineage(db)
        print(f"lineage-resolved entities: {len(lineage_ids)}")

        # Candidate rows: active, non-brand, industry_id IS NULL.
        rows = db.query(
            "SELECT id, canonical_name, attributes FROM entity "
            "WHERE status='active' AND industry_id IS NULL AND owner_brand IS NULL "
            "AND NOT (attributes ? 'brand_id')"
        )
        updated = 0
        for e in rows:
            eid = str(e["id"])
            via_lineage = eid in lineage_ids
            via_vocab = _matches_vocab(e.get("canonical_name"))
            if not (via_lineage or via_vocab):
                continue
            db.execute(
                "UPDATE entity SET industry_id = %s WHERE id = %s AND industry_id IS NULL",
                (INDUSTRY_ID, eid),
            )
            updated += 1
        print(f"backfilled {updated} entities -> industry_id={INDUSTRY_ID}")
        remaining = db.query(
            "SELECT count(*) AS c FROM entity WHERE status='active' AND industry_id IS NULL "
            "AND owner_brand IS NULL AND NOT (attributes ? 'brand_id')"
        )[0]["c"]
        print(f"remaining industry_id-NULL active non-brand: {remaining}")


if __name__ == "__main__":
    main()
