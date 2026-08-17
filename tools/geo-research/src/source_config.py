# -*- coding: utf-8 -*-
"""Two-layer authoritative-source strategy for geo-research reports.

geo-research's `llm_report` historically pushed a hardcoded `GENERAL_SOURCE_QUERIES`
domain list plus generic authority queries, and ignored the Knowledge_Graph source
whitelist contract. This module lets the crawler consume a `--source-config` JSON
(produced by Knowledge_Graph's `requirement_to_source_config`) and run:

  Layer 1 (hardcoded authoritative sources first): for each dimension, build
    `site:<trusted-domain> <industry-topic>` queries from a static registry mapping
    each source class to representative trusted domains (CN / GLOBAL).

  Layer 2 (allowed_source_classes-driven dynamic discovery): for each dimension,
    build open-ended authoritative queries from the requirement's per-dimension
    required_source_classes (falling back to allowed_source_classes).

Both layers tag every query with a `dimension` so the crawl can enforce the
per-dimension >= 5 source floor and report per-dimension coverage.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Registry: source class -> representative trusted domains (the "hardcoded
# authoritative sources" the user wants read first). Reuses the spirit of
# Knowledge_Graph source_discovery.DEFAULT_TRUSTED_DOMAINS, kept local so
# geo-research stays self-contained and works for any industry.
SOURCE_CLASS_DOMAINS = {
    "government": [
        "gov.cn", "miit.gov.cn", "cac.gov.cn", "samr.gov.cn", "stats.gov.cn",
        "gov", "data.gov", "oecd.org", "worldbank.org", "imf.org",
    ],
    "regulator": ["cac.gov.cn", "pbc.gov.cn", "cbirc.gov.cn", "csrc.gov.cn", "sec.gov"],
    "standards_body": ["sac.gov.cn", "cnis.ac.cn", "iso.org", "ieee.org", "itu.int"],
    "industry_association": ["alic.org.cn", "caict.ac.cn", "cnii.com.cn", "csi.org.cn"],
    "industry_research": [
        "iresearch.com.cn", "analysys.cn", "199it.com", "idc.com", "gartner.com",
        "forrester.com", "caict.ac.cn", "leadleo.com", "ifenxi.com", "questmobile.com.cn",
    ],
    "academic": ["edu", "ac.cn", "edu.cn", "scholar.google.com", "arxiv.org"],
    "brokerage_research": [
        "cicc.com", "htsc.com", "eastmoney.com", "swsresearch.com", "research.cicc.com",
    ],
    "reliable_media": ["36kr.com", "huxiu.com", "21jingji.com", "chinanews.com", "thepaper.cn"],
    # Competitor-official domains are INDUSTRY-SPECIFIC (ERP vendors here are a
    # leftover from the e-commerce finance work and actively wrong for e.g.
    # gaming laptops). A global registry can't list every industry's vendors, so
    # keep this mapping EMPTY: competitor `site:` targeting must come from each
    # scope's seed_competitors, not from hardcoded vendor domains. Layer 2 and
    # the institutional domains below still discover competitors dynamically.
    "competitor_official": [],
    "company_disclosure": ["sec.gov", "hkexnews.hk", "sse.com.cn", "szse.cn"],
}

# Dimension keyword hints (for Layer-2 dynamic authority query phrasing).
DIMENSION_KEYWORDS = {
    "market_definition": ["定义", "边界", "标准", "definition", "scope"],
    "category_structure": ["品类", "子品类", "分类", "category", "taxonomy"],
    "market_participants": ["厂商", "参与者", "份额", "participant", "vendor", "market share"],
    "audience_and_decision_chain": ["用户", "决策链", "角色", "audience", "decision chain"],
    "problems_and_jobs": ["痛点", "需求", "任务", "pain point", "job to be done"],
    "use_cases": ["场景", "案例", "use case", "scenario"],
    "capabilities": ["能力", "功能", "模块", "capability", "feature"],
    "decision_factors": ["选型", "决策因素", "评估", "selection", "evaluation criteria"],
    "topics_and_questions": ["主题", "问题", "topic", "question"],
    "market_facts_and_trends": ["规模", "增长", "趋势", "market size", "growth", "trend"],
    "regulation_and_risks": ["法规", "政策", "风险", "合规", "regulation", "compliance", "risk"],
    "competition_structure": ["竞争", "竞品", "格局", "competition", "competitor"],
    "source_ecology": ["来源", "机构", "协会", "source", "institute", "association"],
    "evidence_gaps": ["缺口", "不足", "不确定", "gap", "evidence gap"],
}


def load_source_config(args) -> dict[str, Any]:
    """Read --source-config JSON if present, else return an empty config dict."""
    path = getattr(args, "source_config", None)
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def extract_dimensions(request: str, source_config: dict) -> list[str]:
    """Return the ordered list of dimensions from the config, else parse from the
    request's "请覆盖以下数据维度：N. <code>：..." block."""
    per_dim = (source_config.get("per_dimension_source_classes") or {})
    if per_dim:
        return list(per_dim.keys())
    dims: list[str] = []
    # Match lines like "1. market_definition：..." or "1. market_definition（期望：..."
    for line in request.splitlines():
        m = re.match(r"^\s*\d+[\.、]\s*([a-z_]+)\s*[：:（(]", line)
        if m:
            dims.append(m.group(1))
    return dims


def _domains_for_classes(source_classes: list[str]) -> list[str]:
    """Map a list of source classes to their trusted domains (Layer-1 site: targets)."""
    out: list[str] = []
    seen = set()
    for cls in source_classes:
        for domain in SOURCE_CLASS_DOMAINS.get(cls, []):
            if domain not in seen:
                seen.add(domain)
                out.append(domain)
    return out


def load_layer1_queries(topic: str, dims: list[str], source_config: dict, year: int) -> list[dict]:
    """Layer 1: hardcoded authoritative `site:` queries, one set per dimension.

    Each query is tagged with its dimension. We use the per-dimension required
    source classes (falling back to allowed_source_classes) to pick domains.
    """
    allowed = source_config.get("allowed_source_classes") or []
    per_dim = source_config.get("per_dimension_source_classes") or {}
    queries: list[dict] = []
    # Dedup key is (dimension, query) so a domain shared by several dimensions
    # still yields a hardcoded `site:` query for EACH dimension (we must not drop
    # a whole dimension's Layer-1 coverage just because an earlier dimension
    # already claimed that domain). To keep each dimension's `site:` query
    # DISTINCT (so downstream normalization/dedup can't collapse two dimensions'
    # same-domain queries into one), append the dimension's first keyword — e.g.
    #  site:iresearch.com.cn 游戏笔记本 市场规模 2026   (market_facts)
    #  site:iresearch.com.cn 游戏笔记本 厂商 2026      (market_participants)
    used: set = set()
    for dim in dims:
        classes = per_dim.get(dim) or allowed or ["industry_research", "reliable_media"]
        domains = _domains_for_classes(classes)
        kws = DIMENSION_KEYWORDS.get(dim)
        kw = (" " + kws[0]) if kws else ""  # dimension-specific hint
        # keep the top ~6 domains per dimension to bound the query count
        for domain in domains[:6]:
            q = f"site:{domain} {topic}{kw} {year}"
            key = (dim, q.casefold())
            if key in used:
                continue
            used.add(key)
            queries.append({"query": q, "dataset": "market", "dimension": dim})
    return queries


def load_layer2_queries(topic: str, dims: list[str], source_config: dict, year: int) -> list[dict]:
    """Layer 2: open-ended authoritative queries per dimension, driven by the
    requirement's allowed_source_classes (dynamic planning). Includes both a
    Chinese and an English authority phrasing so SearXNG/LLM can discover sources
    the hardcoded registry may not cover."""
    allowed = source_config.get("allowed_source_classes") or []
    per_dim = source_config.get("per_dimension_source_classes") or {}
    queries: list[dict] = []
    for dim in dims:
        classes = per_dim.get(dim) or allowed
        kws = DIMENSION_KEYWORDS.get(dim, [])
        kw = " ".join(kws[:3]) if kws else ""
        cls_zh = _class_zh(classes)
        q1 = f"{topic} {kw} 权威 {cls_zh} 报告 白皮书 标准 {year}".strip()
        q2 = f"{topic} {kw} {_class_en(classes)} authoritative report {year}".strip()
        queries.append({"query": q1, "dataset": "market", "dimension": dim})
        queries.append({"query": q2, "dataset": "academic", "dimension": dim})
    return queries


def per_dimension_required_classes(source_config: dict, dim: str) -> list[str]:
    per_dim = source_config.get("per_dimension_source_classes") or {}
    allowed = source_config.get("allowed_source_classes") or []
    return per_dim.get(dim) or allowed


def _class_zh(classes: list[str]) -> str:
    mapping = {
        "government": "政府 官方统计",
        "regulator": "监管机构",
        "standards_body": "标准机构 标准",
        "industry_association": "行业协会",
        "industry_research": "行业研究机构 报告",
        "academic": "学术",
        "brokerage_research": "券商研究",
        "reliable_media": "权威媒体",
        "competitor_official": "厂商官网",
        "company_disclosure": "公司披露 年报",
    }
    return " ".join(mapping.get(c, c) for c in classes) or "权威来源"


# ---------------------------------------------------------------------------
# Authoritative-domain gating for crawl selection.
#
# The user's rule: every crawl must use FIXED generic third-party authoritative
# domains PLUS self-planned authoritative domains for the CURRENT industry — and
# NO industry-specific hardcoded vendor domains. To make sources reach the
# per-dimension >=5 floor, the crawler should spend its page budget on records
# from those authoritative domains and skip obviously-irrelevant platform pages
# (real-estate, translators, video sites, marketplaces, portal redirects) that
# SearXNG often surfaces for `site:` queries.
# ---------------------------------------------------------------------------

# Flatten the two-layer & general authoritative registries into one host-suffix
# set used to judge whether a search result is a credible source to crawl.
AUTHORITATIVE_SUFFIXES: set[str] = set()
for _domains in SOURCE_CLASS_DOMAINS.values():
    for _d in _domains:
        AUTHORITATIVE_SUFFIXES.add(_d.lower())

# Generic trusted TLD/authority families that hold for any industry.
_EXTRA_AUTHORITATIVE = [
    "gov.cn", "gov", "edu.cn", "edu", "ac.cn", "ac.uk", "edu.hk", "edu.tw",
    "org.cn", "org", "mil.cn", "cnnic.cn",
]
AUTHORITATIVE_SUFFIXES.update(_EXTRA_AUTHORITATIVE)

# Hosts/substrings that are clearly NOT industry research — spending a crawl on
# them wastes the per-dimension budget. These are generic platform/utility sites,
# not industry-specific vendors.
IRRELEVANT_DOMAIN_HINTS = (
    "ke.com", "translate.", "fanyi.", "iqiyi", "youku.", "taobao", "tmall",
    "jd.com", "douyin", "bilibili.com/video", "tieba.", "zhihu.com/question",
    "nipic", "pages.dev", "github.io", "localhost", "w3.org",
)


def host_of(url: str) -> str:
    """Return the lowercase hostname of a URL, else ''."""
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def is_authoritative_record(record: dict) -> bool:
    """True if a search record's URL is from a trusted authoritative domain
    (fixed generic pool + self-planned current-industry domains from the
    source-config / `site:` query target)."""
    url = str(record.get("url") or record.get("final_url") or "")
    host = host_of(url)
    if not host:
        return False
    if any(hint in host for hint in IRRELEVANT_DOMAIN_HINTS):
        return False
    if any(host.endswith(s) or (s in host) for s in AUTHORITATIVE_SUFFIXES):
        return True
    # A `site:<target>` query whose result honors that domain is authoritative.
    query = str(record.get("query") or "")
    qm = re.search(r"\bsite:([^\s]+)", query, re.IGNORECASE)
    if qm:
        target = qm.group(1).lower().strip("/")
        if target and (host.endswith(target) or target in host or host in target):
            return True
    return False


def prioritize_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split records into (authoritative, non-authoritative) by
    ``is_authoritative_record``. Crawl selection should drain the authoritative
    list first so per-dimension coverage and the >=min_per_dim floor are met
    before any budget is spent on weaker pages."""
    auth, weak = [], []
    for record in records:
        (auth if is_authoritative_record(record) else weak).append(record)
    return auth, weak


def _class_en(classes: list[str]) -> str:
    mapping = {
        "government": "government statistics",
        "regulator": "regulator",
        "standards_body": "standards body",
        "industry_association": "industry association",
        "industry_research": "industry research report",
        "academic": "academic",
        "brokerage_research": "brokerage report",
        "reliable_media": "authoritative media",
        "competitor_official": "official vendor page",
        "company_disclosure": "company annual report disclosure",
    }
    return " ".join(mapping.get(c, c) for c in classes) or "authoritative sources"
