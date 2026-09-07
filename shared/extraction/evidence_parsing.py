"""Shared evidence parsing: raw text → evidence_spans → evidence_units (方案 §4/§5).

L2 与 L3 各自的 ``content_parsing`` / ``evidence_unit_merge`` pipeline 复用这里：
- ``parse_to_span_rows``: 把 markdown/纯文本正文切成 evidence_span（heading / paragraph /
  list_item / table / caption），并计算 heading_path / order_index / char 定位（§4）。
- ``merge_spans_to_units``: 用结构规则把相邻 span 合并为 evidence_unit（§5.2.1），
  记录 merge_reason；小 LLM 合并判断为可选（§5.2.2），默认只做结构合并以控成本。

不做过深语义判断（§3.2：evidence span/unit 生成不是语义分类）。
"""
from __future__ import annotations

import re
from typing import Any


# 行内标题匹配（markdown）：# 一级 ... ###### 六级
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# 列表项（- / * / 1. ）用于 span_type=list_item
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$")
# 中文句号/分号/换行分隔，用于把大段切成可抽取单元
_SENTENCE_SPLIT = re.compile(r"(?<=[。；!？])")

FORMAT_KEYS = ("markdown", "md")


def is_markdown(mime_type: str = "", filename: str = "") -> bool:
    mime = (mime_type or "").lower()
    name = (filename or "").lower()
    return mime in FORMAT_KEYS or name.endswith((".md", ".markdown"))


def _heading_depth(line: str) -> int | None:
    m = _HEADING_RE.match(line)
    return len(m.group(1)) if m else None


def _list_text(line: str) -> str | None:
    m = _LIST_RE.match(line)
    return m.group(3).strip() if m else None


def _blank(line: str) -> bool:
    return not line.strip()


def parse_to_span_rows(text: str, *, span_prefix: str = "ES") -> list[dict]:
    """Split ``text`` into evidence_span write-rows (§4.2 span_type taxonomy).

    Returns a list of dicts carrying span fields minus document_uuid, which the
    caller merges in before calling upsert_evidence_span.
    """
    raw_lines = text.splitlines()
    active_path: list[str] = []
    spans: list[dict] = []
    order = 0
    char_offset = 0

    heading_regex = _HEADING_RE
    for raw in raw_lines:
        line = raw.rstrip()
        if _blank(line):
            char_offset += len(raw) + 1
            continue
        depth = _heading_depth(line)
        if depth is not None:
            title = heading_regex.match(line).group(2).strip()
            # 重置当前标题路径：深度 <= 现有层时裁剪
            while len(active_path) >= depth:
                active_path.pop()
            active_path.append(title)
            spans.append(_span("heading", title, active_path[:], order,
                               char_offset, char_offset + len(title), line))
            order += 1
            char_offset += len(raw) + 1
            continue

        list_text = _list_text(line)
        if list_text is not None:
            spans.append(_span("list_item", list_text, active_path[:], order,
                               char_offset, char_offset + len(raw), line))
            order += 1
            char_offset += len(raw) + 1
            continue

        # 段落：表格、代码块里的行不额外标注，统一按 paragraph 处理
        spans.append(_span("paragraph", line.strip(), active_path[:], order,
                           char_offset, char_offset + len(raw), line))
        order += 1
        char_offset += len(raw) + 1

    # 给 span 加稳定 id
    for i, sp in enumerate(spans):
        sp["span_id"] = f"{span_prefix}_{i:05d}"
    return spans


def _span(span_type: str, text: str, heading_path: list[str], order: int,
          char_start: int, char_end: int, raw_line: str) -> dict:
    return {
        "span_id": "",  # filled by caller
        "span_type": span_type,
        "text": text[:4000],
        "heading_path": heading_path,
        "order_index": order,
        "char_start": char_start,
        "char_end": char_end,
        "locator": {"raw": raw_line[:4000], "char_start": char_start},
    }


def merge_spans_to_unit_rows(spans: list[dict], *, unit_prefix: str = "EU") -> list[dict]:
    """Group consecutive evidence spans into evidence_unit rows (§5.2.1 structure).

    Merging rule (structure-first): spans under the same heading, or a list item
    immediately following its paragraph, are folded into one unit when their
    combined text is still token-cheap (< ~120 tokens), so each unit carries
    enough context for L1-aware extraction without over-slicing (§4.4). Otherwise
    each span becomes its own unit.
    """
    units: list[dict] = []
    buffer: list[dict] = []
    buffer_text: list[str] = []
    last_heading_path: list[str] | None = None

    def flush():
        if buffer:
            reasons = _merge_reason(buffer)
            units.append({
                "unit_id": f"{unit_prefix}_{len(units):05d}",
                "source_span_ids": [b["span_id"] for b in buffer],
                "text": "".join(buffer_text).strip()[:8000],
                "heading_path": buffer[0].get("heading_path", []) or [],
                "merge_reason": reasons,
                "token_count": _token_estimate("".join(buffer_text)),
            })
        buffer.clear()
        buffer_text.clear()

    for span in spans:
        is_fragment = span["span_type"] in ("list_item", "table", "caption")
        heading_changed = (span.get("heading_path") != last_heading_path and buffer)
        if buffer and (heading_changed or (_token_estimate("".join(buffer_text)) >= 120)):
            flush()
        if is_fragment and buffer:
            # 同一 heading 下的列表项/表格追加到当前段落，增强上下文
            buffer.append(span)
            buffer_text.append(span["text"])
            last_heading_path = span.get("heading_path")
            continue
        buffer.append(span)
        buffer_text.append(span["text"])
        last_heading_path = span.get("heading_path")
    flush()
    return units


def _merge_reason(buffer: list[dict]) -> list[str]:
    if len(buffer) <= 1:
        return []
    reasons = []
    if _same_heading(buffer):
        reasons.append("same_heading")
    if any(b["span_type"] == "list_item" for b in buffer):
        reasons.append("list_context")
    return reasons


def _same_heading(buffer: list[dict]) -> bool:
    paths = {tuple(b.get("heading_path") or []) for b in buffer}
    return len(paths) == 1


def _token_estimate(text: str) -> int:
    # 中文约 1 字 ≈ 0.6 token；英文按词。简单估算供切分阈值用。
    cn = len(re.findall(r"[一-鿿]", text))
    en_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return int(cn * 0.6 + en_words)


if __name__ == "__main__":
    sample = """# 产品概览
DeepCleer 深澈智算平台支持多法人合并核算。
- 面向中小企业财务团队
- 提供 AI 销售预测

## 技术能力
具备 ISO 27001 认证与私有化部署能力。"""
    rows = parse_to_span_rows(sample)
    print("spans:", [(r["span_type"], r["text"][:20]) for r in rows])
    print("units:", len(merge_spans_to_unit_rows(rows)))
