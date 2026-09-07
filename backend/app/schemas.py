"""HTTP request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ImportRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = None
    file_path: str | None = None
    source_type: str = "local_document"
    layer: Literal["l2_industry", "l3_brand"] = "l3_brand"
    brand_id: str | None = Field(default=None, max_length=120)
    tenant_id: str = "local"

    @model_validator(mode="after")
    def require_content_or_file(self):
        if not (self.content or self.file_path):
            raise ValueError("content or file_path is required")
        return self


class PipelineRequest(BaseModel):
    document_id: str
    stages: list[str] = Field(default_factory=lambda: ["extract", "promote"])


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=10)


class SettingsRequest(BaseModel):
    llm_provider: Literal["none", "openai-compatible"] = "none"
    llm_base_url: str = ""
    llm_model: str = ""
    embedding_provider: Literal["none", "openai-compatible"] = "none"
    embedding_base_url: str = ""
    embedding_model: str = ""
    api_key: str | None = Field(default=None, max_length=500)


class TestSettingsRequest(SettingsRequest):
    """Transient model configuration used by the connection test endpoint."""


class ProviderTestRequest(BaseModel):
    """Transient configuration for testing one provider independently."""

    base_url: str = ""
    model: str = ""
    api_key: str | None = Field(default=None, max_length=500)


class GraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    stats: dict[str, Any]
