"""Provider-neutral source discovery helpers.

The L2 runtime should depend on a stable source-candidate contract, not on a
specific crawler project. This module keeps the first pass intentionally small:
SearXNG is used when a local endpoint is reachable; otherwise we produce an
auditable fallback plan that can still seed manual review or geo-research.
"""
from __future__ import annotations

import json
import hashlib
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8080/search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""
    rank: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "engine": self.engine,
            "rank": self.rank,
        }


def provider_status(searxng_url: str | None = None, timeout: float = 2.0) -> dict[str, Any]:
    """Return the selected provider and whether local SearXNG is reachable."""
    url = searxng_url or DEFAULT_SEARXNG_URL
    probe = f"{url}?{urllib.parse.urlencode({'q': 'test', 'format': 'json'})}"
    try:
        req = urllib.request.Request(probe, headers={"User-Agent": "BrandAtlasKG/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - configured local search URL
            ok = 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001 - provider fallback is expected
        return {
            "provider": "fallback",
            "searxng_url": url,
            "searxng_available": False,
            "reason": str(exc)[:200],
        }
    return {
        "provider": "searxng" if ok else "fallback",
        "searxng_url": url,
        "searxng_available": ok,
    }


def search(query: str, max_results: int = 5, searxng_url: str | None = None,
           timeout: float = 8.0) -> list[SearchResult]:
    """Search with local SearXNG, returning normalized results.

    Raises on provider/network errors so callers can fallback per query.
    """
    url = searxng_url or DEFAULT_SEARXNG_URL
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"User-Agent": "BrandAtlasKG/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - configured provider URL
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    results = []
    for idx, item in enumerate(payload.get("results") or [], start=1):
        item_url = item.get("url")
        if not item_url:
            continue
        results.append(SearchResult(
            title=item.get("title") or item_url,
            url=item_url,
            snippet=item.get("content") or item.get("snippet") or "",
            engine=item.get("engine") or "searxng",
            rank=idx,
        ))
        if len(results) >= max_results:
            break
    return results


def fallback_search_result(query: str, rank: int = 1) -> SearchResult:
    """Return a traceable fallback search URL when no provider is available."""
    encoded = urllib.parse.quote_plus(query)
    return SearchResult(
        title=f"Search manually: {query}",
        url=f"https://www.google.com/search?q={encoded}",
        snippet="Fallback discovery candidate; provider did not return crawlable results.",
        engine="fallback",
        rank=rank,
    )


def source_id_from_url(url: str, prefix: str = "src") -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.replace("www.", "") or "manual"
    path = parsed.path.strip("/").replace("/", "_")[:32]
    query_hash = hashlib.sha1((parsed.query or url).encode("utf-8")).hexdigest()[:8]
    seed = f"{host}_{path or int(time.time())}_{query_hash}"
    safe = "".join(c.lower() if c.isalnum() else "_" for c in seed)
    safe = "_".join(part for part in safe.split("_") if part)
    return f"{prefix}_{safe[:70]}"
