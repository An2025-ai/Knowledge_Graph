from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.llm_client import LLMConfig, extract_json_object
from src.llm_report import (
    evidence_for_model,
    is_geo_request,
    is_public_url,
    link_citations,
    normalize_plan,
    query_domain,
    search_coverage_appendix,
    select_for_crawl,
    validate_citations,
)


class LLMClientTests(unittest.TestCase):
    def test_chat_endpoint_normalization(self):
        self.assertEqual(LLMConfig(base_url="https://api.example.com", model="m").chat_endpoint, "https://api.example.com/v1/chat/completions")
        self.assertEqual(LLMConfig(base_url="https://api.example.com/v1/", model="m").chat_endpoint, "https://api.example.com/v1/chat/completions")
        self.assertEqual(LLMConfig(base_url="https://api.example.com/v1/chat/completions", model="m").chat_endpoint, "https://api.example.com/v1/chat/completions")

    def test_config_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"base_url": "https://api.example.com", "model": "模型"}), encoding="utf-8-sig")
            self.assertEqual(LLMConfig.from_file(path).model, "模型")

    def test_config_can_store_api_key_without_exposing_it(self):
        config = LLMConfig(base_url="https://api.example.com", model="m", api_key="secret")
        self.assertEqual(config.api_key, "secret")

    def test_extract_json_object_from_fence_or_surrounding_text(self):
        self.assertEqual(extract_json_object('```json\n{"queries": []}\n```'), {"queries": []})
        self.assertEqual(extract_json_object('result: {"ok": true} done'), {"ok": True})


class ReportPipelineTests(unittest.TestCase):
    def test_normalize_plan_filters_invalid_datasets_and_falls_back(self):
        plan = normalize_plan({"queries": [{"query": "市场规模", "dataset": "market"}, {"query": "bad", "dataset": "other"}]}, "研究请求")
        self.assertEqual(
            plan["queries"][0],
            {"query": "市场规模", "dataset": "market", "dimension": None},
        )
        self.assertTrue(any("site:caict.ac.cn" in item["query"] for item in plan["queries"]))
        self.assertTrue(any("权威机构 官方统计" in item["query"] for item in plan["queries"]))
        self.assertTrue(any("authoritative institution government statistics" in item["query"] for item in plan["queries"]))
        fallback = normalize_plan({}, "研究请求")
        self.assertEqual({item["dataset"] for item in fallback["queries"]}, {"market", "products", "academic", "user-voice"})
        self.assertTrue(all("{year}" not in item["query"] for item in fallback["queries"]))

    def test_query_profiles_do_not_force_geo_into_other_industries(self):
        general = normalize_plan({}, "调研中国宠物食品市场与消费者痛点")
        self.assertEqual(general["query_profile"], "general")
        self.assertFalse(any("生成式引擎优化" in item["query"] for item in general["queries"]))
        general_queries = "\n".join(item["query"] for item in general["queries"])
        for domain in (
            "caict.ac.cn",
            "iresearch.com.cn",
            "leadleo.com",
            "21jingji.com",
            "chinanews.com",
            "zhihu.com",
            "research.cicc.com",
        ):
            self.assertIn(domain, general_queries)
        geo = normalize_plan({}, "调研国内 GEO 产品与 AI 搜索需求")
        self.assertEqual(geo["query_profile"], "geo")
        self.assertTrue(any("GEO" in item["query"] for item in geo["queries"]))
        self.assertTrue(any("权威机构 官方统计" in item["query"] for item in geo["queries"]))
        self.assertTrue(any("official dataset regulator standard methodology" in item["query"] for item in geo["queries"]))
        self.assertTrue(is_geo_request("AEO 服务市场"))

    @patch("src.llm_report.socket.getaddrinfo")
    def test_rejects_private_and_accepts_public_urls(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        allowed, reason = is_public_url("https://example.com/page")
        self.assertFalse(allowed)
        self.assertIn("non-public", reason)
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        self.assertEqual(is_public_url("https://example.com/page"), (True, None))

    def test_citations_are_validated_and_linked(self):
        report = "结论一 [S1]，结论二 [S2]。"
        self.assertEqual(validate_citations(report, 2), (True, "ok"))
        linked = link_citations(report, [{"url": "https://a.example"}, {"url": "https://b.example"}])
        self.assertIn("[S1](https://a.example)", linked)
        self.assertFalse(validate_citations("错误 [S3]", 2)[0])
        self.assertFalse(validate_citations("这是一条足够长但没有提供任何来源链接的事实性结论。", 2)[0])

    def test_only_crawled_pages_become_model_evidence(self):
        records = [
            {"dataset": "market", "title": "verified", "url": "https://example.com/a", "published_at": "2026-01-01", "access_status": "crawled", "query": "q", "text": "full page"},
            {"dataset": "market", "title": "snippet", "url": "https://example.com/b", "published_at": None, "access_status": "search-snippet", "query": "q", "snippet": "search only"},
        ]
        evidence, _coverage = evidence_for_model(records, 10, 10000)
        self.assertEqual([item["title"] for item in evidence], ["verified"])

    def test_search_coverage_discloses_domains_and_usage(self):
        coverage = [{"query": "site:caict.ac.cn GEO 2026", "dataset": "market", "target_domain": "caict.ac.cn", "result_count": 1, "search_error": None}]
        records = [{"query": coverage[0]["query"], "access_status": "crawled"}]
        sources = [{"query": coverage[0]["query"]}]
        appendix = search_coverage_appendix(coverage, records, sources)
        self.assertIn("caict.ac.cn", appendix)
        self.assertIn("已搜索并采用", appendix)
        self.assertEqual(query_domain("site:iresearch.cn GEO"), "iresearch.cn")

    def test_crawl_selection_covers_each_query_first(self):
        records = [
            {"id": "a1", "query": "q1", "dataset": "market", "rank": 1},
            {"id": "a2", "query": "q1", "dataset": "market", "rank": 2},
            {"id": "b1", "query": "q2", "dataset": "products", "rank": 1},
        ]
        selected = select_for_crawl(records, 2)
        self.assertEqual({item["query"] for item in selected}, {"q1", "q2"})


if __name__ == "__main__":
    unittest.main()
