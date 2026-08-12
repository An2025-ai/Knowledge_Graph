"""Turn an L2 industry requirement into a single, structured geo-research request.

geo-research's `--request` is one blob of free text. A full L2 `industry_requirement`
carries `required_dimensions` (each with questions/expected_fields/source expectations).
This module flattens that structured requirement into a natural-language research
demand that drives geo-research's search planning (SearXNG queries + LLM report).

Usage:
    python -m runtime.l2.requirement_to_request --requirement-id ikr_xxx \
        [--market CN] [--out request.txt]
"""
from __future__ import annotations

import argparse
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

    lines: list[str] = []
    lines.append(f"研究行业：{industry_id or '（行业）'}（市场：{market}）。")
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