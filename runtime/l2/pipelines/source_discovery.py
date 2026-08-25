"""L2 pipeline: Source Discovery.

Input: industry scope / requirement dimensions.
Output: a source candidate list that can seed a research_package crawl.

The output is file-based by design so it can be reviewed, edited, cached, and
reused before any crawling or database promotion happens.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from runtime.db import DB
from runtime.l1.registry import get_l1_registry
from runtime.l2.scope_builder import DIMENSION_TEMPLATE
from runtime.l2.search.providers import (
    fallback_search_result,
    provider_status,
    search,
    source_id_from_url,
)


DIMENSION_SOURCE_CLASSES = {
    code: get_l1_registry().dimension_source_classes(code)
    for code in (
        "market_definition", "category_structure", "market_participants",
        "audience_and_decision_chain", "problems_and_jobs", "use_cases",
        "capabilities", "decision_factors", "topics_and_questions",
        "market_facts_and_trends", "regulation_and_risks", "competition_structure",
        "source_ecology", "evidence_gaps",
    )
}

DIMENSION_KEYWORDS = {
    "market_definition": ["definition", "scope", "boundary", "定义", "边界", "标准"],
    "category_structure": ["category", "taxonomy", "classification", "品类", "分类", "结构"],
    "market_participants": ["vendor", "participant", "share", "厂商", "企业", "份额", "参与者"],
    "audience_and_decision_chain": ["buyer", "decision", "persona", "用户", "采购", "决策链"],
    "problems_and_jobs": ["pain point", "job to be done", "需求", "痛点", "任务"],
    "use_cases": ["use case", "case study", "scenario", "场景", "案例", "应用"],
    "capabilities": ["capability", "feature", "function", "能力", "功能", "模块"],
    "decision_factors": ["evaluation", "selection", "criteria", "选型", "指标", "决策因素"],
    "topics_and_questions": ["topic", "question", "faq", "问题", "主题", "趋势"],
    "market_facts_and_trends": ["market size", "growth", "trend", "规模", "增长", "趋势"],
    "regulation_and_risks": ["regulation", "policy", "risk", "政策", "法规", "合规", "风险"],
    "competition_structure": ["competition", "competitor", "alternative", "竞争", "竞品", "格局"],
    "source_ecology": ["source", "association", "institute", "信源", "协会", "研究院", "机构"],
    "evidence_gaps": ["gap", "missing", "uncertain", "缺口", "不足", "不确定"],
}

# Default trusted domains per market region, single source of truth: the L1
# source_discovery_policy (via registry). Kept as a derived map for callers.
DEFAULT_TRUSTED_DOMAINS = {
    "CN": get_l1_registry().trusted_domains("CN"),
    "GLOBAL": get_l1_registry().trusted_domains("GLOBAL"),
}


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    separator = ";" if ";" in value else ","
    return [item.strip() for item in value.split(separator) if item.strip()]


def _load_scope(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required to load scope files")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    scope = dict(raw)
    inner = raw.get("scope")
    if isinstance(inner, dict):
        for key, value in inner.items():
            scope.setdefault(key, value)
    return scope


def _dimension_template_map() -> dict[str, dict]:
    return {d["dimension_code"]: d for d in DIMENSION_TEMPLATE}


def _dimensions(scope: dict, args) -> list[dict]:
    selected = _csv(getattr(args, "dimensions", None) or getattr(args, "priority_dim", None))
    explicit = scope.get("required_dimensions") or []
    if explicit:
        dims = [dict(d) for d in explicit]
    else:
        dims = [dict(d) for d in DIMENSION_TEMPLATE]
    if selected:
        selected_set = set(selected)
        dims = [d for d in dims if d.get("dimension_code") in selected_set]
    return dims


def _host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower().removeprefix("www.")


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _contains_any(text: str, needles: list[str]) -> bool:
    haystack = _norm(text)
    return any(_norm(item) and _norm(item) in haystack for item in needles)


def _domain_matches(host: str, domains: list[str]) -> bool:
    clean = host.lower().removeprefix("www.")
    for domain in domains:
        d = domain.lower().removeprefix("www.").strip()
        if not d:
            continue
        if clean == d or clean.endswith(f".{d}") or clean.endswith(d):
            return True
    return False


def _source_class_for(url: str, title: str, snippet: str, preferred: list[str]) -> str:
    host = _host(url)
    text = f"{host} {title} {snippet}"
    if ".gov" in host or host.endswith("gov.cn"):
        return "government"
    if ".edu" in host or ".ac." in host:
        return "academic"
    if _contains_any(text, ["standard", "标准", "sac.gov.cn", "cnis.ac.cn"]):
        return "standards_body"
    if _contains_any(text, ["association", "协会", "联盟"]):
        return "industry_association"
    if _contains_any(text, ["annual report", "investor", "10-k", "招股书", "年报"]):
        return "company_disclosure"
    if _contains_any(text, ["gartner", "idc", "forrester", "iresearch", "艾瑞", "analysys", "易观", "caict", "信通院"]):
        return "industry_research"
    return preferred[0] if preferred else "reliable_media"


def _authority_score(candidate: dict[str, Any], seed_sources: list[str],
                     trusted_domains: list[str]) -> tuple[float, str]:
    url = candidate.get("url") or ""
    host = _host(url)
    title = candidate.get("title") or ""
    snippet = candidate.get("snippet") or ""
    text = f"{title} {snippet} {url}"
    if candidate.get("source_type") == "seed" or _contains_any(text, seed_sources):
        return 0.98, "seed"
    if _domain_matches(host, trusted_domains):
        return 0.92, "trusted_domain"
    if ".gov" in host or host.endswith("gov.cn"):
        return 0.88, "official"
    if ".edu" in host or ".ac." in host:
        return 0.78, "academic"
    if _contains_any(text, ["white paper", "report", "研究报告", "白皮书", "标准", "协会"]):
        return 0.62, "research_candidate"
    if _contains_any(text, ["研究报告", "白皮书", "行业标准", "团体标准", "行业协会", "研究院", "信通院", "艾瑞", "易观"]):
        return 0.68, "research_candidate"
    if candidate.get("engine") == "fallback":
        return 0.35, "search_plan"
    return 0.42, "exploratory"


def _dimension_relevance_score(candidate: dict[str, Any], industry: str,
                               dimension_code: str, query: str) -> float:
    text = " ".join([
        candidate.get("title") or "",
        candidate.get("snippet") or "",
        candidate.get("url") or "",
        query or "",
    ])
    score = 0.0
    if industry and _norm(industry) in _norm(text):
        score += 0.35
    keywords = DIMENSION_KEYWORDS.get(dimension_code, [])
    hits = sum(1 for kw in keywords if _norm(kw) in _norm(text))
    if hits:
        score += min(0.45, 0.18 + hits * 0.09)
    if dimension_code and dimension_code.replace("_", " ") in _norm(text):
        score += 0.2
    return min(score, 1.0)


def _score_candidate(candidate: dict[str, Any], industry: str, seed_sources: list[str],
                     trusted_domains: list[str], query: str) -> dict[str, Any]:
    dimension_code = (candidate.get("dimension_codes") or ["source_ecology"])[0]
    authority, tier = _authority_score(candidate, seed_sources, trusted_domains)
    relevance = _dimension_relevance_score(candidate, industry, dimension_code, query)
    preferred = DIMENSION_SOURCE_CLASSES.get(dimension_code, [])
    source_class = candidate.get("source_class") or ""
    class_bonus = 0.08 if source_class in preferred else 0.0
    overall = min(1.0, authority * 0.58 + relevance * 0.34 + class_bonus)
    candidate.update({
        "authority_score": round(authority, 3),
        "dimension_relevance_score": round(relevance, 3),
        "overall_score": round(overall, 3),
        "authority_tier": tier,
    })
    return candidate


def _query_templates(dimension_code: str) -> list[str]:
    return {
        "market_definition": ["{industry} {market} 市场 定义 边界", "{industry} 行业 标准 定义"],
        "category_structure": ["{industry} 品类 结构 子品类", "{industry} 解决方案 分类"],
        "market_participants": ["{industry} {market} 主要厂商 市场份额", "{industry} 头部企业 产品"],
        "audience_and_decision_chain": ["{industry} 用户角色 决策链", "{industry} 采购决策 角色"],
        "problems_and_jobs": ["{industry} 用户痛点 需求", "{industry} job to be done"],
        "use_cases": ["{industry} 使用场景 案例", "{industry} 应用场景"],
        "capabilities": ["{industry} 产品能力 功能模块", "{industry} capabilities features"],
        "decision_factors": ["{industry} 选型 决策因素", "{industry} 采购 评估指标"],
        "topics_and_questions": ["{industry} 热门问题 主题", "{industry} 常见问题"],
        "market_facts_and_trends": ["{industry} 市场规模 增长率 趋势", "{industry} industry report market size"],
        "regulation_and_risks": ["{industry} 法规 政策 风险", "{industry} 数据安全 合规"],
        "competition_structure": ["{industry} 竞争格局 竞品", "{industry} alternatives competitors"],
        "source_ecology": ["{industry} 权威 来源 研究机构", "{industry} 行业协会 标准"],
        "evidence_gaps": ["{industry} 数据缺口 证据不足"],
    }.get(dimension_code, ["{industry} {dimension}"])


def build_query_plan(industry: str, market: str, dims: list[dict],
                     seed_sources: list[str]) -> list[dict]:
    plan = []
    for dim in dims:
        code = dim.get("dimension_code")
        queries = [
            q.format(industry=industry, market=market, dimension=code)
            for q in _query_templates(code)
        ]
        for seed in seed_sources:
            queries.insert(0, f"{seed} {industry} {code}")
        plan.append({
            "dimension_code": code,
            "queries": queries,
            "expected_fields": dim.get("expected_fields") or _dimension_template_map().get(code, {}).get("expected_fields", []),
            "preferred_source_classes": DIMENSION_SOURCE_CLASSES.get(code, ["industry_research", "reliable_media"]),
        })
    return plan


def discover_sources(industry: str, market: str, dims: list[dict], seed_sources: list[str],
                     max_results_per_query: int = 3, use_provider: bool = True,
                     trusted_domains: list[str] | None = None,
                     max_sources_per_dimension: int = 5,
                     min_authority_score: float = 0.4,
                     strict_authority: bool = False,
                     include_exploratory: bool = False) -> dict[str, Any]:
    status = provider_status() if use_provider else {"provider": "fallback", "searxng_available": False}
    query_plan = build_query_plan(industry, market, dims, seed_sources)
    raw_candidates = []
    seen_urls = set()
    trusted = list(trusted_domains or [])
    trusted.extend(DEFAULT_TRUSTED_DOMAINS.get(market.upper(), DEFAULT_TRUSTED_DOMAINS["GLOBAL"]))

    for item in query_plan:
        for query in item["queries"]:
            try:
                results = search(query, max_results=max_results_per_query) if status.get("searxng_available") else []
            except Exception as exc:  # noqa: BLE001 - per-query fallback
                results = [fallback_search_result(query)]
                status.setdefault("errors", []).append(str(exc)[:200])
            if not results:
                results = [fallback_search_result(query)]
            for result in results:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                source_class = _source_class_for(
                    result.url,
                    result.title,
                    result.snippet,
                    item["preferred_source_classes"],
                )
                candidate = {
                    "source_id": source_id_from_url(result.url),
                    "title": result.title,
                    "url": result.url,
                    "snippet": result.snippet,
                    "engine": result.engine or status.get("provider"),
                    "rank": result.rank,
                    "dimension_codes": [item["dimension_code"]],
                    "source_class": source_class,
                    "source_type": "web",
                    "discovery_status": "pending_review",
                    "l2_enabled": False,
                    "approval_status": "pending",
                    "selection_reason": f"matched query: {query}",
                }
                raw_candidates.append(_score_candidate(candidate, industry, seed_sources, trusted, query))

    for seed in seed_sources:
        seed_query = f"{seed} {industry}"
        url = f"https://www.google.com/search?q={seed_query.replace(' ', '+')}"
        if url in seen_urls:
            continue
        candidate = {
            "source_id": source_id_from_url(url),
            "title": seed,
            "url": url,
            "snippet": "Seed source from scope manifest; resolve to official pages during review/crawl.",
            "engine": "seed",
            "rank": 0,
            "dimension_codes": [d.get("dimension_code") for d in dims],
            "source_class": "industry_research",
            "source_type": "seed",
            "discovery_status": "pending_review",
            "l2_enabled": False,
            "approval_status": "pending",
            "selection_reason": "seed_source",
        }
        raw_candidates.append(_score_candidate(candidate, industry, seed_sources, trusted, seed_query))

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    per_dimension: dict[str, int] = {d.get("dimension_code"): 0 for d in dims}
    strict_floor = max(min_authority_score, 0.55) if strict_authority else min_authority_score
    for candidate in sorted(raw_candidates, key=lambda x: x.get("overall_score", 0), reverse=True):
        dims_for_source = candidate.get("dimension_codes") or ["source_ecology"]
        dim = dims_for_source[0]
        accepted = (
            candidate.get("authority_score", 0) >= strict_floor
            and candidate.get("dimension_relevance_score", 0) >= 0.25
        )
        if not accepted and include_exploratory and not strict_authority:
            accepted = candidate.get("overall_score", 0) >= 0.38
        if per_dimension.get(dim, 0) >= max_sources_per_dimension:
            accepted = False
            candidate["review_reason"] = "dimension_source_limit_reached"
        elif not accepted:
            candidate["review_reason"] = (
                "below_authority_or_dimension_relevance_threshold"
                if strict_authority else
                "kept_for_review_but_not_research_ready"
            )
        else:
            candidate["review_reason"] = "selected_by_authority_and_dimension_relevance"
            per_dimension[dim] = per_dimension.get(dim, 0) + 1
        candidate["accepted_for_research"] = bool(accepted)
        if accepted:
            selected.append(candidate)
        else:
            rejected.append(candidate)

    coverage_gaps = [
        {
            "dimension_code": dim.get("dimension_code"),
            "reason": "no_authoritative_dimension_matched_source",
            "recommended_action": "add seed source/trusted domain or run source_discovery for this dimension only",
        }
        for dim in dims
        if per_dimension.get(dim.get("dimension_code"), 0) == 0
    ]

    return {
        "industry": industry,
        "market": market,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": status,
        "query_plan": query_plan,
        "sources": selected,
        "rejected_candidates": rejected[:100],
        "coverage_gaps": coverage_gaps,
        "stats": {
            "dimensions": len(dims),
            "queries": sum(len(item["queries"]) for item in query_plan),
            "raw_candidates": len(raw_candidates),
            "sources": len(selected),
            "rejected_candidates": len(rejected),
            "coverage_gaps": len(coverage_gaps),
        },
    }


def _default_out(industry: str, market: str) -> str:
    safe = "".join(c.lower() if c.isalnum() else "_" for c in industry).strip("_") or "industry"
    return str(Path("runtime") / "l2" / "output" / f"source_candidates_{safe}_{market.lower()}.json")


def run(db: DB, args) -> dict[str, Any]:  # noqa: ARG001 - db kept for pipeline signature
    if (getattr(args, "report", None) or getattr(args, "research_package", None)) and not getattr(args, "source_list", None):
        print("[source_discovery] skipped: existing report/research_package was provided")
        return {"pipeline": "source_discovery", "status": "skipped"}

    scope = _load_scope(getattr(args, "scope", None))
    industry = getattr(args, "industry", None) or scope.get("industry_name") or scope.get("industry_id")
    if not industry:
        raise ValueError("source_discovery requires --industry or a scope with industry_name/industry_id")
    market = (getattr(args, "market", None) or scope.get("market") or "CN").upper()
    seed_sources = _csv(getattr(args, "seed_sources", None)) or list(scope.get("seed_sources") or [])
    trusted_domains = _csv(getattr(args, "trusted_domains", None)) or list(scope.get("trusted_domains") or [])
    dims = _dimensions(scope, args)
    max_results = int(getattr(args, "max_results_per_query", None) or 3)
    max_sources_per_dimension = int(getattr(args, "max_sources_per_dimension", None) or 5)
    min_authority_score = float(getattr(args, "min_authority_score", None) or 0.4)
    use_provider = not getattr(args, "offline", False)

    payload = discover_sources(
        industry,
        market,
        dims,
        seed_sources,
        max_results,
        use_provider,
        trusted_domains=trusted_domains,
        max_sources_per_dimension=max_sources_per_dimension,
        min_authority_score=min_authority_score,
        strict_authority=getattr(args, "strict_authority", False),
        include_exploratory=getattr(args, "include_exploratory", False),
    )
    out_path = getattr(args, "source_list", None) or getattr(args, "sources_out", None) or _default_out(industry, market)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.source_list = out_path

    print(f"[source_discovery] wrote {out_path} ({payload['stats']})")
    return {
        "pipeline": "source_discovery",
        "source_list": out_path,
        "industry": industry,
        "market": market,
        **payload["stats"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover L2 candidate sources by industry/dimension.")
    parser.add_argument("--scope", help="Path to industry scope manifest YAML")
    parser.add_argument("--industry", help="Target industry")
    parser.add_argument("--market", default="CN")
    parser.add_argument("--dimensions", help="Comma-separated dimension codes")
    parser.add_argument("--priority-dim", help="Alias for --dimensions")
    parser.add_argument("--seed-sources", help="Comma-separated seed source names")
    parser.add_argument("--trusted-domains", help="Comma-separated trusted domains, e.g. caict.ac.cn,idc.com")
    parser.add_argument("--source-list", help="Output source candidate JSON")
    parser.add_argument("--sources-out", help="Alias for --source-list")
    parser.add_argument("--max-results-per-query", type=int, default=3)
    parser.add_argument("--max-sources-per-dimension", type=int, default=5)
    parser.add_argument("--min-authority-score", type=float, default=0.4)
    parser.add_argument("--strict-authority", action="store_true", help="Reject exploratory sources unless authority is strong.")
    parser.add_argument("--include-exploratory", action="store_true", help="Keep lower-authority sources if relevance is acceptable.")
    parser.add_argument("--offline", action="store_true", help="Skip provider calls and emit fallback candidates")
    ns = parser.parse_args()
    result = run(None, ns)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
