"""Local application configuration and user-data paths.

Program files and user data are deliberately separated.  The default data
directory is under ``LOCALAPPDATA`` on Windows and can be overridden with
``BRAND_ATLAS_DATA_DIR`` for development or managed deployments.
"""

from __future__ import annotations

import os
import secrets
import json
from dataclasses import dataclass
from pathlib import Path


def default_data_dir() -> Path:
    configured = os.getenv("BRAND_ATLAS_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    if os.name == "nt":
        root = os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(root) / "BrandAtlas"
    return Path.home() / ".local" / "share" / "BrandAtlas"


@dataclass(frozen=True)
class AppPaths:
    root: Path
    database: Path
    documents: Path
    vectors: Path
    cache: Path
    logs: Path
    backups: Path
    config: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        root = default_data_dir()
        return cls(
            root=root,
            database=root / "database" / "knowledge.db",
            documents=root / "documents",
            vectors=root / "vectors",
            cache=root / "cache",
            logs=root / "logs",
            backups=root / "backups",
            config=root / "config",
        )

    def ensure(self) -> "AppPaths":
        for path in (
            self.root,
            self.database.parent,
            self.documents,
            self.vectors,
            self.cache,
            self.logs,
            self.backups,
            self.config,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class RuntimeSettings:
    host: str = "127.0.0.1"
    port: int = 8787
    token: str = ""
    llm_provider: str = "none"
    llm_base_url: str = ""
    llm_model: str = ""
    embedding_provider: str = "none"
    embedding_base_url: str = ""
    embedding_model: str = ""
    api_key_reference: str = "brand-atlas/default"

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        token = os.getenv("BRAND_ATLAS_TOKEN") or secrets.token_urlsafe(32)
        return cls(
            host=os.getenv("BRAND_ATLAS_HOST", "127.0.0.1"),
            port=int(os.getenv("BRAND_ATLAS_PORT", "8787")),
            token=token,
            llm_provider=os.getenv("BRAND_ATLAS_LLM_PROVIDER", "none"),
            llm_base_url=os.getenv("BRAND_ATLAS_LLM_BASE_URL", ""),
            llm_model=os.getenv("BRAND_ATLAS_LLM_MODEL", ""),
            embedding_provider=os.getenv("BRAND_ATLAS_EMBEDDING_PROVIDER", "none"),
            embedding_base_url=os.getenv("BRAND_ATLAS_EMBEDDING_BASE_URL", ""),
            embedding_model=os.getenv("BRAND_ATLAS_EMBEDDING_MODEL", ""),
            api_key_reference=os.getenv(
                "BRAND_ATLAS_API_KEY_REFERENCE", "brand-atlas/default"
            ),
        )


def load_settings(paths: AppPaths) -> RuntimeSettings:
    """Load persisted non-secret settings; runtime transport values come from env."""
    base = RuntimeSettings.from_environment()
    config_file = paths.config / "settings.json"
    if not config_file.exists():
        return base
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    allowed = {
        "llm_provider", "llm_base_url", "llm_model", "embedding_provider",
        "embedding_base_url", "embedding_model", "api_key_reference",
    }
    values = {key: payload[key] for key in allowed if key in payload}
    return RuntimeSettings(**{**base.__dict__, **values})


def persist_settings(paths: AppPaths, settings: RuntimeSettings) -> None:
    paths.config.mkdir(parents=True, exist_ok=True)
    payload = {
        "llm_provider": settings.llm_provider,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_base_url": settings.embedding_base_url,
        "embedding_model": settings.embedding_model,
        "api_key_reference": settings.api_key_reference,
    }
    (paths.config / "settings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
