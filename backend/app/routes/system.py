from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request

from ..schemas import ProviderTestRequest, SettingsRequest, TestSettingsRequest
from ..services.embedding import ExternalEmbeddingClient
from ..services.llm import OpenAICompatibleClient, configured_api_key

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request):
    current = request.app.state.settings_store.snapshot()
    return {
        "status": "ok",
        "service": "brand-atlas-local",
        "database": str(request.app.state.paths.database),
        "llm_provider": current.llm_provider,
        "embedding_provider": current.embedding_provider,
    }


@router.get("/stats")
def stats(request: Request):
    return request.app.state.knowledge.stats()


@router.get("/settings")
def settings(request: Request):
    current = request.app.state.settings_store.snapshot()
    return {
        "llm_provider": current.llm_provider,
        "llm_base_url": current.llm_base_url,
        "llm_model": current.llm_model,
        "embedding_provider": current.embedding_provider,
        "embedding_base_url": current.embedding_base_url,
        "embedding_model": current.embedding_model,
        "llm_api_key_configured": configured_api_key(current.api_key_reference),
        "data_dir": str(request.app.state.paths.root),
    }


@router.put("/settings")
def update_settings(payload: SettingsRequest, request: Request):
    settings_store = request.app.state.settings_store
    current = settings_store.snapshot()
    updated = replace(
        current,
        llm_provider=payload.llm_provider,
        llm_base_url=payload.llm_base_url,
        llm_model=payload.llm_model,
        embedding_provider=payload.embedding_provider,
        embedding_base_url=payload.embedding_base_url,
        embedding_model=payload.embedding_model,
    )
    if payload.api_key:
        try:
            import keyring

            keyring.set_password("BrandAtlas", updated.api_key_reference, payload.api_key)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not save API key to system keyring: {exc}",
            ) from exc
    try:
        settings_store.replace(updated)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not save settings: {exc}",
        ) from exc
    return {"status": "ok", "settings": settings(request)}


@router.post("/settings/test")
def test_settings(payload: TestSettingsRequest, request: Request):
    """Test transient form values without persisting them."""
    current = request.app.state.settings_store.snapshot()
    key_reference = current.api_key_reference
    result: dict[str, dict[str, str]] = {}

    if payload.llm_provider == "none":
        result["llm"] = {"status": "skipped", "message": "LLM 未启用"}
    else:
        try:
            OpenAICompatibleClient(
                base_url=payload.llm_base_url,
                model=payload.llm_model,
                key_reference=key_reference,
                api_key=payload.api_key,
            ).test_connection()
            result["llm"] = {"status": "ok", "message": "LLM 连接成功，模型可用"}
        except Exception as exc:
            result["llm"] = {"status": "error", "message": str(exc)}

    if payload.embedding_provider == "none":
        result["embedding"] = {"status": "skipped", "message": "Embedding 未启用"}
    else:
        try:
            from dataclasses import replace

            embedding_settings = replace(
                current,
                embedding_base_url=payload.embedding_base_url,
                embedding_model=payload.embedding_model,
            )
            ExternalEmbeddingClient(embedding_settings, api_key=payload.api_key).test_connection()
            result["embedding"] = {"status": "ok", "message": "Embedding 连接成功，模型可用"}
        except Exception as exc:
            result["embedding"] = {"status": "error", "message": str(exc)}

    has_error = any(item["status"] == "error" for item in result.values())
    return {"status": "error" if has_error else "ok", **result}


@router.post("/settings/test/llm")
def test_llm_connection(payload: ProviderTestRequest, request: Request):
    """Test only the configured chat model; never persists form values."""
    if not payload.base_url and not payload.model:
        return {"status": "skipped", "message": "LLM 未配置"}
    try:
        OpenAICompatibleClient(
            base_url=payload.base_url,
            model=payload.model,
            key_reference=request.app.state.settings_store.snapshot().api_key_reference,
            api_key=payload.api_key,
        ).test_connection()
        return {"status": "ok", "message": "LLM 连接成功，模型可用"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@router.post("/settings/test/embedding")
def test_embedding_connection(payload: ProviderTestRequest, request: Request):
    """Test only the embedding model; failure does not affect chat mode."""
    if not payload.base_url and not payload.model:
        return {"status": "skipped", "message": "Embedding 未配置，可继续使用本地关键词检索"}
    try:
        embedding_settings = replace(
            request.app.state.settings_store.snapshot(),
            embedding_base_url=payload.base_url,
            embedding_model=payload.model,
        )
        ExternalEmbeddingClient(embedding_settings, api_key=payload.api_key).test_connection()
        return {"status": "ok", "message": "Embedding 连接成功，模型可用"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
