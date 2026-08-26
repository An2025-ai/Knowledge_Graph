"""L3 pipeline: knowledge_fusion — 跨文档候选融合（方案 §8 / §11.2）。

原 entity_resolution 升级为跨文档融合：读取该 profile（l3_brand）的
``knowledge_candidates``，做实体消解 + 候选分组 → 输出门禁候选实体与知识（§9.3）：
- 实体消解：同类型同名 mention 聚为 ``gate_candidate_entities``
- 候选分组：relation/metric/statement/event 同主题聚为 ``gate_candidate_knowledge``
- 冲突检测：同 subject+predicate 不同 object/value → 分裂为冲突候选供 promotion review

复用 ``runtime.fusion.fusion_service``（确定性基线）。tenant 来自品牌上下文（resolve_brand_context
保证 L3 RLS 可见）。
"""
from __future__ import annotations

from typing import Any

from runtime.core.db import DB
from runtime.brand.pipelines._helpers import resolve_brand_context
from runtime.fusion.fusion_service import run_fusion


def run(db: DB, args) -> dict[str, Any]:
    from runtime.common.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or "l3_brand"
    get_common_registry().require_profile(profile_id)
    layer = getattr(args, "layer", None) or "l3_brand"
    ctx = resolve_brand_context(db, args)
    tenant_id = ctx["tenant_id"]

    return run_fusion(db, args, profile_id=profile_id, layer=layer, tenant_id=tenant_id)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="L3 cross-document knowledge fusion")
    parser.add_argument("--brand", required=True, help="Brand key / id")
    parser.add_argument("--tenant", help="Tenant key")
    parser.add_argument("--profile-id", default="l3_brand")
    parser.add_argument("--layer", default="l3_brand")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        print(json.dumps(run(db, args), ensure_ascii=False, default=str))