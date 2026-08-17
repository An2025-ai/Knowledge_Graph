# Geo Research Module

`tools/geo-research` packages the upstream research workflow used before L2
knowledge-graph ingestion.

This module is not a plain crawler library. It includes:

- project-local research skills under `.agents/skills`;
- SearXNG configuration for local metasearch;
- Playwright-based public-page collection;
- LLM-assisted search planning and report generation;
- citation validation and source coverage ledgers;
- source-configuration support for Knowledge Graph L2 dimensions.

The intended flow is:

```text
tools/geo-research
-> reports/generated/search-report-*.md
-> data/runs/<run_id>/evidence.json and coverage artifacts
-> runtime.l2 report_ingestion
-> evidence_resolution
-> extraction
-> source_enrichment
-> promotion
-> active industry graph
```

Local secrets, browser profiles, virtual environments, crawled pages, run
artifacts, and generated reports are intentionally ignored by git. Use
`tools/geo-research/llm-config.example.json` to create a local
`llm-config.local.json`.

Typical local setup:

```powershell
cd tools\geo-research
.\install-browser-collector.ps1
.\configure-llm.ps1 -BaseUrl "https://your-api.example/v1" -Model "your-model"
.\start-searxng.ps1
.\run-research-report.ps1 -Request "research request" -QueryProfile general
```

The module keeps `geo-research`'s own operating rules separate from L2
promotion rules. The research module produces cited evidence packages; the
Knowledge Graph runtime decides which candidates become active graph knowledge.
