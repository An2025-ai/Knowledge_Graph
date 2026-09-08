"""External Embedding API adapter and replaceable local vector boundary."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ...config import RuntimeSettings
from ..repositories import KnowledgeRepository
from ...runtime_settings import SettingsStore


class ExternalEmbeddingClient:
    """OpenAI-compatible /embeddings client; no local model dependency."""

    def __init__(self, settings: RuntimeSettings, api_key: str | None = None):
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.model = settings.embedding_model
        self.key_reference = settings.api_key_reference
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
        key = self.api_key
        if not key:
            try:
                import keyring

                key = keyring.get_password("BrandAtlas", self.key_reference)
            except Exception:
                key = os.getenv("BRAND_ATLAS_LLM_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def test_connection(self) -> None:
        if not self.base_url or not self.model:
            raise RuntimeError("请填写 Embedding Base URL 和模型名称")
        request = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps({"model": self.model, "input": ["Brand Atlas connection test"]}).encode("utf-8"),
            headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Embedding API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 Embedding API：{exc.reason}") from exc
        if not payload.get("data"):
            raise RuntimeError("Embedding API 已响应，但没有返回向量")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.base_url or not self.model:
            raise RuntimeError("Embedding base URL and model are not configured")
        request = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Embedding API HTTP {exc.code}: {detail}") from exc
        return [row["embedding"] for row in sorted(payload.get("data", []), key=lambda row: row.get("index", 0))]


class EmbeddingService:
    """Embedding use case; storage can later move from JSON to sqlite-vec."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        settings: RuntimeSettings | None = None,
        *,
        settings_store: SettingsStore | None = None,
    ):
        self.repository = repository
        self.settings_store = settings_store or SettingsStore(settings or RuntimeSettings())

    def index_units(self, units: list[dict[str, Any]]) -> int:
        settings = self.settings_store.snapshot()
        if settings.embedding_provider != "openai-compatible" or not units:
            return 0
        client = ExternalEmbeddingClient(settings)
        texts = [(unit.get("text") or "").strip() for unit in units]
        vectors = client.embed(texts)
        written = 0
        for unit, vector in zip(units, vectors):
            if vector:
                self.repository.save_embedding(
                    source_id=unit["unit_id"], source_type="evidence_unit",
                    model=client.model, vector=vector, embedded_text=unit["text"],
                )
                written += 1
        return written
