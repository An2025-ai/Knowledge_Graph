# Brand Atlas 知识图谱 · 架构设计

> 本文整合《L2/L3 知识图谱构建技术执行方案》与《系统工程优化技术方案》的精华，描述系统架构、数据流、数据库与投影。

## 1. 总体架构

Brand Atlas 是一个**证据驱动、分层治理**的知识图谱系统。PostgreSQL 为单一事实源，Neo4j 为可重建的查询投影。

```
  来源文档
    │
    ▼
 ┌─────────────────────────────── L2/L3 执行链 ───────────────────────────────┐
 │  evidence_parsing   candidate_extraction   fusion_service   promotion_service │
 │  (span→evidence)    (证据→候选)            (跨文档融合)      (门禁晋级)        │
 └──────┬──────────────────────────────────────────────────────────┬───────────┘
        │                                                          │
        ▼                                                          ▼
   evidence/候选表（legacy/database/l2_l3_schema.sql）      active graph（主图）
                                                                  │
                                                                  ▼
                                                        Neo4j 投影（可重建）
```

**分层原则**：
- **L1 通用知识层**：只放跨行业、跨品牌复用的规范（本体、陈述、上下文、来源、治理、更新、检索协议），不含任何品牌事实。
- **L2 行业知识层**：行业实体、市场主题、行业趋势、竞品公共信息。
- **L3 品牌认知层**：品牌产品、能力、定位、案例、内部文档。
- **L4 动态反馈层**：查询反馈、校验结果、采纳/拒绝。仅定义对象，未实现。

## 2. shared/ 与 legacy/ 执行分层

新架构将依赖无关的领域规则放到 `shared/`，把 PostgreSQL/Neo4j 运行时放到
`legacy/`。桌面应用只依赖 `shared/`，旧服务端可以依赖 `shared/`，依赖方向单一：

| 阶段 | 模块 | 职责 |
|------|------|------|
| ① 共享知识规则 | `shared/knowledge/` | Registry、策略、协议、检索和规则 API |
| ② 共享本体校验 | `shared/ontology/` | 读取 `common_knowledge/`，校验 Profile |
| ③ 共享证据→候选 | `shared/extraction/` | span→evidence unit；证据→候选 |
| ④ 旧基础设施 | `legacy/core/`（db, knowledge_service, metrics） | PostgreSQL 访问、upsert、旧持久化适配器 |
| ⑤ 旧模型适配 | `legacy/clients/`（embeddings, ner_client） | pgvector 向量化、UIE NER |
| ⑥ 旧流程 | `legacy/industry/`, `legacy/brand/`, `legacy/fusion/`, `legacy/promotion/` | 旧 L2/L3 Pipeline、融合和门禁晋级 |

> `shared/` 只包含可被多个运行时复用的纯领域能力，不保存数据库连接，也不调用旧服务端适配器。

## 3. L2/L3 知识构建链路（证据 → 候选 → 门禁 → 主图）

核心链路从来源文档生成可信结构化知识，共经 **证据 → 候选 → 门禁 → 主图** 四阶段：

1. **evidence_parsing（证据切分）**：将文档切分为证据单元（Evidence Unit），每个单元绑定来源 span 原文，是后续抽取的最小可信单位。
2. **candidate_extraction（候选抽取）**：从证据单元抽取 `knowledge_candidate`（实体、关系、陈述候选项），**L1-aware**——参考 L1 注册库的类型与关系约束、由 LLM 依据上下文赋予置信度。
3. **candidate_normalization（候选归一）**：统一指称、去重、规范化实体与关系候选。
4. **candidate_vectorization（候选向量化）**：用 embeddings 为候选生成 pgvector 向量，供相似度融合与检索。
5. **knowledge_fusion（跨文档融合）**：跨多文档/多证据合并重复候选、消解冲突，产出 `gate_candidate`。
6. **promotion（门禁晋级）**：依据知识晋升策略（`knowledge_promotion_policy`）校验门禁（源头经过白名单预过滤、不再做 source 级门禁），将合格候选写入 active graph 主图。

> 输入侧已做来源白名单与治理预过滤，故晋级环节不再重复 source-class/domain 门禁（commit `61877d3`）。

## 4. L2 / L3 Pipeline

每个 executor 把证据→主图链路拆成若干可独立重跑的 Pipeline（幂等、步骤级事务）。

**L2 行业知识八步**（`legacy/industry/executor.py` `ALL_ORDER`）：

```
article_registration → content_parsing → evidence_unit_merge →
candidate_extraction → candidate_normalization → candidate_vectorization →
knowledge_fusion → promotion
```

**L3 品牌知识九步**（`legacy/brand/executor.py` `DEFAULT_PIPELINES`）：

```
document_registration → sensitive_content_warning → content_parsing →
evidence_unit_merge → candidate_extraction → candidate_normalization →
candidate_vectorization → knowledge_fusion → promotion
```

- 单文档：`--file <doc.md>` 或 `--text`；指定品牌需 `--brand`（L3 必填）。
- 文件路径经 `--file` 读取，默认以内容哈希/注册表去重。
- `--skip-ner` 关闭 NER（缺模型本地降级）、`--unit-limit` 限证据单元数、`--confidence-threshold` 设门禁置信度下限、`--knowledge-id` 只晋升指定候选。
- `--dry-run`（L3）不写库。

## 5. 数据库

PostgreSQL 是旧运行时的单一事实源，定义集中在 `legacy/database/`：

| 文件 | 内容 |
|------|------|
| `legacy/database/schema.sql` | L1 核心表：knowledge_definition, knowledge_version, entity_type, relation_type, intent_definition, task_template, source_policy, quality_rule, example_case… |
| `legacy/database/l2_l3_schema.sql` | L2/L3 **证据→候选→门禁→主图统一建表**（evidence, knowledge_candidate, gate_candidate, active graph 等 35 表） |

**迁移**：`legacy/migrations/__init__.py` 的 `MIGRATIONS` 只映射两把键，`ORDER = ["l1", "l2_l3"]`：

```bash
python -m legacy.migrations --only l1       # 应用 legacy/database/schema.sql
python -m legacy.migrations --only l2_l3    # 应用 legacy/database/l2_l3_schema.sql
```

> 只往 `legacy/database/l2_l3_schema.sql` 新增旧运行时表，新桌面版表结构应进入 `backend/app/schema.sql`。

## 6. Neo4j 图投影

Neo4j 是排重建的查询投影，从 PG 的 `graph_outbox` 事件队列（或全量快照）幂等 MERGE：

```bash
python -m legacy.neo4j.projection --init            # 应用 cypher_init.cypher
python -m legacy.neo4j.projection --full            # 全量重建
python -m legacy.neo4j.projection --process-outbox  # 增量同步
python -m legacy.neo4j.projection --check           # 连通性检查
```

- 实体标签通过 L1 registry 解析（`get_common_registry().neo4j_entity_label`），未命中的有确定性回退。
- 层标记：L3 = owner_brand 非空、L2 = 有 industry 标签、L1 = 其余共享。
- 一致性校验见 `legacy/neo4j/consistency.py`。

## 7. 优化手段（来自 OPTIMIZATION_TECH_PLAN）

- **证据单元化**：以证据为最小单位切分，减少大文本一次抽取的信息损耗。
- **幂等与重跑**：步骤级事务，失败可局部重跑，不污染主图。
- **向量化去重/融合**（pgvector + bge-m3）：候选向量化后按相似度合并重复，提升融合精度。
- **本地模型降级**：NER（PaddleNLP UIE）缺省时自动降级，不阻断主链路。
- **旧运行时依赖单源**：根 `requirements.txt`；桌面版依赖单独维护在 `requirements-desktop.txt`。

## 8. 关键约束

- PostgreSQL 是唯一事实源；Neo4j 随时可 `--full` 重建。
- 旧服务端新表只能进 `legacy/database/l2_l3_schema.sql`；桌面版本地表进入 `backend/app/schema.sql`。
- 已删除/迁移的子系统（geo-research、brand_knowledge、industry_knowledge、旧 flat 模块）不可再当可运行代码，见 memory。
