# Brand Atlas Knowledge Graph

> **版本**: 1.2.0
> **创建日期**: 2026-08-07 · **更新日期**: 2026-08-26

Brand Atlas 知识图谱是一个**多层知识工程系统**，用于持续构建、校验、检索和更新结构化知识，
并为 L2/L3 的知识构建、治理、检索和持续更新提供统一约束。

当前已形成三层技术基线：
- **L1 通用知识层**（v1.2.0）：跨品牌、跨行业复用的方法与规范层
- **L2 行业知识层**（v1.0.0）：行业市场坐标系，定义数据域、Pipeline、Schema 和策略
- **L3 品牌认知层**（v1.0.1）：多租户品牌实例、产品版本、能力映射、证据链和图谱投影规范

L1 不是行业百科，也不是客户品牌知识库，而是：统一知识对象定义、统一关系表达、统一任务输出规范、统一证据规则。

> 详细架构设计见 [docs/DESIGN.md](docs/DESIGN.md)，逐层输入输出、运行命令与成熟度判断见 [docs/USAGE.md](docs/USAGE.md)。

## 四层知识架构

| 层级 | 内容 | 位置 |
|------|------|------|
| **L1 通用知识层** | 本体、陈述、上下文、来源、治理、更新和检索协议 | common_knowledge/ |
| **L2 行业/品类知识层** | 行业实体、市场主题、行业趋势、竞品公共信息 | runtime/industry/ + database/ |
| **L3 品牌认知层** | 品牌产品、能力、定位、案例、内部文档 | runtime/brand/ + database/ |
| L4 动态反馈层 | 查询反馈、校验结果、采纳/拒绝和知识更新反馈 | 后续实现 |

## 目录结构

```
Knowledge_Graph/
├── requirements.txt               # 统一 Python 依赖（含可选本地模型组）
├── common_knowledge/              # L1 通用知识层（registry 唯一数据源）
│   ├── ontology/                  # L2 行业、L3 品牌两套独立本体
│   ├── sources/                   # 来源类型 + 质量/权威规则
│   ├── tasks/                     # 知识构建/刷新/晋升/发现任务
│   ├── policies/                  # 证据、冲突、上下文、晋升、报告、发现策略
│   ├── contracts/                 # 治理、运行协议等通用契约
│   └── schema_profiles/           # 抽取规则和 L2/L3 独立 profile
├── database/                      # 统一数据库 Schema 层（单一事实源）
│   ├── schema.sql                 # L1 核心表（entity_type/relation_type/…）
│   ├── l2_l3_schema.sql           # L2/L3 证据→候选→门禁→主图统一建表
│   └── publish_l1.py              # L1 注册库发布（JSON snapshot）
├── runtime/                       # 可执行代码（按执行层级/阶段分目录）
│   ├── core/                      # ① 基础设施层：db / knowledge_service / metrics
│   ├── clients/                   # ② 外部模型适配器：embeddings / ner_client
│   ├── ontology/                  # ③ L1 本体校验（读 common_knowledge/）
│   ├── extraction/                # ④ 证据→候选：evidence_parsing / candidate_extraction
│   ├── fusion/                    # ⑤ 跨文档融合：fusion_service
│   ├── promotion/                 # ⑥ 门禁晋级：promotion_service
│   ├── common/                    # L1 registry / policy_engine（读 common_knowledge/）
│   ├── industry/                  # L2 八条 Pipeline（executor.py + pipelines/）
│   ├── brand/                     # L3 九条 Pipeline（executor.py + pipelines/）
│   ├── migrations/                # 迁移执行器（指向 database/*.sql）
│   ├── neo4j/                     # 图投影服务 + 一致性校验
│   ├── visualize/                 # Jupyter + pyvis 交互式图谱查看（assets/ 本地库）
│   ├── config/                    # LLM/模型配置示例（*.local.json 已 gitignore）
│   └── docker-compose.yml         # PostgreSQL(pgvector) + Neo4j
├── scripts/                       # 一次性/运维脚本（图谱渲染、HTML 修复）
└── docs/                          # 文档：DESIGN.md / USAGE.md (+ examples/)
```

## 快速上手

```bash
# 1. 安装依赖（含可选本地模型组）
pip install -r requirements.txt

# 2. 启动 PostgreSQL(pgvector) 与 Neo4j
cd runtime && docker compose up -d && cd ..

# 3. 初始化数据库迁移
python -m runtime.migrations --only l1
python -m runtime.migrations --only l2_l3

# 4. 构建 L2 行业知识（单文档）
python -m runtime.industry.executor --all --file <doc.md>

# 5. 构建 L3 品牌知识（单文档，需指定品牌）
python -m runtime.brand.executor --all --file <doc.md> --brand <brand_id>
```

## 当前实现状态

| 能力 | 当前状态 |
|------|----------|
| L1 YAML/Schema/策略定义 | 已完成，可执行全项目校验 |
| L1 PostgreSQL 注册库 | 已有 Schema 和发布器，需外部 PostgreSQL 实例 |
| L2 行业数据处理 | 八步消息链（证据→候选→门禁→主图）、步骤级事务和幂等重跑已实现 |
| L3 品牌数据处理 | 九步消息链（应证→候选→门禁→主图）+ 敏感内容提醒已实现 |
| Neo4j 图谱投影 | 全量重建、outbox 增量、Cypher 初始化和一致性检查已实现 |
| L4 动态观测 | 仅定义对象，未实现 |

本仓库已进入"可生成 PostgreSQL 知识实例并投影到 Neo4j"的工程阶段，但尚不能视为经过生产环境验证的完整图谱产品。

## 版本规范与维护

- **语义化版本**：主版本=实体/关系不兼容变化；次版本=新增类型/意图/任务模板；修订=文字/示例/描述修正。
- 实体/关系、意图分类、来源等级、规则策略、正反例、外部标准均按各自评审节奏维护（详见 L1 定义）。

## 参考标准

- [Schema.org](https://schema.org/)
- [W3C SKOS](https://www.w3.org/TR/skos-reference/)
- [Wikidata](https://www.wikidata.org/)
- [Graph RAG](https://arxiv.org/abs/2404.16130)