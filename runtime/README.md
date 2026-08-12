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
```

## 2. 初始化数据库

```bash
export KG_DB_HOST=localhost KG_DB_PORT=5432 KG_DB_NAME=brand_atlas_kg KG_DB_USER=kg_admin KG_DB_PASSWORD=kg_admin_password

# 一键依次跑 L1 → L2 → L3 迁移
python -m runtime.migrations migrate

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
python -m runtime.l2.executor --pipeline requirement_compilation --scope <scope.yaml>

# 报告摄入：把 geo-research 生成的 Markdown 报告解析成候选
python -m runtime.l2.executor --pipeline report_ingestion --report <report.md>

# 知识抽取：LLM 从报告候选抽出 实体/关系/事实（--dry-run 先试跑不写库）
python -m runtime.l2.executor --pipeline extraction --report <report.md> --dry-run

# 晋升：10 道门禁，通过即稳定
python -m runtime.l2.executor --pipeline promotion

# 一键全流程
python -m runtime.l2.executor --all --scope <scope.yaml> --report <report.md>
```

## 5. L3 品牌知识层执行器

```bash
# 来源登记 + 文档解析 + 候选抽取（核心，走 LLM）
python -m runtime.l3.executor --all --file <brand_doc.md> --brand <brand_id> --dry-run

# 单步
python -m runtime.l3.executor --pipeline candidate_extraction --file <doc.md> --brand <brand_id>
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
        → [L3] 品牌资料(官网/文档) → 抽实体/映射L2/核证据 → PostgreSQL
        → [Neo4j] 从 PostgreSQL 幂等投影（可重建）
        → [可视化] PostgreSQL → JSON → Jupyter+pyvis 交互图
```
