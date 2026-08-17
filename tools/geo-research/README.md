# Brand Atlas Industry Research Module

An open-source-friendly research collector for Generative Engine Optimization (GEO).
It collects public RSS feeds and explicitly configured public pages, stores normalized
records as JSONL, and produces a Markdown digest with source URLs.

## Quick start

```powershell
cd 'D:\Brand Atlas\geo-research'
python -m src.research collect
python -m src.research search  # optional, requires SEARXNG_URL
python -m src.research report
```

On Windows, `.\run.ps1` runs both steps. Schedule that script with Windows Task Scheduler
weekly or biweekly after reviewing the source list.

The first run uses only Python's standard library. Records are written to `data/items.jsonl`
and the report to `reports/latest.md`.

Project-local research skills live under `.agents/skills`. Agent-Reach commands use the
project environment at `.venv-agent-reach`; its `Scripts` directory is registered in the
user `PATH` so `agent-reach`, `bili`, and `twitter` resolve to this project installation.

## Configuration

Edit `sources.json` to add or disable sources. RSS sources are preferred. For pages that do
not provide RSS, add a public URL with `type: page`; the collector records the page itself
and does not attempt to bypass login, CAPTCHA, paywalls, robots rules, or rate limits.

Set `GEO_KEYWORDS` to override the default keyword list, for example:

```powershell
$env:GEO_KEYWORDS = 'GEO,AEO,AI search visibility,LLM SEO,answer engine'
python -m src.research collect
```

For a self-hosted SearXNG instance, set `SEARXNG_URL` and run `python -m src.research search`.
Each result is stored with its original result URL; the SearXNG query URL is also retained.
See [tool-evaluation.md](tool-evaluation.md) for the integration decision.
See [configuration.md](configuration.md) for the required and optional API/model configuration.
See [research-search-crawl-requirements.md](research-search-crawl-requirements.md) for the complete
Chinese search, crawling, community-sampling, evidence, citation, and report-acceptance standard.

Start the bundled local SearXNG service after Docker Desktop is running. The compose file uses
the GHCR mirror because Docker Hub may be unreachable on some networks:

```powershell
.\start-searxng.ps1
$env:SEARXNG_URL = 'http://127.0.0.1:8080'
python -m src.research search
```

The service binds only to localhost and enables both HTML and JSON result formats.
This installation uses Bing China and 360 Search. Baidu and Sogou were disabled after their
search endpoints presented CAPTCHAs; default overseas engines consistently time out here.
If JSON returns `unresponsive_engines`, configure Docker Desktop's HTTP/HTTPS proxy or disable
the unreachable engines in the SearXNG settings before relying on search results.

When a local proxy is available, set it before starting the container:

```powershell
$env:HTTP_PROXY = 'http://127.0.0.1:7890'
$env:HTTPS_PROXY = $env:HTTP_PROXY
.\start-searxng.ps1
```

## Initial open-source references

The source registry separates domestic and international research:

- Domestic industry: CNNIC, CAICT, iResearch, iiMedia, Head Research, 36Kr Research.
- Domestic academic: Baidu Scholar, CNKI, Wanfang, using `生成式引擎优化`, `大模型搜索`,
  `AI 搜索`, `答案引擎优化`, and `品牌可见性` as search terms.
- Domestic user/product discovery: Zhihu first, then official public pages for Baidu AI
  Search, Doubao, Kimi, Yuanbao, Tongyi, Zhipu and DeepSeek where product evidence exists.
- International comparison: Google Scholar, arXiv, G2, Product Hunt, Reddit and the
  open-source GEO tools listed below.

These projects were identified from GitHub's public repository search on 2026-08-06:

- https://github.com/Auriti-Labs/geo-optimizer-skill (MIT)
- https://github.com/onvoyage-ai/gtm-engineer-skills (MIT)
- https://github.com/yaojingang/GEORank (Apache-2.0)
- https://github.com/alexpospekhov/searchstack-aeo (MIT)
- https://github.com/cxcscmu/AutoGEO (research implementation; review license before reuse)
- https://github.com/amplifying-ai/awesome-generative-engine-optimization (curated list)

They are references for later integration, not copied code. Review licenses and activity before
embedding any dependency.

## LLM-assisted industry research report

The report pipeline accepts any OpenAI-compatible chat-completions service. Store only the
service URL and model name in the local config; the API key is prompted for at run time and is
removed from the process environment when the command finishes.

```powershell
# One-time configuration with a locally stored API key (hidden prompt)
.\configure-llm.ps1 -BaseUrl 'https://your-api.example/v1' -Model 'your-model' -StoreApiKey

# Optional: create the dedicated Edge login profile for the only two login sources
.\login-browser.ps1 -Platform zhihu
.\login-browser.ps1 -Platform xiaohongshu

# Public web research
.\run-research-report.ps1 -Request '请调研中国宠物食品市场、竞品和消费者痛点'

# Also allow results from the saved Zhihu/Xiaohongshu login profile
.\run-research-report.ps1 -Request '请调研国内 GEO 产品和品牌方需求' -IncludeLogin -ShowBrowser
```

With `-StoreApiKey`, the hidden-input key is stored in the git-ignored `llm-config.local.json` and
reused on later runs. Re-run the same command to replace it. Without `-StoreApiKey`, the script
preserves an existing stored key; when no key is stored, `run-research-report.ps1` prompts for a
temporary process key. The legacy `GEO_LLM_API_KEY` name remains readable for compatibility.

Query profiles:

- `-QueryProfile auto` (default): use the GEO source preset only when the request mentions GEO,
  AEO, generative engine optimization, or AI search; otherwise use the general industry preset.
- `-QueryProfile general`: force general market, competitor, user-voice, media, and academic sources.
- `-QueryProfile geo`: force the detailed GEO source and citation policy.

The general profile uses the same priority checklist for every industry and brand, replacing only
the subject terms: CAICT, iResearch, iResearch/ifenxi, LeadLeo, QuestMobile, Aurora, CBNData,
Tencent/Alibaba research and 199IT; CNR, 21财经, 经济日报, 中国青年报 and CCTV/3·15;
36Kr, Huxiu, Morketing, Meihua and BMR; Zhihu, Xiaohongshu, ZSXQ and Bilibili; competitor
primary sources and financing news; then CITIC, CICC, HTSC, SWS and Eastmoney report discovery.
Missing or inaccessible sources remain in the search coverage ledger and are never silently
treated as evidence.

The model first creates a search plan and appends the mandatory current-year source queries
from `queries.json`. Local SearXNG discovers candidate pages, and Playwright crawls permitted
pages. Search snippets are retained for discovery and coverage auditing but cannot enter the
report evidence set. The model writes a detailed Chinese Markdown report only from successfully
opened pages. Inline `[S#]` citations become clickable original URLs; a per-domain search
coverage ledger and the complete graded source list are appended to the report. The newest report is written to
`reports/latest-search-report.md`; plans, search results, and evidence remain under
`data/runs/<timestamp>/` for audit.

China-focused GEO research additionally follows
`.agents/skills/agent-reach/references/geo-research-policy.md`: authoritative market reports,
investigative and vertical media, public user communities, competitor primary sources, and
brokerage research are searched in layers. Current-year evidence is preferred, and every factual
claim must link to the exact original page used as evidence.

## Roadmap

1. Add official search/news APIs for stable discovery and pagination.
2. Expand the Playwright adapter with approved per-site selectors where generic extraction is insufficient.
3. Add adapters for G2, Product Hunt, Reddit, Zhihu, and Xiaohongshu only where access is
   permitted, with manual URL import as the fallback.
4. Add LLM-assisted tagging for competitor, pain point, evidence, and opportunity fields.

## Browser collection

Install the isolated browser environment once. The collector automatically uses installed Edge
when the separate Playwright Chromium download is unavailable:

```powershell
.\install-browser-collector.ps1
.\run.ps1 browser-diagnose
.\run.ps1 browser -Dataset market
```

Browser records are written to `data/<dataset>/browser-items.jsonl`; extracted page text is
stored in `data/<dataset>/pages/` with a SHA-256 hash in the record. Login sources are skipped
unless a dedicated profile and `--include-login` are supplied. See the Chinese
[访问要求清单](access-requirements.md) for current domestic sources, login steps, API options,
proxy requirements, and measured access failures.

## Scope and compliance

Only public, low-frequency collection is supported. Platform terms, robots.txt, copyright,
privacy, and applicable laws take precedence. Prefer official APIs or manually supplied URLs
for sources requiring authentication.
