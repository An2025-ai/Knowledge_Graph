# L2 外部行业研究链路

> 目标：先输出候选信源清单，再生成可追溯 research package，最后生成行业报告并进入 L2 入库链路。

## 1. 新链路

```text
industry scope / industry name
-> source_discovery
-> source_candidates.json
-> geo_research_report_job
-> research_package/
-> report_ingestion
-> evidence_resolution
-> extraction
-> promotion
```

这次改造的重点是：不再只依赖外部 geo-research 生成的一份简化 Markdown，而是让 L2 接收一个完整研究包。

## 2. 第一步：输出候选信源清单

离线模式，不调用搜索服务，只生成 query plan 和 fallback 候选：

```powershell
python -m runtime.l2.executor --pipeline source_discovery `
  --industry "CRM软件" `
  --market CN `
  --dimensions "capabilities,market_participants,decision_factors" `
  --seed-sources "中国信通院,艾瑞咨询,IDC" `
  --offline `
  --source-list runtime/l2/output/crm_sources.json `
  --dry-run --no-db-check
```

如果本机部署了 SearXNG，设置：

```powershell
$env:SEARXNG_URL = "http://localhost:8080/search"
```

然后去掉 `--offline`，系统会优先用本地 SearXNG。连不上时会自动退回 fallback 候选，不阻塞 L2 流程。

输出文件形态：

```json
{
  "industry": "CRM软件",
  "market": "CN",
  "provider": {"provider": "searxng", "searxng_available": true},
  "query_plan": [],
  "sources": [],
  "stats": {"dimensions": 3, "queries": 9, "sources": 20}
}
```

新增来源默认是：

```text
approval_status = pending
l2_enabled = false
discovery_status = pending_review
```

这保证了“白名单找不到”时可以继续发现来源，但不会绕过后续 promotion 的来源治理。

## 3. 第二步：爬取并提取维度，生成 research package

从信源清单生成研究包：

```powershell
python -m runtime.l2.executor --pipeline geo_research_report_job `
  --source-list runtime/l2/output/crm_sources.json `
  --package-out runtime/l2/output/crm_research_package `
  --report-id grep_crm_cn_001 `
  --dry-run --no-db-check
```

如果要实际抓取 URL，去掉 `--dry-run`。如果只想先生成包结构，不抓网页：

```powershell
python -m runtime.l2.executor --pipeline geo_research_report_job `
  --source-list runtime/l2/output/crm_sources.json `
  --package-out runtime/l2/output/crm_research_package `
  --no-fetch `
  --report-id grep_crm_cn_001
```

研究包目录包含：

```text
research_package/
  manifest.json
  sources.json
  evidence_index.json
  coverage_ledger.json
  candidates.json
  report.md
  documents/
```

其中：

| 文件 | 用途 |
|---|---|
| `sources.json` | 候选信源清单和 query plan |
| `evidence_index.json` | `[S#]` 到 evidence/source/quote/url 的映射 |
| `coverage_ledger.json` | 每个 L2 维度覆盖了多少信源 |
| `candidates.json` | 初步维度候选陈述 |
| `report.md` | 给人阅读，也给现有 `report_ingestion` 使用 |

## 4. 第三步：报告进入现有 L2 链路

可以直接用 research package：

```powershell
python -m runtime.l2.executor --pipeline geo_research_report_job `
  --research-package runtime/l2/output/crm_research_package `
  --report-id grep_crm_cn_001

python -m runtime.l2.executor --pipeline report_ingestion `
  --research-package runtime/l2/output/crm_research_package `
  --report-id grep_crm_cn_001

python -m runtime.l2.executor --pipeline evidence_resolution `
  --evidence runtime/l2/output/crm_research_package/evidence_index.json `
  --report-id grep_crm_cn_001
```

也可以一条命令从行业名开始：

```powershell
python -m runtime.l2.executor --all `
  --industry "CRM软件" `
  --market CN `
  --seed-sources "中国信通院,艾瑞咨询,IDC" `
  --dimensions "capabilities,market_participants,decision_factors" `
  --offline
```

`--all` 会按顺序生成 scope、信源清单、research package、报告候选、证据解析，再进入抽取和晋升。

## 5. 全文信源名单找不到怎么办

不要让流程中断。采用三层来源策略：

| 来源层级 | 处理方式 |
|---|---|
| 核心白名单 | 直接作为优先候选 |
| 扩展候选 | 进入 source_candidates，等待审核 |
| 探索线索 | 只作为搜索线索，不直接晋升事实 |

当某个维度覆盖不足时，补跑单个维度即可：

```powershell
python -m runtime.l2.executor --pipeline source_discovery `
  --industry "CRM软件" `
  --market CN `
  --dimensions "regulation_and_risks" `
  --seed-sources "工信部,国家网信办,全国标准信息公共服务平台"
```

这样可以避免每次重新全量爬行业，也能逐步把新行业的信源生态养起来。
