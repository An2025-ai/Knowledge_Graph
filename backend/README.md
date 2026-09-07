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

The SQLite database defaults to `database/knowledge.db` under the application
root. Other runtime data defaults to `%LOCALAPPDATA%\BrandAtlas` on Windows.
Set `BRAND_ATLAS_DATA_DIR` or `BRAND_ATLAS_DATABASE_PATH` to use managed
locations during development or deployment.

The API is intentionally independent from the retired PostgreSQL/Neo4j
implementation under `legacy/`. It imports only dependency-light domain
primitives from `shared/`; this package is the embedded desktop runtime.

Document ingestion is implemented by `app/services/knowledge_pipeline.py`:
evidence units are turned into rule/optional-LLM candidates, normalized, fused,
resolved into entities, and persisted as SQLite graph rows. The module is a
fresh implementation and does not import the retired runtime.
