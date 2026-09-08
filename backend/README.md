# Brand Atlas Local Backend

FastAPI service for the local-first application. The service listens only on
`127.0.0.1`, uses a per-process bearer token, stores data in SQLite, and runs
the knowledge pipeline in a small durable worker pool.

## Run

From the repository root:

```powershell
pip install -r requirements-desktop.txt
$env:BRAND_ATLAS_TOKEN = "dev-token"
python -m backend.main --host 127.0.0.1 --port 8787 --token dev-token
```

The SQLite database defaults to `%LOCALAPPDATA%\BrandAtlas\database\knowledge.db`
on Windows and the standard user data directory on other systems. Set
`BRAND_ATLAS_DATABASE_PATH` to override only the database file, or set
`BRAND_ATLAS_DATA_DIR` to override the complete data root. The database path
override has priority.

The API is intentionally independent from the retired PostgreSQL/Neo4j
implementation under `legacy/`. It imports only dependency-light domain
primitives from `shared/`; this package is the embedded desktop runtime.

Document ingestion is implemented by `app/application/services/knowledge_pipeline.py`:
evidence units are turned into rule/optional-LLM candidates, normalized, fused,
resolved into entities, and persisted as SQLite graph rows. The module is a
fresh implementation and does not import the retired runtime.
