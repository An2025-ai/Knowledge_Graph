# Tool evaluation

| Project | Fit | Recommendation | Reason |
|---|---|---|---|
| [last30days-skill](https://github.com/mvanhorn/last30days-skill) | High | Use as discovery layer | Strong for recent Reddit, HN, X, YouTube, GitHub and arXiv signals; MIT; returns recent, people-driven evidence. Keep original URLs and treat its synthesis as a lead, not the source. |
| [SearXNG](https://github.com/searxng/searxng) | High | Use as search layer | Self-hosted metasearch with JSON output and no profiling; AGPL-3.0 means keep it as a separate service and review obligations before redistribution. |
| [browser-use](https://github.com/browser-use/browser-use) | Medium | Optional fallback | Useful for JS-rendered public pages and explicit, human-like browser workflows; requires Python 3.11+, an LLM key and browser runtime. It is slower and less deterministic than APIs/RSS. |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | Medium | Optional domestic adapter | Covers GitHub, Bilibili, Xiaohongshu, Reddit and YouTube; MIT. Some sources need user-controlled cookies or local services, so use only with permitted access and retain the canonical URL. |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | Low for MVP | Do not install yet | Powerful adaptive crawler (BSD-3-Clause), but its anti-bot/stealth features increase compliance and maintenance risk. Add only for an approved, stable public source. |
| [web-access](https://github.com/eze-is/web-access) | Medium | Optional agent skill | Useful routing between search, fetch, curl and CDP, with Windows browser support. The repository has no SPDX license in its GitHub metadata; review before commercial distribution. |

## Proposed stack

1. SearXNG or official APIs for discovery.
2. Existing collector for normalized records and URL preservation.
3. last30days for recent community/user signals.
4. browser-use or Agent-Reach only for pages that are public but JavaScript-rendered.
5. LLM synthesis only after raw records are saved.

The project must report the original URL, publisher, publication time, collection time, and
whether a conclusion is directly evidenced or inferred.
