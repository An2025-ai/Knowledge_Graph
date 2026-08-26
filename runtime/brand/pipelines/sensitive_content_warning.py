"""L3 pipeline: sensitive_content_warning — 敏感内容提醒（方案 §10.2 / §11.2）。

原 original_file_gate 从「阻断」改为「只提醒不阻断」：对品牌文档正文扫描敏感/风险
标记（绝对化宣称、财务/认证高危、竞品贬低、合规线索等），输出
``warning_id / warning_type / severity(action)``，低/中/高三档分级写入
``content_inventory``（或单独警告），记录品牌上下文。

不阻断管线继续（promotion 阶段 §10.2 会依据这些警告额外记录
sensitive_warning_status / public_quote_risk / user_notice_required）。
"""
from __future__ import annotations

import os
import re
from typing import Any

from runtime.core.db import DB
from runtime.brand.pipelines._helpers import resolve_brand_context

# 风险标记：类型 -> 正则/关键词，severity 分级
_RISK_RULES: list[tuple[str, tuple[int, list[str]]]] = [
    ("absolute_claim", (2, [
        "唯一", "首个", "第一", "最全", "最准", "最好", "最佳", "名列前茅", "无可比拟",
    ])),
    ("financial_kpi", (2, [
        "ROI", "投资回报", "增长率", "市场份额", "营收", "利润率", "%提升", "省  ",
    ])),
    ("certification_claim", (2, [
        "认证", "资质", "ISO", "等保", "安全评估", "可信云",
    ])),
    ("competitor_denigration", (1, [
        "竞品", "短板", "优于对手", "竞对", "碾压", "吊打",
    ])),
    ("compliance_signal", (1, [
        "合规", "监管", "处罚", "诉讼", "召回", "资质受限",
    ])),
    ("customer_specific", (1, [
        "客户名", "招投标", "中标", "合同金额", "订单",
    ])),
]


def scan_risks(text: str) -> list[dict]:
    """Return [{warning_type, severity, matched, count}] for the text."""
    found: list[dict] = []
    seen: set[tuple] = set()
    for wtype, (severity, markers) in _RISK_RULES:
        hits = [m for m in markers if m.lower() in (text or "").lower()]
        if not hits:
            continue
        key = (wtype, severity)
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "warning_type": wtype,
            "severity": severity,
            "matched": hits,
            "count": len(hits),
        })
    return found


def _render_action(severity: int) -> str:
    if severity >= 2:
        return "review_before_publication"
    if severity == 1:
        return "flag_for_disclosure"
    return "note"


def run(db: DB, args) -> dict[str, Any]:
    ctx = resolve_brand_context(db, args)
    file_path = getattr(args, "file", None)
    if file_path and os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = getattr(args, "text", None) or ""

    warnings = scan_risks(text)
    dry_run = bool(getattr(args, "dry_run", False))

    if not dry_run and warnings:
        for i, w in enumerate(warnings):
            db.execute(
                "INSERT INTO content_inventory "
                "(id, tenant_id, document_id, content_type, attributes, status) "
                "VALUES (uuid_generate_v4(), %s, %s, 'sensitive_warning', %s::jsonb, 'active') "
                "ON CONFLICT DO NOTHING",
                (
                    ctx["tenant_id"], getattr(args, "document_id", None),
                    {
                        "warning_id": f"warn_{ctx['brand_key']}_{i}_{_render_action(w['severity'])}",
                        "warning_type": w["warning_type"],
                        "severity": w["severity"],
                        "action": _render_action(w["severity"]),
                        "matched": w["matched"],
                        "public_quote_risk": 1 if w["severity"] >= 2 else 0,
                        "user_notice_required": 1 if w["severity"] >= 2 else 0,
                    },
                ),
            )

    print(f"[sensitive_content_warning] {len(warnings)} warnings for "
          f"brand={ctx['brand_key']}")
    return {
        "pipeline": "sensitive_content_warning",
        "brand_id": ctx["brand_id"],
        "tenant_id": ctx["tenant_id"],
        "warning_count": len(warnings),
        "warnings": warnings,
        "actions": [{
            "warning_type": w["warning_type"],
            "severity": w["severity"],
            "action": _render_action(w["severity"]),
        } for w in warnings],
        "blocked": False,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 sensitive content warning pipeline")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--file", help="Path to source file to scan")
    parser.add_argument("--document-id", help="document_id to record onto")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args()

    with DB.from_env() as db:
        print(json.dumps(run(db, ns), ensure_ascii=False, indent=2, default=str))