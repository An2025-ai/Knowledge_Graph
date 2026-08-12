"""PostgreSQL access layer for Brand Atlas runtime executors.

Follows the conventions from database/publish.py:
- Connection via KG_DB_* env vars
- Optional psycopg2 import (fails gracefully for --dry-run / validation)
- ON CONFLICT ... DO UPDATE ... updated_at = NOW() upsert style
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor

    HAS_PSYCOPG2 = True
except ImportError:  # pragma: no cover
    psycopg2 = None
    Json = None
    RealDictCursor = None
    HAS_PSYCOPG2 = False


DB_CONFIG = {
    "host": os.environ.get("KG_DB_HOST", "localhost"),
    "port": int(os.environ.get("KG_DB_PORT", "5432")),
    "dbname": os.environ.get("KG_DB_NAME", "brand_atlas_kg"),
    "user": os.environ.get("KG_DB_USER", "kg_admin"),
    "password": os.environ.get("KG_DB_PASSWORD", "kg_admin_password"),
}


def json_dumps(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return json.dumps(obj, ensure_ascii=False)


def connect():
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")
    return psycopg2.connect(**DB_CONFIG)


class DB:
    """Thin wrapper providing upsert + query helpers with autocommit transactions."""

    def __init__(self, conn=None):
        self._conn = conn if conn is not None else connect()
        self._conn.autocommit = True

    @classmethod
    def from_env(cls):
        return cls()

    def close(self):
        if self._conn:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def _json(self, value: Any):
        if Json is None:
            raise RuntimeError("psycopg2 not installed")
        if isinstance(value, (dict, list)):
            return Json(value, dumps=json_dumps)
        return value

    def upsert(self, table: str, row: dict, key_field: str):
        """Insert-or-update a single row keyed by key_field (uniquely constrained)."""
        columns = list(row.keys())
        values = [self._json(row[c]) for c in columns]
        placeholders = ", ".join(["%s"] * len(columns))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key_field)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({key_field}) DO UPDATE SET {updates}, updated_at = NOW()"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, values)

    def execute(self, sql: str, params: tuple | None = None):
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def query(self, sql: str, params: tuple | None = None) -> list[dict]:
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def insert_returning_id(self, sql: str, params: tuple | None = None) -> Any:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

    @staticmethod
    def run_sql_file(conn, path: str):
        """Execute a .sql migration file in a single transaction."""
        if not HAS_PSYCOPG2:
            raise RuntimeError("psycopg2 not installed")
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def check_connection() -> bool:
    """Return True if PostgreSQL is reachable."""
    if not HAS_PSYCOPG2:
        print("[db] psycopg2 not installed")
        return False
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as e:  # pragma: no cover
        print(f"[db] connection failed: {e}")
        return False


if __name__ == "__main__":
    print("[db] checking PostgreSQL connection...")
    print("[db] OK" if check_connection() else "[db] FAILED")
