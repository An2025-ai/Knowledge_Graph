"""L2 pipeline: knowledge_fusion — 跨文档候选融合（方案 §8 / §11.1）。

读取该 profile（l2_industry）的 ``knowledge_candidates``，做实体消解 + 候选分组，
输出门禁候选实体与知识（§9.3）：
- 实体消解：同类型同名 mention 聚为 ``gate_candidate_entities``（含别名/证据聚合）
- 候选分组：relation/metric/statement/event 同主题聚为 ``gate_candidate_knowledge``
- 冲突检测：同 subject+predicate 不同 object/value → 分裂为冲突候选供 promotion review

复用 ``runtime.fusion.fusion_service``（确定性基线，不做 embedding/LLM 归并）。
"""
from __future__ import annotations

from typing import Any

from runtime.core.db import DB
from runtime.fusion.fusion_service import run_fusion


def run(db: DB, args) -> dict[str, Any]:
    from runtime.common.registry import get_common_registry

    profile_id = getattr(args, "profile_id", None) or "l2_industry"
    get_common_registry().require_profile(profile_id)
    layer = getattr(args, "layer", None) or "l2_industry"
    tenant_id = getattr(args, "tenant_id", None)

    return run_fusion(db, args, profile_id=profile_id, layer=layer, tenant_id=tenant_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="L2 cross-document knowledge fusion")
    parser.add_argument("--profile-id", default="l2_industry")
    parser.add_argument("--layer", default="l2_industry")
    parser.add_argument("--tenant-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with DB.from_env() as db:
        import json

        print(json.dumps(run(db, args), ensure_ascii=False, default=str))