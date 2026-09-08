"""External-only OpenAI-compatible LLM adapter.

There is no local model fallback here by design.  When no provider is
configured, the agent service answers from the local graph context instead.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def _api_key(reference: str, override: str | None = None) -> str | None:
    if override:
        return override
    try:
        import keyring

        value = keyring.get_password("BrandAtlas", reference)
        if value:
            return value
    except Exception:
        pass
    return os.getenv("BRAND_ATLAS_LLM_API_KEY")


def configured_api_key(reference: str) -> bool:
    """Return whether the runtime has a key without exposing its value."""
    return bool(_api_key(reference))


class OpenAICompatibleClient:
    def __init__(self, *, base_url: str, model: str, key_reference: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.key_reference = key_reference
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
        key = _api_key(self.key_reference, self.api_key)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def test_connection(self) -> None:
        """Make a minimal real request so the endpoint and selected model are verified."""
        if not self.base_url or not self.model:
            raise RuntimeError("请填写 LLM Base URL 和模型名称")
        if not _api_key(self.key_reference, self.api_key):
            raise RuntimeError("LLM API Key 未配置，请在设置中重新填写并保存")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "temperature": 0,
            "max_tokens": 1,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 LLM API：{exc.reason}") from exc
        if not payload.get("choices"):
            raise RuntimeError("LLM API 已响应，但没有返回 choices")

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.base_url or not self.model:
            raise RuntimeError("LLM base URL and model are not configured")
        if not _api_key(self.key_reference, self.api_key):
            raise RuntimeError("LLM API Key 未配置，请在设置中重新填写并保存")
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0.2},
                          ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"LLM API HTTP {exc.code}: {detail}") from exc
        choices = payload.get("choices") or []
        if not choices or not choices[0].get("message", {}).get("content"):
            raise RuntimeError("LLM API returned no message")
        return str(choices[0]["message"]["content"])
