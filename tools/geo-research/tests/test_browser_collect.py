from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.browser_collect import (
    DEFAULT_EXTRACT_TIMEOUT_MS,
    blocker_reason,
    content_quality_error,
    extract_page,
    failure_reason,
    make_record,
)
from src.storage import upsert_jsonl


class BrowserCollectorTests(unittest.TestCase):
    def test_extract_page_uses_bounded_text_timeout(self):
        class FakeLocator:
            def __init__(self):
                self.timeout = None

            def or_(self, other):
                return self

            @property
            def first(self):
                return self

            def inner_text(self, timeout):
                self.timeout = timeout
                return "正文 内容"

        class FakePage:
            url = "https://example.com/final"

            def __init__(self):
                self.locator_instance = FakeLocator()

            def evaluate(self, script, selector):
                return {"title": "Title", "canonical": "https://example.com/canonical", "published": ""}

            def locator(self, selector):
                return self.locator_instance

        page = FakePage()
        payload = extract_page(page, {})
        self.assertEqual(payload["text"], "正文 内容")
        self.assertEqual(page.locator_instance.timeout, DEFAULT_EXTRACT_TIMEOUT_MS)

    def test_detects_manual_blocker(self):
        self.assertEqual(blocker_reason("安全验证", "请完成验证"), "安全验证")

    def test_detects_soft_404(self):
        self.assertEqual(failure_reason("404 未找到页面", "页面已经搬家"), "404")

    def test_record_preserves_traceability_fields(self):
        source = {"name": "Example", "dataset": "market", "url": "https://example.com/source"}
        payload = {
            "title": "Report",
            "canonical": "https://example.com/report",
            "final_url": "https://example.com/report",
            "http_status": 200,
            "text": "evidence",
        }
        record = make_record(source, payload, "ok")
        self.assertEqual(record["requested_url"], source["url"])
        self.assertEqual(record["url"], payload["canonical"])
        self.assertEqual(record["http_status"], 200)
        self.assertTrue(record["content_sha256"])

    def test_empty_page_is_not_traceable_content(self):
        self.assertEqual(content_quality_error(""), "insufficient extracted text: 0 characters")
        self.assertIsNone(content_quality_error("x" * 80))

    def test_jsonl_upsert_replaces_same_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.jsonl"
            upsert_jsonl(path, [{"id": "1", "title": "old"}])
            total = upsert_jsonl(path, [{"id": "1", "title": "new"}])
            self.assertEqual(total, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["title"], "new")

    def test_load_sources_accepts_utf8_bom(self):
        from src.browser_collect import load_sources

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(
                json.dumps([{"name": "Example", "dataset": "market", "url": "https://example.com"}]),
                encoding="utf-8-sig",
            )
            self.assertEqual(load_sources(path, "market", None)[0]["name"], "Example")


if __name__ == "__main__":
    unittest.main()
