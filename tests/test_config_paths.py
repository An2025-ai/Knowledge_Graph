"""Embedding/NER config path guard (审查 Action Plan High #8, “新增内容”).

Code used to point at ``legacy/clients/config/`` while the real config directory
is ``legacy/config/`` (see legacy/config/model-config.example.json). These tests
pin DOWN the resolved path so a future regression moves it back.

Also checks that a config file placed at the CORRECT path parses into
EmbeddingConfig/NERConfig and honors ``api_key_env`` for the Authorization header
(Critical #3 is exercised here too — the header must be ``Bearer <key>``).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from legacy.clients.embeddings import (
    DEFAULT_MODEL_CONFIG as EMB_DEFAULT_CONFIG,
    EmbeddingClient,
    EmbeddingConfig,
)
from legacy.clients.ner_client import (
    DEFAULT_MODEL_CONFIG as NER_DEFAULT_CONFIG,
    NERConfig,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigPathTests(unittest.TestCase):
    def test_default_model_config_points_at_legacy_config(self):
        """High #8: both clients must resolve the config under ``legacy/config/``,
        NOT ``legacy/clients/config/`` (which does not exist)."""
        expected_dir = PROJECT_ROOT / "legacy" / "config"
        for name, path in (("embedding", EMB_DEFAULT_CONFIG), ("ner", NER_DEFAULT_CONFIG)):
            self.assertEqual(
                path.parent, expected_dir,
                f"{name} DEFAULT_MODEL_CONFIG must live in legacy/config/",
            )
        self.assertEqual(EMB_DEFAULT_CONFIG, NER_DEFAULT_CONFIG,
                         "both clients share the same model config file")

    def test_nonexistent_config_degrades_to_defaults(self):
        """With no model-config.local.json present, both configs fall back to sane
        defaults instead of raising."""
        emb = EmbeddingConfig.from_file()
        ner = NERConfig.from_file()
        self.assertEqual(emb.provider, "api")
        self.assertEqual(ner.provider, "local")

    def test_config_parses_from_legacy_config_location(self):
        """Drop a config at legacy/config/model-config.local.json (the location the
        fixed path resolves to) and confirm both clients read it."""
        payload = {
            "embedding": {"provider": "api", "model": "bge-m3", "dimension": 1024,
                          "base_url": "https://gw/v1", "api_key_env": "TEST_API_KEY"},
            "ner": {"enabled": True, "provider": "api", "model": "uie-x",
                    "schema": ["organization", "product"]},
        }
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "model-config.local.json"
            cfg_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            emb = EmbeddingConfig.from_file(cfg_path)
            self.assertEqual(emb.provider, "api")
            self.assertEqual(emb.base_url, "https://gw/v1")
            self.assertEqual(emb.api_key_env, "TEST_API_KEY")

            ner = NERConfig.from_file(cfg_path)
            self.assertEqual(ner.model, "uie-x")
            self.assertEqual(ner.schema, ["organization", "product"])

    def test_api_key_env_drives_auth_header(self):
        """Critical #3: Authorization header = \"Bearer <key>\", sourced from the
        configured env var, not a placeholder."""
        config = EmbeddingConfig(base_url="https://gw/v1",
                                 api_key_env="TEST_API_KEY")
        client = EmbeddingClient(config)
        with patch.dict(os.environ, {"TEST_API_KEY": "sk-secret", "HF_ENDPOINT": ""}):
            sent = {}

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"data": [{"index": 0, "embedding": [0.1, 0.2]}]}'

            actual_url = "https://gw/v1/embeddings"

            def fake_urlopen(req, timeout=None):
                sent["url"] = req.full_url
                sent["headers"] = req.headers
                sent["body"] = req.data
                return _Resp()

            with patch("legacy.clients.embeddings.urllib.request.urlopen", fake_urlopen):
                vec = client.embed(["x"])
            self.assertEqual(sent["url"], actual_url)
            self.assertEqual(sent["headers"].get("Authorization"), "Bearer sk-secret")
            self.assertNotIn("******", sent["headers"].get("Authorization", ""))
            self.assertEqual(vec, [[0.1, 0.2]])


if __name__ == "__main__":
    unittest.main()
