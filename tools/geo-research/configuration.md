# Integration configuration

## Required for the baseline

No LLM API key or paid search API is required for the baseline stack:

- SearXNG: local metasearch service; no Docker Hub login required.
- last30days: HN, Polymarket, public Reddit, YouTube, GitHub and grounding sources can run without a model API key.
- Agent-Reach: RSS, Jina Reader, YouTube and basic Bilibili access do not require an LLM key.
- Codex performs synthesis in the active conversation; Codex login is not exported as an `OPENAI_API_KEY` to local scripts.

## Recommended interactive configuration

- GitHub CLI: run `gh auth login` for higher GitHub rate limits and authenticated repository access.
- OpenCLI extension: install the matching Chrome extension and keep a dedicated browser profile for permitted logged-in sources.
- SearXNG: after WSL2 and Docker Desktop are running, execute `.\start-searxng.ps1`.

## Optional credentials

| Credential | Unlocks | Required? |
|---|---|---|
| `BRAND_ATLAS_LLM_API_KEY` | 通用行业研究报告的规划、证据归纳和引用报告生成 | Optional; `run-research-report.ps1` 会隐藏提示输入 |
| `SCRAPECREATORS_API_KEY` | last30days TikTok/Instagram and Reddit fallback | Optional |
| `OPENAI_API_KEY` | last30days legacy Reddit discovery/reasoning provider | Optional |
| `OPENROUTER_API_KEY` | last30days web/reasoning provider | Optional |
| `PERPLEXITY_API_KEY` | grounded search and deep research | Optional |
| `XAI_API_KEY` or X cookies | X/Twitter search | Optional |
| Groq API key | Agent-Reach Xiaoyuzhou transcription | Optional |
| Platform cookies/session | Xiaohongshu, Reddit, X, Facebook, Instagram, Xueqiu | Optional and user-authorized only |

Never commit keys or cookies to this repository. Use the tools' user-level configuration files.
For social platforms, use a dedicated account and respect terms, rate limits, copyright and privacy.

## Current machine status (2026-08-07)

- Python 3.12, Node.js 24, Git, GitHub CLI, mcporter and Docker Desktop installed.
- last30days installed as a project-local skill at `.agents\skills\last30days`.
- Agent-Reach installed in `.venv-agent-reach` and registered at `.agents\skills\agent-reach`.
- Agent-Reach working without login: YouTube, RSS, Jina Reader and Bilibili.
- SearXNG is running from `ghcr.io/searxng/searxng:latest` at `http://127.0.0.1:8080`.
- SearXNG uses Bing China and 360 Search successfully. Baidu and Sogou hit CAPTCHAs; overseas defaults remain disabled.
- Playwright 1.62.0 is installed in `.venv-browser` and uses the installed Microsoft Edge fallback.
- Exa MCP is configured; connectivity is intermittent on the current network.
