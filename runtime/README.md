# Brand Atlas Knowledge Graph — 运行时执行引擎

> **版本**: 1.0.0  
> **日期**: 2026-08-11  
> **说明**: 这是 L2/L3 知识层的**可执行代码**，把数据契约（YAML/Schema）变成真正能跑起来的"知识库形成"流程。

## 1. 前置条件

```bash
# 1) 启动 PostgreSQL 和 Neo4j（用 Docker，本机已装 Docker）
cd runtime
docker compose up -d

# 2) 安装 Python 依赖
pip install -r requirements.txt        # 项目根已有
pip install -r runtime/requirements.txt # neo4j driver 等

# 3) 配置 LLM 模型（重要）
#    编辑 runtime/config/llm-config.local.json，填上：
#      - base_url: 你的 LLM 网关地址（如 https://tokenhub.mandao.com/v1）
#      - model: 模型名（如 Qwen/Qwen3.8-Max）
#    把 API key 设到环境变量：
#      Windows: $env:BRAND_ATLAS_LLM_API_KEY = "你的key"
#      Linux:   export BRAND_ATLAS_LLM_API_KEY="你的key"

# 4) （优化）本地 embedding 模型 bge-m3（自动经 hf-mirror 下载）
#    pip install -r runtime/requirements-local-models.txt
#    配置 runtime/config/model-config.local.json（provider=local, BAAI/bge-m3）
#    embeddings.py 已默认 HF_ENDPOINT=https://hf-mirror.com（huggingface.co 不可达时）
```

## 2. 初始化数据库

```bash
export KG_DB_HOST=localhost KG_DB_PORT=5432 KG_DB_NAME=brand_atlas_kg KG_DB_USER=kg_admin KG_DB_PASSWORD=kg_admin_password

# 一键依次跑 L1 → L2 → L3 → vector(pgvector) 迁移
python -m runtime.migrations migrate

# 发布 L1 类型/关系/策略注册数据（migration 只建表，不填数据）
python database/publish.py --validate
python database/publish.py

# 或单独跑某层
python -m runtime.migrations migrate --only l2

# 验证连接
python -m runtime.db --check
```

> 顺序依赖：L3 迁移引用 L2 的 entity/evidence/document 表，必须先跑 L1、L2。
> `docker compose` 里 PostgreSQL 的账号是 `kg_admin / kg_admin_password`（可在 compose 文件改）。

## 3. 配置 LLM

配置文件：`runtime/config/llm-config.local.json`（已被 .gitignore 忽略，不会提交）。

```json
{
  "base_url": "https://你的网关/v1",
  "model": "你的模型名",
  "api_key": "",
  "api_key_env": "BRAND_ATLAS_LLM_API_KEY",
  "timeout_seconds": 120,
  "max_output_tokens": 6000,
  "temperature": 0.2
}
```

- `api_key` 留空则从环境变量 `BRAND_ATLAS_LLM_API_KEY` 读取。
- 模型名/url/apikey 后期补上即可，无需改代码。

## 4. L2 行业知识层执行器

```bash
# 需求编译：行业范围 → 需求契约
python -m runtime.industry.executor --pipeline requirement_compilation --scope <scope.yaml>

# 报告摄入：把 geo-research 生成的 Markdown 报告解析成候选
python -m runtime.industry.executor --pipeline report_ingestion --report <report.md> --report-id <report_id>

# 引用证据解析：引用标签 → source/evidence
python -m runtime.industry.executor --pipeline evidence_resolution --evidence <evidence.json> --report-id <report_id>

# 【爬取】直接调用 geo-research 爬虫生成行业报告（SearXNG 搜索 + Playwright 抓取 + LLM 生成）
python -m runtime.industry.executor --pipeline geo_research_report_job --crawl --request "研究中国CRM行业"
#   可配置（环境变量）：
#   GEO_RESEARCH_ROOT      = geo-research 根目录（默认 d:/Brand Atlas/geo-research）
#   GEO_RESEARCH_PYTHON    = 其 python（默认 .venv-browser/Scripts/python.exe）
#   GEO_RESEARCH_LLM_CONFIG= 其 llm-config.local.json
#   GEO_RESEARCH_TIMEOUT   = 爬取超时秒数（默认 900）

# 知识抽取：LLM 从报告候选抽出 实体/关系/事实（--dry-run 先试跑不写库）
python -m runtime.industry.executor --pipeline extraction --report <report.md> --dry-run

# 晋升：10 道门禁，通过即稳定
python -m runtime.industry.executor --pipeline promotion

# 一键全流程（--report 用已有报告，或 --crawl 自动爬取）
python -m runtime.industry.executor --all --scope <scope.yaml> --report <report.md> --evidence <evidence.json>
python -m runtime.industry.executor --all --scope <scope.yaml> --crawl --request "研究需求" --evidence <evidence.json>

# 【推荐】从"大致信息"一键到"按需求爬取报告"：
#   你只需给目标行业 + 市场区域，系统自动：
#   ① scope_builder 生成完整 14 维度 scope
#   ② requirement_compilation 编译成 requirement（含各维度研究问题）
#   ③ 用完整需求触发 geo-research 爬取 + 生成行业报告
#   ④ report_ingestion → extraction → promotion 入库
python -m runtime.industry.executor --all --industry "CRM软件" --market CN --crawl \
    --evidence <evidence.json> \
    [--audience "中小企业销售负责人"] [--competitors "销售易,纷享销客,用友"] \
    [--priority-dim "audience_and_decision_chain,problems_and_jobs"] \
    [--seed-sources "中国信通院,艾瑞咨询"]

# 也可单独生成 scope / request（不爬取）
python -m runtime.industry.scope_builder --industry "CRM软件" --market CN [--out scopes/crm.yaml]
python -m runtime.industry.requirement_to_request --requirement-id <ikr_xxx> [--out request.txt]
```

> **爬取说明**：`--crawl` 会真正调用 geo-research 爬网并生成报告，耗时较长（搜索+抓取+LLM 写报告，可能几分钟）。geo-research 的报告生成模型用它所处目录的 `llm-config.local.json`（已同步为 DeepSeek）。若抓取某站点卡住，可调大 `GEO_RESEARCH_TIMEOUT` 或先排查该站点网络。

> **来源审批与失败恢复**：新 evidence index 导入的来源默认为 `pending/disabled`。核验后需在 `source_instance` 设置 `approval_status='approved', l2_enabled=true`，否则 promotion 会在来源门禁拒绝。每个非 dry-run Pipeline 以单独事务执行，失败会回滚本步骤；重复运行通过唯一键复用已有 section/candidate/citation/statement/relation。
> 事务与统一退出码由 L2/L3 executor 提供；生产运行不要直接调用 `runtime.*.pipelines.*` 子模块。

## 5. L3 品牌知识层执行器（优化流水线）

**优化后的流水线顺序**（OPTIMIZATION_TECH_PLAN.md §5.2）：
```
source_registration
→ original_file_gate
→ layout_aware_parsing
→ semantic_chunking
→ candidate_pre_extraction      ← 规则/词典候选（新增）
→ candidate_extraction          ← LLM + Pydantic + 本体校验
→ entity_resolution             ← blocking + embedding 语义消歧（升级）
→ assertion_classification
→ evidence_verification         ← 语义证据核验（升级）
→ review_promotion
```

```bash
# 完整跑一条品牌文档
python -m runtime.brand.executor --all --file <brand_doc.md> --brand <brand_id>

# 单步
python -m runtime.brand.executor --pipeline candidate_pre_extraction --file <doc.md> --brand <brand_id>
python -m runtime.brand.executor --pipeline candidate_extraction --file <doc.md> --brand <brand_id>
```

> `--all --dry-run` 不会落库，因此从空库运行时后续步骤无法读取前序 document/chunk；完整预演请使用隔离测试库。

## 5.5 优化能力（OPTIMIZATION_TECH_PLAN.md）

| 能力 | 模块 | 说明 |
|------|------|------|
| 严格抽取校验 | `runtime/extraction_schema.py` (Pydantic) + `ontology_validator.py` | LLM 输出先 shape→本体校验，非法自动重试修复 |
| 候选预抽取 | `runtime/brand/pipelines/candidate_pre_extraction.py` + `brand_knowledge/rules+dictionaries` | 正则+词典抽 URL/版本/认证/组织/能力/产品候选，LLM 只处理难例 |
| NER 小模型 | `runtime/ner_client.py`（PaddleNLP）+ `candidate_pre_extraction._ner_entities` | 可选第三层：UIE/ERNIE 通用 NER 抽组织/产品/能力/认证，`generator="paddlenlp:ner:<type>"`；未装 paddlenlp 时降级为空，不影响主链路（配置 `"ner"` 段，`--skip-ner` 可关）。模型 `uie-base`，需 **paddlepaddle 2.6.x**（3.x 下静态导出失败），schema 需中文（客户端自动中英互译） |
| 向量存储 | `vector_migration.sql` (pgvector) + `embeddings.py` | entity/evidence/assertion embedding + HNSW |
| 语义消歧 | `entity_resolution.py` | 精确匹配 + 别名/embedding 打分（0.35名+0.30嵌+0.20别名），≥.90 自动合并 / .75-.90 人工 |
| 语义证据核验 | `evidence_verification.py` | 字符串→embedding 相似度 + 高风险用 LLM 判定 direct/partial/insufficient/contradicted |
| 指标 | `runtime/metrics.py` | 成本/重复率/接受率/核验分布 |

**metrics**：
```bash
python -m runtime.metrics --db-check
```

## 6. Neo4j 图投影

```bash
# 初始化约束/索引（Neo4j 启动后）
python -m runtime.neo4j.projection --init

# 全量重建（从 PostgreSQL）
python -m runtime.neo4j.projection --full

# 增量（处理 graph_outbox 事件）
python -m runtime.neo4j.projection --process-outbox

# 连接检查
python -m runtime.neo4j.projection --check

# PG ↔ Neo4j 一致性校验
python -m runtime.neo4j.consistency
```

Neo4j 浏览器：http://localhost:7474 （账号 `neo4j` / `neo4j_admin_password`）

## 7. 目录结构

```
runtime/
├── config/            # LLM 配置（local 已 gitignore）
├── llm_client.py      # OpenAI 兼容 LLM 客户端（复用自 geo-research）
├── extract.py         # LLM 结构化抽取助手
├── db.py              # PostgreSQL 访问层（复用 publish.py 约定）
├── migrations/
│   ├── l2_migration.sql   # L2 业务表（entity/relation/statement/evidence 等）
│   └── __init__.py        # 迁移执行器（L1→L2→L3）
├── l2/                # L2 六条 Pipeline 执行器
├── l3/                # L3 十条 Pipeline 执行器
├── neo4j/             # 图投影服务 + 一致性校验
├── visualize/         # Jupyter + pyvis 交互式图谱查看
├── docker-compose.yml # PostgreSQL + Neo4j 一键启动
└── requirements.txt   # runtime 额外依赖
```

## 7.5 在 VSCode 查看阶段性结果（交互式图谱）

用 **Jupyter + pyvis** 在 VSCode 里渲染可交互的知识图（缩放/拖拽/按类型筛色）。

```bash
# 1. 装 VSCode 插件: Jupyter (ms-toolsai.jupyter)
# 2. 装 Python 包
pip install -r runtime/requirements.txt

# 3. 跑完执行器后，导出图谱数据
python -m runtime.visualize.export
#   python -m runtime.visualize.export --brand <id> --tenant <id>   # 只看某品牌
#   python -m runtime.visualize.export --industry <id>              # 只看某行业

# 4. 在 VSCode 打开 runtime/visualize/knowledge_graph.ipynb → 选内核 → 运行全部
```

详见 `runtime/visualize/README.md`。备选：Neo4j Browser（localhost:7474）。

## 8. 数据流总览

```
L1 定义 → [L2] 行业情报(geo-research报告) → 抽实体/关系/事实 → PostgreSQL
        → [L3] 品牌资料(官网/文档) → 抽实体/核证据 → PostgreSQL
        → [Neo4j] 从 PostgreSQL 幂等投影（可重建）
        → [可视化] PostgreSQL → JSON → Jupyter+pyvis 交互图
```
