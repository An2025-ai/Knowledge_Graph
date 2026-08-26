"""Shared L1-aware candidate extraction: evidence_unit text → knowledge_candidates (方案 §6).

L2 与 L3 各自的 ``candidate_extraction.py`` pipeline 复用这里，统一走：
    NER 批量识别 → 正则/规则识别数值/时间/单位/关系触发词 → 映射 L1 ontology/extraction_rules
    → 过滤无关系的 unit → LLM 在 L1 约束下做结构化抽取（可选）→ 向量化（下游）→ 带溯源入库

纪律（§6.3 / §12 成本控制）：
- 正则/规则全量跑、成本最低；NER 批量跑；LLM 只做高价值结构化抽取。
- ``pre_extract`` 是纯函数、无模型依赖，规则内联在代码（不再读旧 brand_knowledge/rules
  或 dictionaries YAML——那些旧配置文件已删除；§5.3 不再提前建大词典）。
- 产物保留溯源：document_id / evidence_unit_id / source_span_ids / published_at /
  original_url / content_hash / evidence_text（§3.0，文章撤稿可追踪）。
"""
from __future__ import annotations

import json
import re
from typing import Any
from engine.core.db import DB

# ---------------------------------------------------------------------------
# 通用规则提取（内联正则，无外部词典依赖）
# ---------------------------------------------------------------------------

# 数值 + 单位（百分比、货币、数量级）
_NUM_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|％|亿元人民币|亿元|万元|万|亿|美元|元|人|家|个|台|套|项|倍)"
)
# 日期/时间
_DATE_RE = re.compile(r"\b(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})?日?|20\d{2}年(?:第[一二三四]?季度|上半年|下半年)\b")
# 版本号
_VERSION_RE = re.compile(r"\b[Vv](\d+(?:\.\d+)+)\b|\b(\d+\.\d+\.\d+)\b")
# 认证/资质（常见）
_CERT_RE = re.compile(
    r"(ISO\s*27001|ISO\s*27002|ISO\s*27017|ISO\s*27018|ISO\s*9001|"
    r"等保三级|国家高新技术企业|CMMI\s*[0-9]|SOC\s*2|可信云|云服务安全评估)"
)
# URL
_URL_RE = re.compile(r"https?://[^\s，。；]+")
# 关系触发词（§6.3.3：支持/提供/拥有/面向/聚焦 等显式关系）
_RELATION_TRIGGERS = [
    ("offers", "提供|推出|上线|发布|支持"),
    ("capability", "具备|拥有|支持能力|具备能力"),
    ("certification", "获得|取得|通过|认证"),
    ("targets", "面向|服务|针对|覆盖"),
]

_RULES = [
    ("numeric_metric", _NUM_UNIT_RE, "", 0.85),
    ("date", _DATE_RE, "", 0.9),
    ("version", _VERSION_RE, "version", 0.9),
    ("certification", _CERT_RE, "certification", 0.9),
    ("url", _URL_RE, "", 0.95),
]


def rule_candidates(text: str) -> list[dict]:
    """Deterministic regex candidates for numeric/date/version/certification/url."""
    out: list[dict] = []
    for name, rx, payload_key, conf in _RULES:
        for m in rx.finditer(text):
            value = m.group(0)
            payload = {"value": value, "type": name}
            if payload_key:
                payload["name"] = value
            out.append({
                "candidate_type": "metric" if name == "numeric_metric" else
                                  ("statement" if name == "date" else name),
                "candidate_payload": payload,
                "confidence": conf,
                "generator": f"regex:{name}",
            })
    return out


def relation_trigger_candidates(text: str) -> list[dict]:
    """显式关系触发词 → 提示候选含 relation（真正 LLM/归一后落到 knowledge_candidates）。"""
    out: list[dict] = []
    for rel, pattern in _RELATION_TRIGGERS:
        if re.search(rf"({pattern})", text):
            out.append({
                "candidate_type": "relation",
                # trigger + type 双键：`build_candidate_rows` 读 payload.get("type") 构造
                # predicate.type（knowledge_candidates.predicate），缺 type 会让融合/晋级
                # 的关系谓词全部为 None（审查 Critical #4）。
                "candidate_payload": {"trigger": rel, "type": rel},
                "confidence": 0.6,
                "generator": f"regex:trigger:{rel}",
            })
    return out


# ---------------------------------------------------------------------------
# NER 预筛（可选，PaddleNLP）。映射到 L1 允许的实体类型，否则丢弃（§6.3.2）。
# ---------------------------------------------------------------------------

# 通用 NER 标签 → L1 类型白名单（L2/L3 ontology 共用的部分）
_NER_TYPE_MAP = {
    "organization": "organization", "org": "organization", "company": "organization",
    "product": "product", "product_name": "product",
    "capability": "capability", "function": "capability", "feature": "capability",
    "certification": "certification", "cert": "certification",
    "audience": "audience", "customer": "customer", "person": "customer",
}


def ner_candidates(text: str, ner_client) -> list[dict]:
    """Run the optional NER layer; map to L1 entity types, drop unmatched (person→drop)."""
    out: list[dict] = []
    try:
        for ent in ner_client.named_entities(text):
            ctype = _NER_TYPE_MAP.get(str(ent.get("type", "")).lower())
            if not ctype or not ent.get("text"):
                continue
            out.append({
                "candidate_type": "entity",
                "candidate_payload": {"name": ent["text"], "entity_type": ctype},
                "confidence": round(float(ent.get("score", 0.7)), 3),
                "generator": f"paddlenlp:ner:{ctype}",
            })
    except Exception:  # noqa: BLE001 - optional layer, never break caller
        pass
    return out


def pre_extract(text: str, ner_client=None, profile_id: str = "l2_industry") -> list[dict]:
    """Run rule + (optional) NER prescreen, filtered to L1 ontology (default l2)."""
    from engine.common.registry import get_common_registry

    allowed_types = set(get_common_registry().entity_types(profile_id)) | {
        "metric", "statement", "relation"
    }
    cands = rule_candidates(text) + relation_trigger_candidates(text)
    if ner_client is not None:
        cands += ner_candidates(text, ner_client)
    # 过滤掉不在 L1 ontology 的实体候选
    kept = []
    for c in cands:
        if c["candidate_type"] in ("entity", "relation", "metric", "statement"):
            kind = c["candidate_payload"].get("entity_type", c["candidate_type"])
            if c["candidate_type"] == "entity" and kind not in allowed_types:
                continue
            c = dict(c)
            c["candidate_payload"] = dict(c["candidate_payload"])
            c["candidate_payload"]["entity_type"] = kind
            kept.append(c)
        else:
            kept.append(c)
    return kept


# ---------------------------------------------------------------------------
# 候选知识生成（将预筛/LLM 结果落成 knowledge_candidates 写行，§6.3.5）
# ---------------------------------------------------------------------------

def build_candidate_rows(
    context: dict,
    ev_unit: dict,
    candidates: list[dict],
    *,
    max_rows: int = 12,
) -> list[dict]:
    """Turn prescreen/LLM candidate dicts into knowledge_candidate write-rows.

    ``context`` carries document/provenance: document_uuid, profile_id, layer,
    published_at, original_url, content_hash. ``ev_unit`` carries evidence fields
    (evidence_unit_id, source_span_ids, text).
    """
    from engine.core.knowledge_service import stable_hash

    rows: list[dict] = []
    seen: set[str] = set()
    doc_uuid = context["document_uuid"]
    evidence_text = context.get("evidence_text") or (ev_unit.get("text") or "")
    for cand in candidates:
        ctype = cand["candidate_type"]
        payload = cand.get("candidate_payload") or {}
        if ctype == "entity":
            # 实体预筛本身不落成知识候选，交给归一化/融合作实体；此处跳过避免噪音
            continue
        method = cand.get("generator", "regex")
        suffix_keys = (ctype, method, str(payload.get("name") or payload.get("value") or
                                          payload.get("trigger") or ""))
        cand_id = f"KC_{context.get('document_id') or 'doc'}_{stable_hash(*suffix_keys)}"
        if cand_id in seen:
            continue
        seen.add(cand_id)
        subject = {"entity_type": payload.get("entity_type"), "name": payload.get("name")}
        row = {
            "candidate_id": cand_id,
            "profile_id": context["profile_id"],
            "layer": context["layer"],
            "document_uuid": doc_uuid,
            "evidence_unit_id": ev_unit.get("unit_id"),
            "source_span_ids": ev_unit.get("source_span_ids", []),
            "candidate_type": _map_candidate_type(ctype),
            "subject": subject,
            "predicate": {"type": payload.get("type")} if ctype in ("relation",) else None,
            "object": {},
            "metric": payload if ctype in ("metric", "numeric_metric") else None,
            "statement": {"text": payload.get("value", "")} if ctype == "statement" else None,
            "event": None,
            "evidence_text": evidence_text[:4000],
            "confidence": cand.get("confidence", 0.5),
            "extraction_method": [method],
            "schema_valid": True,
            "published_at": context.get("published_at"),
            "original_url": context.get("original_url"),
            "content_hash": context.get("content_hash"),
        }
        rows.append(row)
        if len(rows) >= max_rows:
            break
    return rows


def _map_candidate_type(ctype: str) -> str:
    mapping = {
        "numeric_metric": "metric",
        "certification": "statement",
        "date": "event",
        "version": "statement",
        "url": "statement",
        "trigger:relation": "relation",
    }
    if ctype in ("relation", "metric", "statement", "event"):
        return ctype
    return mapping.get(ctype, "statement")


# ---------------------------------------------------------------------------
# Pipeline run 辅助：批量把 evidence_units 产出候选并落库
# ---------------------------------------------------------------------------

def extract_and_store(
    db: DB,
    context: dict,
    units: list[dict],
    *,
    ner_client=None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """For each evidence_unit: prescreen → candidates → upsert knowledge_candidates.

    Returns counts. LLM structured extraction is intentionally left to the
    per-layer pipeline (it needs a live client); this service guarantees the
    deterministic rule/NER baseline always lands, so the pipeline is testable
    without an LLM connection.
    """
    from engine.core.knowledge_service import upsert_knowledge_candidate

    total = 0
    ner_count = 0
    for unit in units:
        text = unit.get("text", "")
        cands = pre_extract(text, ner_client=ner_client, profile_id=context["profile_id"])
        if not cands:
            continue
        per_unit = {
            "unit_id": unit.get("unit_id"),
            "source_span_ids": unit.get("source_span_ids", []),
            "text": text,
        }
        rows = build_candidate_rows(context, per_unit, cands)
        for r in rows:
            if any("paddlenlp:ner" in m for m in r["extraction_method"]):
                ner_count += 1
            if dry_run:
                total += 1
                continue
            upsert_knowledge_candidate(db, r)
            total += 1
    return {"candidate_count": total, "ner_count": ner_count}


if __name__ == "__main__":
    print(json.dumps(pre_extract(
        "该平台支撑 12 亿元营收，获得 ISO 27001 认证，覆盖 800 家客户。V2.1 版已发布。",
        profile_id="l2_industry"), ensure_ascii=False, indent=1))