"""Shared LLM-assisted extraction helpers for L2/L3 executors.

Provides:
- load_llm(): build an LLMClient from runtime/config/llm-config.local.json
- extract_json(): call LLM with a system prompt and parse a JSON object
- extract_entities_relations(): the core "report/markdown -> entities+relations+statements"
"""
from __future__ import annotations

import json
from typing import Any

from runtime.llm_client import LLMClient, LLMConfig, extract_json_object
from runtime.extraction_schema import validate_extraction
from runtime.ontology_validator import validate_ontology


def load_llm(config_path=None) -> LLMClient:
    config = LLMConfig.from_file(config_path) if config_path else LLMConfig.from_file()
    return LLMClient(config)


def extract_json(client: LLMClient, system: str, user: str, *, max_tokens: int | None = None) -> dict:
    raw = client.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return extract_json_object(raw)


# ---------------------------------------------------------------------------
# Core extraction: text -> entities / relations / statements
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = """\
你是知识抽取引擎。根据给定的 L1 本体约束，从输入文本中抽取结构化知识。
只使用下列允许的实体类型和关系类型，不要自创新类型。

允许的实体类型：
brand, product, industry, category, audience, use_case, problem, topic,
competitor, capability, decision_factor, job_to_be_done, outcome, organization, product_version

允许的关系类型：
belongs_to, operates_in, serves, supports_use_case, solves, has_capability,
competes_with, alternative_to, has_topic, covers, targets, mentions,
has_problem, has_decision_factor, capability_supports_use_case, requires_capability,
produces_outcome, achieves_outcome, owns_brand, offers, version_of, supersedes

输出必须是 JSON，结构为：
{
  "entities": [{"id": "ent_<type>_<slug>", "type": "<type>", "canonical_name": "...", "aliases": []}],
  "relations": [{"subject": "<entity_id>", "relation": "<relation>", "object": "<entity_id>", "confidence": 0.0}],
  "statements": [{"text": "...", "statement_class": "fact|claim|observation|inference"}]
}
只抽取文本直接支持的内容。没有来源的推断标记为 inference、能力主张标记为 claim。
"""


def extract_entities_relations(
    client: LLMClient,
    text: str,
    *,
    max_tokens: int | None = None,
    validate: bool = True,
    retries: int = 1,
    on_error=None,
) -> dict[str, Any]:
    """Run structured extraction over a chunk of text.

    If `validate` is True, the LLM output is checked with Pydantic
    (extraction_schema) and the ontology (ontology_validator). Invalid output is
    repaired by re-prompting up to `retries` times; failures still return the
    raw parsed dict so downstream can decide. `on_error` is called with a message
    on each failed attempt (e.g. for metrics).
    """
    try:
        result = extract_json(client, EXTRACTION_SYSTEM, text, max_tokens=max_tokens)
    except (ValueError, json.JSONDecodeError) as exc:  # truncated/invalid JSON
        if on_error:
            on_error(f"json: {exc}")
        result = {}
    if not validate:
        return _normalized(result)

    for attempt in range(retries + 1):
        validation_errors: list[str] = []
        # Pydantic shape validation
        try:
            validated = validate_extraction(result)
        except Exception as exc:  # noqa: BLE001 - Pydantic ValidationError
            validation_errors.append(f"shape: {exc}")
        else:
            result = validated.model_dump(exclude_none=True)
            # Ontology business-rule validation
            v = validate_ontology(result)
            if not v.ok:
                validation_errors.extend(v.errors[:5])

        if not validation_errors:
            return _normalized(result)

        if on_error:
            on_error("; ".join(validation_errors))
        if attempt >= retries:
            return _normalized(result)
        # Repair: tell the LLM what was invalid and ask it to fix.
        reason = validation_errors[:6] if validation_errors else ["输出 JSON 不完整或被截断，请重新输出完整合法的 JSON"]
        repair_prompt = (
            text
            + "\n\n[校验失败] 上次输出字段类型/本体不合法或 JSON 不完整。请修正后重新按 JSON 输出：\n- "
            + "\n- ".join(reason)
        )
        try:
            result = extract_json(client, EXTRACTION_SYSTEM, repair_prompt, max_tokens=max_tokens)
        except (ValueError, json.JSONDecodeError) as exc:
            if on_error:
                on_error(f"json-repair: {exc}")
            result = {}
    return _normalized(result)


def _normalized(result: dict) -> dict[str, Any]:
    return {
        "entities": result.get("entities", []),
        "relations": result.get("relations", []),
        "statements": result.get("statements", []),
    }


def normalize_entity_id(type_: str, canonical_name: str, existing: set[str]) -> str:
    """Build a stable ent_<type>_<slug> id, deduping collisions by suffixing."""
    slug = "".join(c for c in canonical_name.lower() if c.isalnum())[:40] or "unnamed"
    base = f"ent_{type_}_{slug}"
    candidate = base
    i = 1
    while candidate in existing:
        candidate = f"{base}_{i}"
        i += 1
    existing.add(candidate)
    return candidate


if __name__ == "__main__":
    import sys

    client = load_llm()
    sample = "示例：某 CRM 品牌面向中小企业销售团队，解决销售线索分散问题，具备 AI 销售预测能力。"
    print(json.dumps(extract_entities_relations(client, sample), ensure_ascii=False, indent=2))