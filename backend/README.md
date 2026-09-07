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

The default user data directory is `%LOCALAPPDATA%\BrandAtlas` on Windows.
Set `BRAND_ATLAS_DATA_DIR` to use another directory during development.

The API is intentionally independent from the legacy PostgreSQL/Neo4j
execution path under `legacy/`. It imports only dependency-light domain
primitives from `shared/`; this package is the embedded desktop adapter.
