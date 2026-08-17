# -*- coding: utf-8 -*-
"""Seed a few shared L2 capability entities so the L3 l2_mapping step can produce
cross-layer (L3 brand capability -> shared L2 capability) brand_mapping edges.

The shared L2 layer currently lacks these as `capability` type (they exist as
`outcome` or not at all), so l2_mapping (which matches capability->capability)
finds nothing. We insert representative shared L2 capabilities with tenant_id NULL
(the cross-tenant shared layer), scope='shared', owner_brand NULL — the exact
shape _find_l2_entity looks for.
"""
import sys
sys.path.insert(0, r"d:\Brand Atlas\Knowledge_Graph")
from runtime.db import DB

SHARED_CAPS = [
    "多法人合并核算",
    "自动对账",
    "内部交易抵消",
    "财务报表生成",
    "自动结转损益",
    "数据采集",
    "实时分析",
    "智能体编排",
    "私有化部署",
    "数据加密",
]

with DB.from_env() as db:
    for name in SHARED_CAPS:
        # idempotent: skip if a shared capability with this name already exists
        exists = db.query(
            "SELECT id FROM entity WHERE tenant_id IS NULL AND entity_type='capability' "
            "AND owner_brand IS NULL AND canonical_name = %s LIMIT 1",
            (name,),
        )
        if exists:
            print(f"skip (exists): {name}")
            continue
        slug = "".join(c for c in name.lower() if c.isalnum())[:36]
        db.execute(
            "INSERT INTO entity "
            "(id, tenant_id, entity_id, entity_type, canonical_name, owner_brand, "
            " scope, status, version) "
            "VALUES (uuid_generate_v4(), NULL, %s, 'capability', %s, NULL, "
            " 'shared', 'active', '1.0.0')",
            (f"ent_l2_cap_{slug}", name),
        )
        print(f"seeded shared L2 capability: {name}")
