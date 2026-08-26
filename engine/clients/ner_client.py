"""PaddleNLP NER client with provider abstraction (OPTIMIZATION_TECH_PLAN.md §4.2/§10.3).

Inserts a small-model NER layer between the rule/dictionary candidate extractors
and the LLM candidate_extraction step, so deterministic (regex/dictionary) facts
are cost-free and the NER model catches organization/product/capability/
certification mentions the fixed suffix/term lists miss.

The PaddleNLP dependency is heavy and may be incompatible with some
PaddlePaddle/Python/Windows combinations, so it is an OPTIONAL dependency:
  - imports are deferred until first use,
  - if ``import paddlenlp`` fails (NOT installed) or model initialization fails,
    the client degrades to returning an empty list instead of raising into the
    caller, so the L3 pipeline always skips the NER layer gracefully.

This module mirrors the provider-abstraction pattern of ``engine/embeddings.py``
(EmbeddingConfig / EmbeddingClient): a dataclass config read from a per-provider
JSON section, a lazy model load, and a module-level model cache so the heavy
model is loaded once per process.

Config section (engine/config/model-config.local.json):

    "ner": {
      "enabled": true,
      "provider": "local",
      "model": "uie-base",
      "schema": ["organization", "product", "capability", "certification"]
    }
"""
from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default HuggingFace mirror for Chinese networks (mirrors embeddings.py).
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# Module-level cache so the (heavy) Paddle model is loaded once per process,
# not once per NERClient / pipeline step.
_LOCAL_MODEL_CACHE: dict[str, Any] = {}

DEFAULT_MODEL_CONFIG = Path(__file__).resolve().parent / "config" / "model-config.local.json"

# Default schema the NER model is asked to extract. Keys on the right are the
# candidate_type values in ``knowledge_candidates``; see _TYPE_ALIASES below.
DEFAULT_SCHEMA = ["organization", "product", "capability", "certification"]

# ---------------------------------------------------------------------------
# Label mapping.
#
# UIE (the Chinese ERNIE-based information-extraction model paddlenlp 2.6 uses)
# MUST be given **Chinese** schema labels ("公司" / "产品" / "能力" / "认证"): with
# English labels it returns empty spans for Chinese text. So the config keeps
# English candidate_type semantics and we translate to/from Chinese around the
# UIE call. _SCHEMA_ZH maps an English candidate_type -> Chinese UIE label that
# the model is asked to extract.
# ---------------------------------------------------------------------------
_SCHEMA_ZH = {
    "organization": "公司",
    "product": "产品",
    "capability": "能力",
    "certification": "认证",
}

# UIE Chinese output label -> English candidate_type. Any label UIE returns that
# is not here is dropped (not projected as a candidate).
_TYPE_ALIASES = {
    "公司": "organization",
    "产品": "product",
    "能力": "capability",
    "认证": "certification",
    "organization": "organization",
    "org": "organization",
    "company": "organization",
    "product": "product",
    "product_name": "product",
    "capability": "capability",
    "function": "capability",
    "feature": "capability",
    "certification": "certification",
    "cert": "certification",
}


@dataclass
class NERConfig:
    enabled: bool = True
    provider: str = "local"
    model: str = "uie-base"
    schema: list[str] = field(default_factory=lambda: list(DEFAULT_SCHEMA))
    base_url: str = ""  # reserved for a future "api" provider
    api_key_env: str = "BRAND_ATLAS_LLM_API_KEY"

    @classmethod
    def from_file(cls, path: Path = DEFAULT_MODEL_CONFIG) -> "NERConfig":
        """Read the ``ner`` section of the model config file, else defaults."""
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        ner = payload.get("ner", {})
        kwargs = {k: v for k, v in ner.items() if k in cls.__dataclass_fields__}
        if "schema" in ner and not isinstance(ner["schema"], (list, tuple)):
            kwargs.pop("schema", None)  # ignore malformed schema (not a list)
        return cls(**kwargs)


class NERClient:
    def __init__(self, config: NERConfig | None = None):
        self.config = config or NERConfig.from_file()
        self._model = None  # lazy-loaded cached model

    def named_entities(self, text: str) -> list[dict]:
        """Return ``[{"type": <candidate_type>, "text": <span>, "score": float}]``.

        On any provider/model failure this degrades to ``[]`` (graceful) rather
        than raising, so the NER layer is strictly optional.
        """
        if not self.config.enabled:
            return []
        try:
            if self.config.provider == "local":
                return self._named_entities_local(text)
            raise ValueError(f"unknown NER provider '{self.config.provider}'")
        except Exception as exc:  # noqa: BLE001 - optional layer, never break caller
            warnings.warn(f"[ner] NER unavailable, degrading to empty: {exc}")
            self.config.enabled = False  # don't retry a known-bad model this run
            return []

    def _named_entities_local(self, text: str) -> list[dict]:
        """PaddleNLP UIE NER over the configured schema (local model)."""
        try:
            from paddlenlp import Taskflow
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "NER provider 'local' requires paddlenlp + paddlepaddle. "
                "Run: pip install -r requirements.txt (local-models group)"
            ) from exc

        model_name = self.config.model or "uie-base"
        # UIE needs Chinese schema labels for Chinese text (English labels return
        # empty). Translate the English candidate_type schema -> Chinese before
        # calling the model; _map_ner_type translates UIE labels back.
        schema_zh = [_SCHEMA_ZH.get(s, s) for s in self.config.schema]
        if self._model is None:
            if _LOCAL_MODEL_CACHE.get(model_name) is not None:
                self._model = _LOCAL_MODEL_CACHE[model_name]
            else:
                # UIE information-extraction Taskflow returns a dict keyed by
                # (Chinese) schema label -> list of {text, start, end, probability}.
                self._model = Taskflow(
                    "information_extraction", schema=schema_zh, model=model_name
                )
                _LOCAL_MODEL_CACHE[model_name] = self._model

        try:
            out = self._model(text)
        except TypeError:
            out = self._model([text])
        results: list[dict] = []
        # _model(text) with one string returns a list; with a list returns list-of-lists.
        batch = out if isinstance(out, (list, tuple)) else [out]
        for doc in batch:
            if not isinstance(doc, dict):
                continue
            for label, spans in doc.items():
                ctype = _map_ner_type(label)
                if not ctype:
                    continue
                for span in spans or []:
                    text = _clean_span(span.get("text", ""))
                    if not text:
                        continue
                    results.append({
                        "type": ctype,
                        "text": text,
                        "score": float(span.get("probability", span.get("score", 0.7))),
                    })
        return results


def _map_ner_type(label: str) -> str | None:
    """Map a model label/alias to an L3 candidate_type, or None to drop it."""
    return _TYPE_ALIASES.get((label or "").lower(), _TYPE_ALIASES.get(label))


_OPENING_BRACKETS = "([{（【「『"
_CLOSING_BRACKETS = ")]}）】」』"


def _is_balanced_brackets(text: str) -> bool:
    """True if every opened bracket has a matching closer (balanced/parenthesized).
    Used to avoid mangling well-formed spans while trimming stray brackets."""
    for _open, _close in zip("([{（【「『", ")]}）】」』"):
        if text.count(_open) != text.count(_close):
            return False
    return True


def _clean_span(text: str) -> str:
    """Trim a dangling/unbalanced bracket that UIE sometimes leaves at a span
    boundary (e.g. '...公司' without its closing '）'), while leaving balanced
    parenthesized spans untouched. Also strips leading/trailing whitespace."""
    text = (text or "").strip()
    if not text:
        return ""
    # Only trim when the bracket is unbalanced (no matching closer present).
    while text and text[0] in _OPENING_BRACKETS and not _is_balanced_brackets(text):
        text = text[1:].strip()
    while text and text[-1] in _OPENING_BRACKETS and not _is_balanced_brackets(text):
        text = text[:-1].strip()
    return text


def get_ner_client() -> NERClient:
    return NERClient()


if __name__ == "__main__":
    c = get_ner_client()
    print("NER enabled:", c.config.enabled, "provider:", c.config.provider,
          "model:", c.config.model, "schema:", c.config.schema)
    sample = "DeepCleer 深澈智算（上海智云图科技有限公司）提供 AI 业财财报平台，支持自动对账、多法人合并核算，获得 ISO 27001 认证。"
    print(json.dumps(c.named_entities(sample), ensure_ascii=False, indent=1))
