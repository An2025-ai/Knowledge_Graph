"""Migration executor — runs L1 + unified L2/L3 schema in dependency order.

Usage:
    python -m runtime.migrations migrate            # run all (L1 → L2/L3)
    python -m runtime.migrations migrate --only l2_l3  # run only one layer
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # Knowledge_Graph root

# 统一 database 口径：所有 L2/L3 + 候选向量表收进同一个 database/l2_l3_schema.sql。
# 旧的 l2_migration.sql / brand_l3_migration.sql / vector_migration.sql 已删除并并入。
MIGRATIONS = {
    "l1": ROOT / "database" / "schema.sql",
    "l2_l3": ROOT / "database" / "l2_l3_schema.sql",
}

ORDER = ["l1", "l2_l3"]


def run_layer(db, key: str):
    path = MIGRATIONS[key]
    if not path.exists():
        print(f"[migrate] SKIP {key}: {path.name} not found")
        return False
    print(f"[migrate] RUN {key} from {path.name} ...")
    db.run_sql_file(db._conn, str(path))
    print(f"[migrate] OK {key}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run L1 / L2/L3 migrations.")
    parser.add_argument("--only", choices=ORDER, help="run only this layer")
    parser.add_argument("--check", action="store_true", help="list migrations, don't run")
    args = parser.parse_args()

    if args.check:
        for key in ORDER:
            print(f"  {key}: {MIGRATIONS[key].resolve()}")
        return 0

    from runtime.core import db as dbmod

    if args.only:
        keys = [args.only]
    else:
        keys = ORDER

    with dbmod.DB() as db:
        for key in keys:
            run_layer(db, key)
    print("[migrate] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())