"""Turn an L2 industry requirement into a single, structured geo-research request.

geo-research's `--request` is one blob of free text. A full L2 `industry_requirement`
carries `required_dimensions` (each with questions/expected_fields/source expectations).
This module flattens that structured requirement into a natural-language research
demand that drives geo-research's search planning (SearXNG queries + LLM report).

Usage:
    python -m runtime.industry.requirement_to_request --requirement-id ikr_xxx \
        [--market CN] [--out request.txt]
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from runtime.db import DB


def requirement_to_request(requirement: dict, market: str = "CN") -> str:
    """Flatten a requirement dict into a structured research request string."""
    industry_id = requirement.get("industry_id") or requirement.get("industry", {}).get("industry_id")
    market = market or requirement.get("market", "CN")
    req_id = requirement.get("requirement_id")

    dims = requirement.get("required_dimensions") or requirement.get("dimensions") or []
    if not dims and isinstance(requirement.get("industry"), dict):
        dims = requirement["industry"].get("required_dimensions") or []

    # Readable research topic: prefer the industry's canonical name (from the
    # scope manifest / question wording), falling back to a stripped industry_id.
    # NEVER put `ind_<slug>` directly in the search line — geo-research uses this
    # line to derive the topic for its `site:` authoritative queries, so a slug
    # like `ind_游戏笔记本` would make every Layer-1 query search that string.
    industry_name = (
        requirement.get("industry_name")
        or _readable_name_from_questions(dims)
        or _strip_id(industry_id)
        or "行业"
    )

    lines: list[str] = []
    lines.append(f"研究行业：{industry_name}（市场：{market}）。")
    lines.append("请基于公开权威来源（政府、监管、标准组织、行业协会、行业研究机构、券商、权威媒体、厂商官网），生成一份覆盖以下维度的完整行业研究报告。")
    lines.append("所有事实性陈述须带 [S#] 引用。")

    if dims:
        lines.append("")
        lines.append("请覆盖以下数据维度：")
        for i, dim in enumerate(dims, start=1):
            code = dim.get("dimension_code") or dim.get("dimension", f"dimension_{i}")
            questions = dim.get("questions") or []
            if questions:
                qs = "；".join(str(q) for q in questions)
                lines.append(f"{i}. {code}：{qs}")
            else:
                fields = dim.get("expected_fields") or []
                lines.append(f"{i}. {code}（期望：{', '.join(str(f) for f in fields)}）")
    else:
        lines.append("请覆盖市场定义、品类结构、主要厂商、用户与决策链、痛点与任务、使用场景、产品能力、决策因素、竞争格局、市场趋势、合规风险等维度。")

    lines.append("")
    lines.append("报告应包含：执行摘要、研究方法、各维度发现、来源清单、搜索覆盖清单和缺失数据说明。")
    return "\n".join(lines)


def _readable_name_from_questions(dims: list[dict]) -> str | None:
    """Pull a readable industry name from the first dimension question, e.g.
    '游戏笔记本 在 CN 市场的定义...' -> '游戏笔记本'. Returns None if ambiguous."""
    # Markers a template question can use to reference the market, e.g.
    # "<行业> 在 <CN|中国> 市场的定义...". Cut the topic off before any of these.
    for dim in dims:
        questions = dim.get("questions") or []
        for q in questions:
            text = str(q).strip()
            if not text:
                continue
            cut = re.split(r"\s*在\s*(?:CN|中国|[A-Z]{2,3})\s*市场|:\s*$", text)[0].strip()
            cut = cut.strip("，。；：: ")
            if cut and len(cut) <= 40:
                return cut
    return None


def _strip_id(industry_id: str | None) -> str | None:
    """'ind_游戏笔记本' / 'cat_x' -> '游戏笔记本' / 'x'."""
    if not industry_id:
        return None
    return re.sub(r"^(?:ind|cat|industry)_", "", industry_id).strip() or None


def requirement_to_source_config(requirement: dict, market: str = "CN") -> dict:
    """Extract a machine-readable authoritative-source contract for geo-research.

    The crawled `--request` is free text and loses the structured source whitelist.
    This returns a JSON slice the crawler can parse to run a two-layer source
    strategy: (1) hardcoded trusted domains per source class, (2) dynamic
    per-dimension authoritative-source discovery driven by the requirement's
    allowed_source_classes + per-dimension required_source_classes.

    The requirement dict is the single source of truth (NOT any module-level
    hardcoded mapping), so any industry shares the same contract.
    """
    industry_id = requirement.get("industry_id") or requirement.get("industry", {}).get("industry_id")
    req_id = requirement.get("requirement_id")

    dims = requirement.get("required_dimensions") or requirement.get("dimensions") or []
    if not dims and isinstance(requirement.get("industry"), dict):
        dims = requirement["industry"].get("required_dimensions") or []

    src_reqs = requirement.get("source_requirements") or {}
    allowed = src_reqs.get("allowed_source_classes") or list(
        requirement.get("allowed_source_classes") or []
    )
    excluded = src_reqs.get("excluded_source_classes") or list(
        requirement.get("excluded_source_classes") or []
    )

    per_dim: dict[str, list[str]] = {}
    for i, dim in enumerate(dims, start=1):
        code = dim.get("dimension_code") or dim.get("dimension", f"dimension_{i}")
        required = dim.get("required_source_classes")
        # fall back to the global allowed list when a dimension has no explicit set
        per_dim[code] = list(required) if required else list(allowed)

    return {
        "requirement_id": req_id,
        "industry_id": industry_id,
        # Readable topic for geo-research's `site:` queries (NOT the ind_ slug).
        "industry_name": (
            requirement.get("industry_name")
            or _readable_name_from_questions(dims)
            or _strip_id(industry_id)
            or ""
        ),
        "market": market or requirement.get("market", "CN"),
        "allowed_source_classes": list(allowed),
        "excluded_source_classes": list(excluded),
        "per_dimension_source_classes": per_dim,
        "critical_claim_min_independent_sources": src_reqs.get(
            "critical_claim_min_independent_sources", 2
        ),
    }


def load_requirement(db: DB, requirement_id: str) -> dict:
    """Fetch an industry_requirement row by requirement_id."""
    rows = db.query(
        "SELECT * FROM industry_requirement WHERE requirement_id = %s LIMIT 1",
        (requirement_id,),
    )
    if not rows:
        raise ValueError(f"industry_requirement not found: {requirement_id}")
    row = rows[0]
    # JSONB columns come back as Python dicts already (RealDictCursor + psycopg2).
    return dict(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert an L2 requirement into a geo-research request.")
    parser.add_argument("--requirement-id", required=True, help="industry_requirement.requirement_id")
    parser.add_argument("--market", default=None, help="Override market (e.g. CN)")
    parser.add_argument("--out", help="Optional output file for the request text")
    parser.add_argument("--dry-run", action="store_true", help="Load but only print")
    args = parser.parse_args()

    with DB() as db:
        req = load_requirement(db, args.requirement_id)
    text = requirement_to_request(req, market=args.market or req.get("market", "CN"))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[requirement_to_request] wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())