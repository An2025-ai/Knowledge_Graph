# -*- coding: utf-8 -*-
"""Generate a geo-research report OFFLINE from the most recent run's
search-results, without a full re-crawl.

Purpose: the search phase now returns high-quality authoritative results
(IDC/Gartner/艾瑞/易观...). Crawling 90 pages is slow/timeout-prone. This
script reuses `evidence_for_model` + `synthesize_report` to produce a report
directly from the search snippets, enforcing the per-dimension >=5 floor with
the authoritative-domain filter, so we can deliver a report now.

Usage:
    python -X utf8 -m scripts.gen_report_from_search [--run-dir <id>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from src.llm_client import LLMConfig, LLMClient  # noqa: E402
from src.source_config import is_authoritative_record  # noqa: E402
from src.llm_report import evidence_for_model, synthesize_report  # noqa: E402


def build_sources_from_search(search_path: Path) -> list[dict]:
    """Turn search results into evidence-style records, marking authoritative
    ones as crawled (using their snippet as text)."""
    search = json.loads(search_path.read_text(encoding="utf-8"))
    records = []
    for r in search:
        url = r.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        text = str(r.get("snippet") or r.get("content") or "")[:12000]
        records.append(
            {
                "id": r.get("id") or re.sub(r"[^0-9a-f]", "", url)[:16] or str(len(records)),
                "dataset": r.get("dataset") or "market",
                "query": r.get("query") or "",
                "dimension": r.get("dimension"),
                "rank": r.get("rank", 1),
                "title": r.get("title") or url,
                "url": r.get("final_url") or url,
                "snippet": text,
                # Authoritative domain records count as usable evidence; the
                # rest keep snippet-only status so they rank below authoritative.
                "access_status": "crawled" if is_authoritative_record(r) else "search-snippet",
                "text": text,
                "published_at": r.get("published_at"),
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline report from search results")
    parser.add_argument("--run-dir", help="Run id under data/runs to read plan+search from")
    parser.add_argument("--min-per-dim", type=int, default=5)
    parser.add_argument("--max-sources", type=int, default=90)
    parser.add_argument("--out", help="Output report path")
    args = parser.parse_args()

    run_id = args.run_dir or max(
        (d.name for d in (ROOT / "data" / "runs").iterdir() if d.is_dir()),
        key=lambda n: n,
    )
    run_dir = ROOT / "data" / "runs" / run_id
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    search = run_dir / "search-results.json"
    print(f"[gen] run={run_id} plan_queries={len(plan['queries'])}")

    sources = build_sources_from_search(search)
    auth = [s for s in sources if is_authoritative_record(s)]
    print(f"[gen] total sources={len(sources)} authoritative={len(auth)}")

    model_sources, coverage = evidence_for_model(
        sources, args.max_sources, 120000, min_per_dim=args.min_per_dim
    )
    print("[gen] model_sources selected:", len(model_sources))
    for d in coverage:
        print(f"   {d['dimension']}: {d['source_count']} (min {d['min_required']}) -> {d['status']}")

    # Write dimension coverage
    (run_dir / "dimension-coverage.json").write_text(
        json.dumps({"min_sources_per_dimension": args.min_per_dim, "dimensions": coverage},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    config = LLMConfig.from_file(ROOT / "llm-config.local.json")
    client = LLMClient(config)
    body = synthesize_report(client, plan["request"], plan, model_sources)

    report_dir = ROOT / "reports" / "generated"
    report_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else report_dir / f"search-report-{run_id}-offline.md"
    out.write_text(
        "# 专题搜索研究报告（离线，基于搜索快照）\n\n"
        f"- 生成时间：{__import__('datetime').datetime.now().isoformat(timespec='seconds')}\n"
        f"- 运行 ID：{run_id}\n"
        f"- 搜索信源数：{len(model_sources)}（其中权威域 {sum(1 for s in model_sources if is_authoritative_record(s))}）\n"
        f"- 每维度下限：{args.min_per_dim}\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    print(f"[gen] wrote report -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
