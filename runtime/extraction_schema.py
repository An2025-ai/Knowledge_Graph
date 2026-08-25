"""Pydantic v2 models for strict LLM extraction validation.

Validates the shape of LLM extraction output before it reaches PostgreSQL.
Mirrors OPTIMIZATION_TECH_PLAN.md §4.3 "LLM Structured Extraction Layer".
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

STATEMENT_CLASSES = {"fact", "claim", "observation", "inference"}


class EntityInput(BaseModel):
    id: str = Field(pattern=r"^ent_[a-z]+_[a-z0-9_]+$")
    type: str
    canonical_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _type_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("entity type must not be empty")
        return v.strip()


class RelationInput(BaseModel):
    subject: str
    relation: str
    object: str
    level: str | None = None
    entity_type_subject: str | None = None
    entity_type_object: str | None = None
    metric_name: str | None = None
    metric_value: str | float | int | None = None
    scope: str | dict[str, Any] | None = None
    evidence_text: str | None = None
    source_doc: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class StatementInput(BaseModel):
    text: str = Field(min_length=1)
    statement_class: str = Field(default="claim")
    level: str | None = None
    metric_name: str | None = None
    metric_value: str | float | int | None = None
    scope: str | dict[str, Any] | None = None
    evidence_text: str | None = None
    source_doc: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("statement_class")
    @classmethod
    def _stmt_class_valid(cls, v: str) -> str:
        if v not in STATEMENT_CLASSES:
            raise ValueError(f"statement_class must be one of {sorted(STATEMENT_CLASSES)}")
        return v


class ExtractionResult(BaseModel):
    entities: list[EntityInput] = Field(default_factory=list)
    relations: list[RelationInput] = Field(default_factory=list)
    statements: list[StatementInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _relation_refs_exist(self) -> "ExtractionResult":
        entity_ids = {e.id for e in self.entities}
        dangling = [
            r for r in self.relations
            if r.subject not in entity_ids or r.object not in entity_ids
        ]
        if dangling:
            raise ValueError(
                "relations reference entities not present in this extraction result: "
                + ", ".join(f"{r.subject}-{r.relation}->{r.object}" for r in dangling[:5])
            )
        return self


def validate_extraction(payload: dict[str, Any]) -> ExtractionResult:
    """Coerce a raw LLM dict into an ExtractionResult, raising on invalid shape."""
    return ExtractionResult.model_validate(payload)


def to_dicts(result: ExtractionResult) -> dict[str, Any]:
    return result.model_dump(exclude_none=True)
