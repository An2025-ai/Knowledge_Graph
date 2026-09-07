"""Brand Atlas local application backend.

The backend is intentionally independent from the legacy PostgreSQL/Neo4j
runtime under :mod:`legacy`.  It provides the desktop application's local
HTTP boundary and uses SQLite as the local source of truth.
"""

__all__ = ["create_app"]


def create_app():
    from backend.app import create_app as _create_app

    return _create_app()
