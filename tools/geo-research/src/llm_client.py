"""Minimal OpenAI-compatible chat-completions client."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_API_KEY_ENV = "BRAND_ATLAS_LLM_API_KEY"
LEGACY_API_KEY_ENVS = ("GEO_LLM_API_KEY",)


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    endpoint: str | None = None
    api_key: str | None = None
    api_key_env: str = DEFAULT_API_KEY_ENV
    api_key_required: bool = True
    timeout_seconds: int = 120
    max_output_tokens: int = 6000
    temperature: float = 0.2

    @classmethod
    def from_file(cls, path: Path) -> "LLMConfig":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return cls(**payload)

    @property
    def chat_endpoint(self) -> str:
        if self.endpoint:
            return self.endpoint
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def api_key_env_candidates(self) -> tuple[str, ...]:
        names = [self.config.api_key_env]
        for name in (DEFAULT_API_KEY_ENV, *LEGACY_API_KEY_ENVS):
            if name not in names:
                names.append(name)
        return tuple(names)

    def available_api_key_env(self) -> str | None:
        return next((name for name in self.api_key_env_candidates() if os.getenv(name)), None)

    def api_key(self) -> str | None:
        if self.config.api_key:
            return self.config.api_key
        resolved_env = self.available_api_key_env()
        value = os.getenv(resolved_env) if resolved_env else None
        if self.config.api_key_required and not value:
            candidates = ", ".join(self.api_key_env_candidates())
            raise RuntimeError(f"Missing API key in config and environment; checked: {candidates}")
        return value

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int | None = None) -> str:
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": max_tokens or self.config.max_output_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json", "User-Agent": "BrandAtlasResearch/0.1"}
        if key := self.api_key():
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(
            self.config.chat_endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                choice = payload["choices"][0]
                content = choice.get("message", {}).get("content") or choice.get("text")
                if not content:
                    raise RuntimeError("LLM response did not contain choices[0].message.content")
                return content.strip()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:1000]
                last_error = RuntimeError(f"LLM HTTP {exc.code}: {detail}")
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM request failed: {last_error}")


def extract_json_object(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM output does not contain a JSON object")
        candidate = candidate[start : end + 1]
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload
