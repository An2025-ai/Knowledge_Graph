"""Embedding client with provider abstraction (OPTIMIZATION_TECH_PLAN.md §4.6/§10.4).

Default provider is "api" — calls the gateway's OpenAI-compatible /embeddings
endpoint. A "local" provider stub is provided for future bge-m3 via
sentence-transformers (requires HuggingFace download; not the default).

Config: runtime/config/model-config.local.json
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MODEL_CONFIG = Path(__file__).resolve().parent / "config" / "model-config.local.json"

# Default HuggingFace mirror. huggingface.co is unreachable on many CN networks;
# hf-mirror.com is a reachable mirror. Users can override via HF_ENDPOINT.
# If HF_ENDPOINT is not already set, default it to the mirror for model download.
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# Module-level cache so the (heavy, ~2GB) local bge model is loaded once per
# process, not once per EmbeddingClient / pipeline step.
_LOCAL_MODEL_CACHE: dict[str, Any] = {}


@dataclass
class EmbeddingConfig:
    provider: str = "api"
    model: str = "bge-m3"
    dimension: int = 1024
    base_url: str = ""
    api_key_env: str = "BRAND_ATLAS_LLM_API_KEY"

    @classmethod
    def from_file(cls, path: Path = DEFAULT_MODEL_CONFIG) -> "EmbeddingConfig":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        emb = payload.get("embedding", {})
        return cls(**{k: v for k, v in emb.items() if k in cls.__dataclass_fields__})


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig.from_file()
        self._model = None  # lazy-load cache for local provider

    def _api_key(self) -> str | None:
        return os.getenv(self.config.api_key_env)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a list of 1024-dim vectors for the given texts."""
        if self.config.provider == "api":
            return self._embed_api(texts)
        if self.config.provider == "local":
            return self._embed_local(texts)
        raise ValueError(f"unknown embedding provider '{self.config.provider}'")

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """bge-m3 via sentence-transformers (local, requires HF model download).

        Uses HF_ENDPOINT mirror (e.g. hf-mirror.com) if set, for networks that
        cannot reach huggingface.co directly.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "embedding provider 'local' requires sentence-transformers + torch. "
                "Run: pip install -r runtime/requirements-local-models.txt"
            ) from exc
        model_name = self.config.model or "BAAI/bge-m3"
        if self._model is None:
            # Reuse the module-level cached model if already loaded (same name).
            if _LOCAL_MODEL_CACHE.get(model_name) is not None:
                self._model = _LOCAL_MODEL_CACHE[model_name]
            else:
                self._model = SentenceTransformer(model_name)
                _LOCAL_MODEL_CACHE[model_name] = self._model
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    def _embed_api(self, texts: list[str]) -> list[list[float]]:
        if not self.config.base_url:
            raise RuntimeError("embedding base_url not set in model-config.local.json")
        url = self.config.base_url.rstrip("/") + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if key := self._api_key():
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": self.config.model, "input": texts}
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"embedding API HTTP {exc.code}: {detail}") from exc
        data = payload.get("data", [])
        # data may come back unordered; sort by index.
        data = sorted(data, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()


# ---------------------------------------------------------------------------
# Persist embeddings into the pgvector tables
# (entity_embedding / evidence_embedding / assertion_embedding — see
# runtime/migrations/vector_migration.sql). These are called right after a
# source row is created so the HNSW indexes can be used for `<=>` retrieval.
# psycopg2 renders a Python list as the textual vector literal `[0.1,...]`,
# which pgvector accepts directly.
# ---------------------------------------------------------------------------

# Valid vector tables -> primary-key column name (both shared by all three).
_EMBEDDING_TABLES = {
    "entity_embedding": "entity_id",
    "evidence_embedding": "evidence_id",
    "assertion_embedding": "assertion_id",
}


def write_embedding(
    db,
    table: str,
    pk_value,
    text: str,
    tenant_id,
    model: str = "BAAI/bge-m3",
) -> list[float] | None:
    """Embed ``text`` and persist into ``table`` (idempotent ON CONFLICT DO UPDATE).

    Returns the vector on success, or None on any embedding/provider failure so
    the caller (a pipeline write) is never blocked by the optional vector layer.
    ``db`` is a ``runtime.db.DB``; ``pk_value`` is the source row UUID.
    """
    pk_col = _EMBEDDING_TABLES.get(table)
    if pk_col is None:
        raise ValueError(f"unknown embedding table '{table}'")
    try:
        vec = get_embedding_client().embed_one(text)
    except Exception:  # noqa: BLE001 - optional layer, never break caller
        return None
    db.execute(
        f"INSERT INTO {table} ({pk_col}, tenant_id, embedding_model, embedding, embedded_text) "
        "VALUES (%s, %s, %s, %s, %s) "
        f"ON CONFLICT ({pk_col}) DO UPDATE SET "
        "embedding=EXCLUDED.embedding, embedded_text=EXCLUDED.embedded_text, "
        "embedding_model=EXCLUDED.embedding_model, tenant_id=EXCLUDED.tenant_id, "
        "updated_at=NOW()",
        (pk_value, tenant_id, model, vec, text),
    )
    return vec


def write_embeddings_batch(
    db,
    table: str,
    rows: list[dict],
    model: str = "BAAI/bge-m3",
) -> int:
    """Batch variant: ``rows`` is a list of {"id": uuid, "text": str, "tenant_id": ?}.
    Embeds all texts in one call, then persists each with one upsert. Returns the
    number written on success (0 if the embedding layer is unavailable)."""
    pk_col = _EMBEDDING_TABLES.get(table)
    if pk_col is None:
        raise ValueError(f"unknown embedding table '{table}'")
    valid = [r for r in rows if r.get("id") and (r.get("text") or "").strip()]
    if not valid:
        return 0
    texts = [(r["text"] or "").strip() for r in valid]
    try:
        vecs = get_embedding_client().embed(texts)
    except Exception:  # noqa: BLE001 - optional layer
        return 0
    for r, vec in zip(valid, vecs):
        db.execute(
            f"INSERT INTO {table} ({pk_col}, tenant_id, embedding_model, embedding, embedded_text) "
            "VALUES (%s, %s, %s, %s, %s) "
            f"ON CONFLICT ({pk_col}) DO UPDATE SET "
            "embedding=EXCLUDED.embedding, embedded_text=EXCLUDED.embedded_text, "
            "embedding_model=EXCLUDED.embedding_model, tenant_id=EXCLUDED.tenant_id, "
            "updated_at=NOW()",
            (r["id"], r.get("tenant_id"), model, vec, r["text"]),
        )
    return len(valid)


if __name__ == "__main__":
    c = get_embedding_client()
    print("embedding provider:", c.config.provider, "model:", c.config.model)
    try:
        vec = c.embed_one("DeepCleer 多法人合并核算")
        print("向量维度:", len(vec), "前3:", vec[:3])
    except Exception as e:
        print("embedding 调用失败:", e)