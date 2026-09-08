# Brand Atlas 知识图谱 · 使用说明

## 文档状态：历史运行手册（已停用）

> 本文档记录的是已停用的 `legacy/` PostgreSQL/Neo4j 运行时，仅供迁移核对，不是当前产品的启动方式。
> 当前请使用独立桌面版，见 [LOCAL_APP.md](../architecture/LOCAL_APP.md)。新的桌面版知识构建已在 `backend/` 和 `shared/` 中重新实现，运行时不再调用本文档中的旧命令。

> 合并自原 DATA_FLOW_AND_USAGE / USAGE / LAYERED_GRAPH_USAGE 与 runtime、visualize README。

## 1. 环境准备

### 1.1 安装依赖

```bash
pip install -r requirements.txt
```

依赖统一在根 `requirements.txt`，含可选 `local-models` 组（本地 embedding / NER 模型）。

### 1.2 启动数据库与图数据库

```bash
cd legacy && docker compose up -d
```

docker-compose（`legacy/docker-compose.yml`）拉起 PostgreSQL(pgvector) 与 Neo4j。默认端口与账号见 compose 文件 / 环境变量（以下可用 env 覆盖）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/brand_atlas` | PG 连接 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 连接 |
| `NEO4J_USER` / `NEO4J_PASSWORD` | `neo4j` / `neo4j_admin_password` | Neo4j 账号 |

### 1.3 运行时配置

私有运行配置放 `legacy/config/*.local.json`（已 gitignore）。参考模板：

- `legacy/config/llm-config.example.json` — LLM 模型/密钥
- `legacy/config/model-config.example.json` — embedding / NER 模型配置

## 2. 数据库迁移

```bash
python -m legacy.migrations --only l1        # 应用 legacy/database/schema.sql（L1 核心表）
python -m legacy.migrations --only l2_l3     # 应用 legacy/database/l2_l3_schema.sql（L2/L3 建表）
python -m legacy.migrations --check          # 仅列出迁移，不执行
```

发布 L1 注册库（common_knowledge/ YAML → PG）：

```bash
python -m legacy.database.publish_l1                 # 校验并打印 L1 注册库
python -m legacy.database.publish_l1 --out <path>    # 导出注册库 JSON 快照
python -m legacy.database.publish_l1 --seed          # UPSERT 进 PG entity_type/relation_type（L2/L3 写库前置）
```

## 3. L2 行业知识构建

处理行业/品类公开信息文档，产出行业实体、市场主题、趋势、竞品公共信息。

```bash
# 端到端八步（article_registration → … → promotion）
python -m legacy.industry.executor --all --file <doc.md>

# 只跑单步 / 指定参数
python -m legacy.industry.executor --pipeline knowledge_fusion --file <doc.md>
python -m legacy.industry.executor --all --file <doc.md> --skip-ner --confidence-threshold 0.75
```

常用参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--all` / `--pipeline` | — | 全链路 / 单步（见 `PIPELINES`） |
| `--file` / `--text` / `--document-uuid` | — | 输入：文件 / 原文 / 已注册文档 |
| `--profile-id` | `l2_industry` | L2 profile id |
| `--layer` | `l2_industry` | 图层标签 |
| `--tenant-id` | — | 门禁/主图租户 |
| `--skip-ner` | off | 关闭 NER（本地模型缺失降级） |
| `--unit-limit` | 200 | 证据单元数量上限 |
| `--confidence-threshold` | — | 门禁置信度下限 |
| `--knowledge-id` | — | 只晋升指定门禁候选 |

## 4. L3 品牌知识构建

处理品牌来源文档（产品、能力、定位、案例、内部文档）产出多租户品牌知识。

```bash
# 端到端九步（document_registration → … → promotion），品牌必填
python -m legacy.brand.executor --all --file <doc.md> --brand <brand_id>

# 只跑单步 / 不写库
python -m legacy.brand.executor --pipeline promotion --file <doc.md> --brand <brand_id>
python -m legacy.brand.executor --all --file <doc.md> --brand <brand_id> --dry-run
```

常用参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--brand` | **必填** | 品牌 key / id |
| `--tenant` | `default` | 租户 key |
| `--all` / `--pipeline` | — | 全链路 / 单步 |
| `--file` / `--text` | — | 输入 |
| `--source-type` / `--publisher` / `--canonical-url` / `--language` | — | 来源元数据 |
| `--access-level` | — | `public`/`internal`/`confidential`/`restricted` |
| `--dry-run` | off | 不写库 |
| `--skip-ner` / `--unit-limit` / `--confidence-threshold` / `--knowledge-id` | — | 同 L2 |

## 5. Neo4j 图投影

```bash
python -m legacy.neo4j.projection --init            # 应用 cypher_init.cypher
python -m legacy.neo4j.projection --full            # 全量重建
python -m legacy.neo4j.projection --process-outbox  # 增量同步 graph_outbox
python -m legacy.neo4j.projection --check           # 连通性检查
```

## 6. 运维健康指标

```bash
python -m legacy.core.metrics                 # 输出健康指标
python -m legacy.core.metrics --json          # 原始 JSON 输出
python -m legacy.core.metrics --db-check      # 先检查 DB 连通再出指标
```

## 7. 图谱可视化

可视化依赖 `legacy/visualize/assets/` 下的本地前端库（vis-network 等），支持**离线打开**，不需要 CDN。

### 7.1 交互式 Notebook

`legacy/visualize/knowledge_graph.ipynb`：在 Notebook 中加载 PG/Neo4j 数据，交互式查看图谱。

### 7.2 导出分层 2D 图（单文件 HTML）

```bash
python -m legacy.visualize.export --layer L1
python -m legacy.visualize.export --layer L2
python -m legacy.visualize.export --layer L3
```

产出 `legacy/visualize/output/{l1,l2,l3}_graph.json`。然后构建单文件分层 2D 图（数据内联、vis-network 走本地 assets，可直接 `file://` 打开）：

```bash
python scripts/build/build_layered_prototype.py
# → legacy/visualize/output/layered_2d.html
```

`layered_2d.html` 提供 L1/L2/L3 页签、按实体类型着色、节点点击详情、搜索过滤。

> **旧 HTML 清理**：若存在旧 pyvis 生成的 HTML，用以下脚本去除失效脚本引用（404 → 本地 assets）：

```bash
python scripts/maintenance/fix_html_stale.py
python scripts/maintenance/fix_html_cdn.py
```

### 7.3 其他脚本

| 脚本 | 作用 |
|------|------|
| `scripts/build/render_graph.py` | 直接渲染 JSON 为图谱（使用本地 assets 颜色映射） |
| `scripts/build/build_layered_prototype.py` | 由 export 的 JSON 产出分层 2D HTML |
| `scripts/maintenance/fix_html_stale.py` / `scripts/maintenance/fix_html_cdn.py` | 清理旧 HTML 的失效/外部脚本引用 |

## 8. 测试与验证

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

覆盖 L1 契约校验（`tests/test_l1_contracts.py`）与运行时回归（`tests/test_runtime_regressions.py`）。

## 9. 端到端数据流（概括）

```
来源文档 (L2: 行业公开信息 / L3: 品牌文档)
  → evidence_parsing        span → Evidence Unit
  → candidate_extraction    Evidence Unit → knowledge_candidate (L1-aware)
  → candidate_normalization 指称统一 / 去重
  → candidate_vectorization pgvector 向量化
  → knowledge_fusion        跨文档融合 → gate_candidate
  → promotion               门禁晋级 → active graph (PostgreSQL)
  → projection              增量/全量 → Neo4j 查询投影
```

数据和中间表（evidence / candidate / gate_candidate / active graph）建表唯一定义在 `legacy/database/l2_l3_schema.sql`，详见 [DESIGN.md](../architecture/DESIGN.md)。
