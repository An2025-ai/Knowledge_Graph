"""Build LLM prompts from L1 schema profiles."""
from __future__ import annotations

from typing import Any

from engine.common.registry import get_common_registry


def _compact(value: str | None, *, limit: int = 140) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_entity_definitions(registry, entity_types: list[str], profile_id: str | None) -> str:
    lines: list[str] = []
    for type_code in entity_types:
        spec = registry.entity_metadata(type_code, profile_id)
        name = spec.get("canonical_name") or type_code
        definition = _compact(spec.get("definition"))
        owner = spec.get("owner_layer")
        group = spec.get("ontology_group")
        suffix = ""
        if owner or group:
            suffix = f"；owner={owner or 'unknown'}；group={group or 'unknown'}"
        lines.append(f"- {type_code}（{name}）：{definition}{suffix}")
    return "\n".join(lines)


def _format_relation_definitions(registry, relation_types: list[str], profile_id: str | None) -> str:
    lines: list[str] = []
    for relation in relation_types:
        spec = registry.relation_metadata(relation, profile_id)
        description = _compact(spec.get("description"))
        subject_types = ", ".join(spec.get("subject_types") or [])
        object_types = ", ".join(spec.get("object_types") or [])
        scope = spec.get("relation_scope")
        suffix = f"；scope={scope}" if scope else ""
        lines.append(f"- {relation}: {subject_types} -> {object_types}；{description}{suffix}")
    return "\n".join(lines)


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return title + "\n" + "\n".join(f"- {item}" for item in items)


def _format_semantic_terms(registry, profile_id: str | None) -> str:
    if profile_id not in {"l2_industry", "l3_brand"}:
        return ""
    meaning_key = "l2_meaning" if profile_id == "l2_industry" else "l3_meaning"
    lines = []
    for term in registry.semantic_terms():
        lines.append(
            f"- {term.get('display_name')}（{term.get('term')}）：{term.get(meaning_key)}"
        )
    return "\n".join(lines)


def _format_chains(chains: list[dict[str, Any]]) -> str:
    lines = []
    for chain in chains:
        path = " -> ".join(chain.get("path") or [])
        lines.append(
            f"- {chain.get('chain_id')}: {path}。目的：{chain.get('purpose')}。"
            f"抽取提示：{chain.get('prompt_instruction')}"
        )
    return "\n".join(lines)


def _format_dimensions(dimensions: list[dict[str, Any]]) -> str:
    lines = []
    for item in dimensions:
        lines.append(
            f"- {item.get('module')}：实体={', '.join(item.get('entity_types') or [])}；"
            f"关系={', '.join(item.get('relation_types') or [])}；"
            f"指标={', '.join(item.get('metrics') or [])}"
        )
    return "\n".join(lines)


def build_extraction_prompt(profile_id: str | None = None) -> str:
    registry = get_common_registry()
    entities = sorted(registry.entity_types(profile_id, extractable_only=True))
    relations = sorted(registry.relation_types(profile_id, extractable_only=True))
    statement_classes = sorted(registry.statement_classes(profile_id))
    profile_line = f"当前 schema profile: {profile_id}。禁止读取或推断其他层本体。"
    extraction_rules = registry.extraction_rules(profile_id)
    semantic_terms = _format_semantic_terms(registry, profile_id)
    narrative_chains = _format_chains(registry.narrative_chains(profile_id))
    layer_dimensions = _format_dimensions(registry.layer_dimensions(profile_id))
    output_rules = registry.prompt_output_rules()
    output_schema = registry.prompt_output_schema()
    include_rules = extraction_rules.get("include") or []
    exclude_rules = extraction_rules.get("exclude") or []
    assertion_guidance = extraction_rules.get("assertion_guidance") or []

    return f"""\
你是{extraction_rules.get("role", "知识抽取引擎")}。根据给定的 L1 本体和 schema profile 约束，从输入文本中抽取结构化知识。
{profile_line}
抽取焦点：{extraction_rules.get("focus", "当前层知识抽取")}。
只使用下列允许的实体类型和关系类型，不要自创新类型。所有事实、主张、观测和推断都必须能回到输入文本。

允许的实体类型：
{", ".join(entities)}

实体类型定义：
{_format_entity_definitions(registry, entities, profile_id)}

允许的关系类型：
{", ".join(relations)}

关系类型定义：
{_format_relation_definitions(registry, relations, profile_id)}

允许的陈述类别：
{", ".join(statement_classes)}

当前层语义：
{semantic_terms or "- 按当前 Profile 的本体定义处理。"}

模块化实体/关系/指标维度：
{layer_dimensions or "- 当前 profile 未配置模块化维度。"}

优先抽取：
{_format_list("", include_rules) or "- 文本直接支持、且符合当前 profile 的实体、关系和陈述。"}

不要抽取：
{_format_list("", exclude_rules) or "- 文本没有证据支持的信息。"}

叙事链：
{narrative_chains or "- 当前 profile 未配置专属叙事链；保持实体、关系和 statement 可追溯即可。"}

陈述分类规则：
{_format_list("", assertion_guidance) or "- fact/claim/observation/inference 按 L1 assertion 类型定义区分。"}

通用输出规则：
{_format_list("", output_rules)}

输出必须是 JSON，结构为：
{{
  "entities": [{{"id": "ent_<type>_<slug>", "type": "<type>", "canonical_name": "...", "aliases": []}}],
  "relations": [{{
    "level": "{profile_id or 'global'}",
    "subject": "<entity_id>",
    "relation": "<relation>",
    "object": "<entity_id>",
    "entity_type_subject": "<subject_type>",
    "entity_type_object": "<object_type>",
    "metric_name": "",
    "metric_value": "",
    "scope": "行业/品牌/产品/场景/区域/时间",
    "evidence_text": "",
    "source_doc": "",
    "confidence": 0.0
  }}],
  "statements": [{{
    "level": "{profile_id or 'global'}",
    "text": "...",
    "statement_class": "fact|claim|observation|inference",
    "metric_name": "",
    "metric_value": "",
    "scope": "行业/品牌/产品/场景/区域/时间",
    "evidence_text": "",
    "source_doc": "",
    "confidence": 0.0
  }}]
}}
推荐关系字段：{", ".join(output_schema.get("relations", []))}
推荐陈述字段：{", ".join(output_schema.get("statements", []))}
只抽取文本直接支持的内容。没有来源的推断标记为 inference，能力或品牌自述优先标记为 claim。
陈述的 statement_class 只能取上述"允许的陈述类别"之一（fact/claim/observation/inference），不得使用其他任意标签。
confidence 表示该陈述被上下文文本直接支持的程度（0~1）：文本明确给出的事实给高值，仅有文本间接支撑或推理给中值，文本未直接支持、属主观判断的给低值；没有可靠依据时请如实给低值，不要一律填 0.0 或 1.0。
"""
