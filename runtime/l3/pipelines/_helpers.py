"""Shared helpers for L3 brand cognition pipelines.

These small utilities are used by several of the L3 pipeline executors so that
each pipeline stays focused on its own concern while sharing the plumbing that
is common to all of them:

- ``resolve_brand_context``: map the CLI ``--brand`` / ``--tenant`` args to a
  concrete ``tenant_id`` and ``brand_id`` (the brand ``entity`` UUID), creating
  the tenant / brand / brand_workspace rows as needed, and set the L3 RLS
  session variable (``app.tenant_id``) so L3 writes are visible under Row Level
  Security.
- ``upsert_entity``: insert-or-reuse an ``entity`` row keyed by the L2/L3
  business-unique index ``(tenant_id, entity_type, canonical_name, owner_brand)``.
- ``assertion_updates_allowed``: a context manager that temporarily disables
  non-replica triggers (including L3's append+supersedes ``trg_assertion_no_update``)
  for the current session only, so classification / promotion may refine an
  existing assertion row in place.
"""
from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from runtime.db import DB


# ---------------------------------------------------------------------------
# Brand / tenant context resolution
# ---------------------------------------------------------------------------

def _tenant_id(db: DB, tenant_key: str, tenant_name: str) -> str:
    """Find an existing tenant by tenant_key, else create it."""
    rows = db.query(
        "SELECT id FROM tenant WHERE tenant_key = %s LIMIT 1", (tenant_key,)
    )
    if rows:
        return rows[0]["id"]
    tid = db.insert_returning_id(
        "INSERT INTO tenant (id, name, tenant_key, status) "
        "VALUES (uuid_generate_v4(), %s, %s, 'active') RETURNING id",
        (tenant_name, tenant_key),
    )
    return tid


def _brand_entity_id(db: DB, tenant_id: str, brand_key: str) -> str:
    """Find or create the brand ``entity`` row for the tenant.

    The brand is stored as an ``entity`` of type ``brand`` scoped to the tenant
    (owner_brand NULL so it is the anchor "self" brand). Returns the entity UUID.
    """
    rows = db.query(
        "SELECT id FROM entity "
        "WHERE tenant_id = %s AND entity_type = 'brand' AND canonical_name = %s "
        "AND COALESCE(owner_brand, '') = '' LIMIT 1",
        (tenant_id, brand_key),
    )
    if rows:
        return rows[0]["id"]
    bid = db.insert_returning_id(
        "INSERT INTO entity "
        "(id, tenant_id, brand_id, entity_id, entity_type, canonical_name, "
        " scope, status, version) "
        "VALUES (uuid_generate_v4(), %s, NULL, %s, 'brand', %s, 'local', 'active', '1.0.0') "
        "RETURNING id",
        (tenant_id, f"ent_brand_{uuid.uuid4().hex[:12]}", brand_key),
    )
    return bid


def _ensure_brand_workspace(db: DB, tenant_id: str, brand_id: str, args) -> None:
    """Best-effort creation of a minimal brand_workspace row (idempotent)."""
    market = getattr(args, "market", None) or "CN"
    language = getattr(args, "language", None) or "zh-CN"
    access_level = getattr(args, "access_level", None) or "internal"
    exists = db.query(
        "SELECT 1 FROM brand_workspace "
        "WHERE tenant_id = %s AND brand_entity_id = %s AND market = %s AND language = %s LIMIT 1",
        (tenant_id, brand_id, market, language),
    )
    if exists:
        return
    try:
        db.execute(
            "INSERT INTO brand_workspace "
            "(id, tenant_id, brand_entity_id, market, language, default_access_level, "
            " onboarding_request, status) "
            "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s::jsonb, 'active')",
            (tenant_id, brand_id, market, language, access_level,
             '{"onboarding_status": "pipeline_executor"}'),
        )
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[helpers] brand_workspace create skipped: {exc}")


def resolve_brand_context(db: DB, args) -> dict[str, Any]:
    """Resolve ``--brand`` / ``--tenant`` into a usable brand context.

    Returns a dict with ``tenant_id``, ``tenant_key``, ``brand_id`` (the brand
    entity UUID) and ``brand_key``. Also sets the ``app.tenant_id`` session var
    so L3 RLS policies permit reads/writes for this tenant.
    """
    brand_key = getattr(args, "brand", None) or getattr(args, "brand_id", None)
    if not brand_key:
        raise ValueError("No brand provided. Pass --brand <brand_id|brand_name>.")
    brand_key = str(brand_key)

    tenant_key = getattr(args, "tenant", None) or getattr(args, "tenant_key", None) or "default"
    tenant_name = getattr(args, "tenant_name", None) or f"Tenant {tenant_key}"

    tid = _tenant_id(db, str(tenant_key), tenant_name)
    brand_id = _brand_entity_id(db, tid, brand_key)

    # L3 tables are RLS-protected on tenant_id; set the session tenant.
    db.execute("SET app.tenant_id = %s", (tid,))

    _ensure_brand_workspace(db, tid, brand_id, args)

    return {
        "tenant_id": tid,
        "tenant_key": str(tenant_key),
        "brand_id": brand_id,
        "brand_key": brand_key,
        "brand": brand_key,
    }


# ---------------------------------------------------------------------------
# Entity upsert (insert-or-reuse by business-unique key)
# ---------------------------------------------------------------------------

def upsert_entity(
    db: DB,
    tenant_id: str,
    brand_id: str | None,
    entity_type: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    owner_brand: str | None = None,
) -> tuple[str, str]:
    """Return ``(entity_uuid, entity_id)``, reusing an existing row or inserting.

    The reuse key is the L2/L3 business-unique index
    ``(tenant_id, entity_type, canonical_name, COALESCE(owner_brand, ''))``.
    When creating, ``owner_brand`` defaults to ``brand_id`` so brand-local
    entities are kept distinct from shared L2 entities.
    """
    owner = owner_brand if owner_brand is not None else brand_id
    rows = db.query(
        "SELECT id, entity_id FROM entity "
        "WHERE tenant_id = %s AND entity_type = %s AND canonical_name = %s "
        "AND COALESCE(owner_brand, '') = COALESCE(%s, '') LIMIT 1",
        (tenant_id, entity_type, canonical_name, owner),
    )
    if rows:
        return rows[0]["id"], rows[0]["entity_id"]

    slug = "".join(c for c in canonical_name.lower() if c.isalnum())[:40] or "unnamed"
    candidate = f"ent_{entity_type}_{slug}"
    if owner and db.query("SELECT 1 FROM entity WHERE entity_id = %s", (candidate,)):
        candidate = f"{candidate}_{str(owner)[:8]}"
    # guard against any residual collision on the entity_id (varchar) unique key
    while db.query("SELECT 1 FROM entity WHERE entity_id = %s", (candidate,)):
        candidate = f"{candidate}_{uuid.uuid4().hex[:4]}"

    aliases_json = aliases or []
    eid = db.insert_returning_id(
        "INSERT INTO entity "
        "(id, tenant_id, brand_id, entity_id, entity_type, canonical_name, "
        " owner_brand, scope, status, version, source_refs) "
        "VALUES (uuid_generate_v4(), %s, %s, %s, %s, %s, %s, 'local', 'active', '1.0.0', %s::jsonb) "
        "RETURNING id",
        (tenant_id, owner, candidate, entity_type, canonical_name, owner,
         {"aliases": aliases_json}),
    )
    # record aliases
    for alias in aliases_json:
        db.execute(
            "INSERT INTO entity_alias (id, entity_id, alias_name, alias_type, is_preferred) "
            "VALUES (uuid_generate_v4(), %s, %s, 'alt_label', FALSE) "
            "ON CONFLICT (entity_id, alias_name) DO NOTHING",
            (eid, alias),
        )
    return eid, candidate


# ---------------------------------------------------------------------------
# Assertion in-place updates (bypass the append+supersedes trigger) for the
# classification / promotion pipelines. Session-scoped only.
# ---------------------------------------------------------------------------

@contextmanager
def assertion_updates_allowed(db: DB):
    """Temporarily allow in-place assertion UPDATEs for this session.

    The L3 migration installs ``trg_assertion_no_update`` which raises on any
    ``UPDATE`` to ``assertion`` (append + supersedes only). Classification and
    promotion need to backfill ``assertion_kind`` / ``status`` in place, so we
    set ``session_replication_role = replica`` for the scope of the context
    manager (disables non-replica triggers for this session only) and restore it
    afterwards.
    """
    db.execute("SET session_replication_role = replica")
    try:
        yield
    finally:
        db.execute("SET session_replication_role = origin")


def update_assertion(db: DB, assertion_id: str, **fields: Any) -> None:
    """Update a single assertion row in place (trigger bypassed)."""
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [assertion_id]
    with assertion_updates_allowed(db):
        db.execute(f"UPDATE assertion SET {cols} WHERE id = %s", tuple(params))


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()