"""Collect public GEO research sources and write a Markdown digest."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .storage import DATASETS, upsert_jsonl

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources.json"
DATA = ROOT / "data" / "items.jsonl"
REPORT = ROOT / "reports" / "latest.md"
QUERIES = ROOT / "queries.json"
DEFAULT_KEYWORDS = ["GEO", "AEO", "generative engine optimization", "AI search", "LLM SEO", "answer engine"]


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        value = re.sub(r"\s+", " ", data).strip()
        if value: self.parts.append(value)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "GEO-Research/0.1 (public research)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")


def keywords():
    raw = os.getenv("GEO_KEYWORDS")
    return [x.strip().lower() for x in raw.split(",") if x.strip()] if raw else [x.lower() for x in DEFAULT_KEYWORDS]


def parse_rss(body: str, source: dict):
    root = ET.fromstring(body)
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        summary = (node.findtext("description") or "").strip()
        yield make_item(source, title, link, summary)


def make_item(source, title, url, summary):
    clean = re.sub(r"<[^>]+>", " ", html.unescape(summary))
    category = source.get("category", "uncategorized")
    dataset = source.get("dataset") or dataset_for_category(category)
    return {"id": hashlib.sha256((url or title).encode()).hexdigest()[:16], "source": source["name"],
            "dataset": dataset,
            "category": category,
            "title": title or source["name"], "url": url or source["url"],
            "summary": re.sub(r"\s+", " ", clean).strip()[:1000],
            "collected_at": datetime.now(timezone.utc).isoformat()}


def dataset_for_category(category: str) -> str:
    if "industry" in category:
        return "market"
    if "academic" in category:
        return "academic"
    if "product" in category:
        return "products"
    if "user" in category:
        return "user-voice"
    return "market"


def save_by_dataset(records: list[dict], filename: str) -> None:
    for dataset in DATASETS:
        selected = [record for record in records if record.get("dataset") == dataset]
        if selected:
            total = upsert_jsonl(ROOT / "data" / dataset / filename, selected)
            print(f"Saved {len(selected)} {dataset} records; {total} total in {filename}.")


def collect():
    configured = json.loads(SOURCES.read_text(encoding="utf-8"))
    wanted = keywords(); found = []
    for source in configured:
        if not source.get("enabled", True): continue
        try:
            body = fetch(source["url"])
            if source.get("type") == "rss":
                found.extend(parse_rss(body, source))
            else:
                parser = TextParser(); parser.feed(body)
                text = " ".join(parser.parts)
                if any(k in text.lower() for k in wanted):
                    found.append(make_item(source, source["name"], source["url"], text))
            time.sleep(1)
        except Exception as exc:
            found.append({"id": hashlib.sha256(source["url"].encode()).hexdigest()[:16], "source": source["name"],
                          "title": "Collection error", "url": source["url"], "summary": str(exc),
                          "collected_at": datetime.now(timezone.utc).isoformat(), "error": True})
    existing = {}
    if DATA.exists():
        for line in DATA.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line); existing[item["id"]] = item
    existing.update({item["id"]: item for item in found})
    DATA.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing.values()), encoding="utf-8")
    save_by_dataset(found, "source-items.jsonl")
    print(f"Collected {len(found)} records; {len(existing)} total records.")


def search_searxng():
    base = os.getenv("SEARXNG_URL")
    if not base:
        raise SystemExit("Set SEARXNG_URL to a SearXNG instance, for example http://localhost:8080")
    records = []
    for configured_query in json.loads(QUERIES.read_text(encoding="utf-8")):
        query = configured_query["query"] if isinstance(configured_query, dict) else configured_query
        query = query.replace("{year}", str(datetime.now().year))
        dataset = configured_query.get("dataset", "market") if isinstance(configured_query, dict) else "market"
        url = base.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json", "language": "auto"})
        payload = json.loads(fetch(url))
        source = {"name": "SearXNG", "dataset": dataset, "category": "search_result", "url": url}
        for result in payload.get("results", []):
            records.append(make_item(source, result.get("title", query), result.get("url", ""), result.get("content", "")))
    save_by_dataset(records, "search-items.jsonl")
    print(f"SearXNG added {len(records)} classified results.")


def report():
    indexed = {}
    for path in (ROOT / "data").rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                indexed[(item["id"], item.get("dataset"))] = item
    items = list(indexed.values())
    items.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
    lines = ["# GEO Research Digest", "", f"Generated: {datetime.now().isoformat(timespec='seconds')}", "", f"Records: {len(items)}", ""]
    for item in items[:100]:
        lines += [f"## {item['title']}", f"- Dataset: {item.get('dataset', 'legacy')}",
                  f"- Source: {item['source']}", f"- Status: {item.get('status', 'ok')}",
                  f"- URL: {item['url']}", f"- Collected: {item['collected_at']}",
                  f"- Summary: {item.get('summary', '')}", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["collect", "search", "report"]); args = parser.parse_args()
    collect() if args.command == "collect" else search_searxng() if args.command == "search" else report()
