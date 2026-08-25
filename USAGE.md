# Brand Atlas Knowledge Graph — 使用说明

> **版本**: 1.2.0  
> **更新日期**: 2026-08-11  
> **适用范围**: L1 通用知识层 v1.2.0 + L2 行业知识层 v1.0.0 + L3 品牌认知层 v1.0.1

本说明涵盖知识图谱的完整使用流程：理解四层架构、浏览知识定义、修改与发布知识、数据库接入、L2 行业层的使用，以及 L3 品牌认知层的使用。

> 本文保留概念说明。当前执行器的准确输入输出、CLI、限制和图谱阶段判断以 [DATA_FLOW_AND_USAGE.md](DATA_FLOW_AND_USAGE.md) 为准。

---

## 1. 系统总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    四层知识架构                                   │
├──────────────┬──────────────────────────────────────────────────┤
│ L1 通用知识层 │ 定义对象/关系/意图/任务/证据规则（方法与规范）        │
│ L2 行业知识层 │ 实例化共享行业坐标系（品类/角色/问题/能力/主题）      │
│ L3 品牌认知层 │ 十步执行器已实现；真实数据、治理门禁和图投影需集成验收 │
│ L4 动态观测层 │ 保存待验证的时效性资料快照（未实现，仅定义对象）       │
└──────────────┴──────────────────────────────────────────────────┘
```

**核心原则**：
- **稳定规则结构化**：规则和模板以 YAML 定义，版本化管理
- **品牌/行业事实不进入 L1**：L1 只包含通用规则，具体数据在 L2-L3
- **YAML 是源，数据库是视图**：修改都在 YAML 中进行，通过脚本发布到 PostgreSQL
- **所有定义必须有版本、来源和变更记录**：每个文件都有 `meta` 和 `changelog`

---

## 2. 目录结构总览

```
Knowledge_Graph/
├── README.md                        # 项目总览
├── .gitignore                       # Git 忽略规则（已初始化 Git，标签 v1.1.0）
│
├── common_knowledge/                # ── L1 通用知识层 ──
│   ├── ontology/
│   │   ├── l2_industry/             # L2 行业本体：实体、关系、指标
│   │   └── l3_brand/                # L3 品牌本体：实体、关系、指标
│   ├── intents/
│   │   ├── intent_types.yaml        # 13 种意图 + 7 个决策阶段
│   │   └── intent_types.yaml        # 通用知识查询意图
│   ├── sources/
│   │   ├── source_types.yaml        # 13 种来源类型（3级权威）
│   │   └── authority_rules.yaml     # 20 条质量规则
│   ├── tasks/                       # 4 个知识构建/治理任务
│   │   ├── industry_knowledge_build.yaml    # 行业知识构建
│   │   ├── industry_knowledge_refresh.yaml  # 行业知识刷新
│   │   ├── source_discovery.yaml    # 来源发现与验证
│   │   └── knowledge_promotion.yaml # 知识晋升
│   ├── policies/                    # 6 个策略文件
│   │   ├── claim_policy.yaml        # 事实与主张策略
│   │   ├── conflict_policy.yaml     # 冲突处理策略
│   │   ├── context_policy.yaml      # 上下文检索策略
│   │   ├── source_discovery_policy.yaml    # 来源发现策略
│   │   ├── knowledge_promotion_policy.yaml # 知识晋升策略
│   │   └── report_evidence_policy.yaml     # 报告证据策略
│   ├── contracts/                   # 治理、运行协议等通用契约
│   └── schema_profiles/             # 抽取规则和 L2/L3 独立 Profile
│
├── industry_knowledge/              # ── L2 行业知识层 ──
│   ├── README.md                    # L2 技术文档（1916 行）
│   ├── scopes/                      # 行业范围定义
│   │   └── industry_scope.example.yaml
│   ├── requirements/                # 研究需求文件
│   │   └── industry_requirement.example.yaml
│   ├── schemas/                     # 8 个 JSON Schema
│   ├── taxonomies/                  # 分类模板
│   │   └── capabilities/            # 能力字典模板
│   ├── pipelines/                   # 6 个数据处理流水线
│   ├── policies/                    # 3 个 L2 策略
│   └── examples/crm/                # CRM 试点示例
│       └── scope.yaml
│
├── brand_knowledge/                 # ── L3 品牌认知层 ──
│   ├── README.md                    # L3 技术文档（1069 行）
│   ├── scopes/                      # 品牌接入范围 + 多租户
│   ├── sources/                     # 品牌来源策略和权限
│   ├── domains/                     # 11 数据域 + 抽取 Profile
│   ├── ontology/                    # L3 实体/关系/assertion_kind
│   ├── schemas/                     # 9 个 JSON Schema
│   ├── pipelines/                   # 10 个品牌处理流水线
│   ├── policies/                    # 6 个 L3 策略
│   ├── database/                    # L3 迁移 SQL（11 表 + RLS）
│   ├── examples/                    # DeepCleer 试点数据
│   └── skills/                      # 12 个逻辑 Skills
│
└── database/                        # ── L1 数据库层 ──
    ├── schema.sql                   # PostgreSQL 10 张表（9 核心 + 1 辅助）
    ├── publish.py                   # YAML → 数据库 发布脚本
    └── README.md                    # 数据库初始化指南
```

---

## 3. L1 通用知识层使用说明

### 3.1 两套独立业务本体

L1 分别保存两套完整定义，通过 Profile 调用：

- `l2_industry` 只加载 L2 行业实体、关系和指标。
- `l3_brand` 只加载 L3 品牌实体、关系和指标。

两层不继承共同业务本体，不建立跨层关系，也不相互读取指标。同名代码可以存在，但只按
当前 Profile 的定义解析。`metric` 和 `evidence` 不是构图实体；指标保存在本层
`metrics.yaml`，证据属于运行时记录。

```powershell
python -m runtime.common.entity_types --profile l2_industry
python -m runtime.common.relation_types --profile l2_industry
python -m runtime.common.entity_types --profile l3_brand
python -m runtime.common.relation_types --profile l3_brand
```

### 3.2 如何新增一个实体类型

1. 根据归属层打开 `common_knowledge/ontology/l2_industry/entities.yaml` 或 `common_knowledge/ontology/l3_brand/entities.yaml`
2. 在 `entity_types:` 列表末尾添加新实体，格式如下：

```yaml
- type: my_entity
  canonical_name: 我的实体
  canonical_name_en: My Entity
  definition: >
    该实体的定义说明
  examples:
    - 示例 1
    - 示例 2
  required_fields: [id, type, canonical_name, status, version]
  optional_fields: [aliases, description, scope, source_refs]
  constraints:
    - 约束条件 1
  version: 1.1.0
```

3. 更新文件头部 `meta.version` 和底部 `changelog`
4. 如果新实体参与关系，只更新同目录的 `relations.yaml`，不得引用另一层类型

> **注意**：修改 entity 类型属于主版本变更，如果破坏兼容性应升主版本（如 2.0.0）；仅新增类型属于次版本变更（1.x.0）。

### 3.3 实体记录格式（L2/L3 实际使用）

实际知识记录遵循 `ent_{type}_{short_name}` 命名：

```yaml
id: ent_crm_salesforce
type: brand
canonical_name: Salesforce
aliases: [Salesforce.com, 赛富时]
description: 客户关系管理和企业软件品牌
scope: shared
status: active
source_refs: [src_salesforce_official]
created_at: 2026-08-11
updated_at: 2026-08-11
version: 1.0.0
```

### 3.4 如何理解意图分类

`intents/intent_types.yaml` 定义双层意图模型：

```
主意图（13种）                    决策阶段（7个）
─────────────────────────       ─────────────────────────
definition    定义/是什么          awareness    认知
education     教育/原理            problem      问题识别
trend         趋势/行业变化        solution     方案探索
brand         品牌认知             evaluation   比较评估
problem_solving 问题解决           decision     购买决策
recommendation  推荐               implementation 使用实施
comparison    对比选择             retention    复购/替代
review        评测验证
risk          风险/限制
pricing       价格/成本
case          案例/证明
how_to        操作方法
alternative   替代方案
```

查询意图只用于定义知识检索的语义范围；具体提问词生成不属于当前 L1 项目。

### 3.5 事实 vs 主张 vs 观测 vs 推断

依据 `policies/claim_policy.yaml`：

| 类别 | 判定 | 例子 |
|------|------|------|
| **fact** | 有来源、客观可验证 | "该功能 2024 年 Q3 上线" |
| **claim** | 有来源、但含立场/主观 | "行业领先"（品牌自述） |
| **observation** | 特定时间的快照 | "某季度报告披露的市场数据" |
| **inference** | 由多条前提推导 | "基于数据，品牌可见度上升" |

**关键规则**：
- 没有来源的内容不得标记为 fact
- 品牌自述必须标记为 claim（`stance: self_claim`）
- 单次搜索观测不得直接写入稳定规则

---

## 4. L2 行业知识层使用说明

### 4.1 L2 是什么

L2 不是积累网页，而是建立**可复用的行业坐标系**：
- 行业中有什么品类？
- 有哪些用户角色和问题？
- 用户在什么场景寻找什么能力？
- 购买时关注哪些决策因素？
- 哪些结论有证据、何时有效、适用于什么范围？

### 4.2 如何使用 L2（完整流程）

```
步骤 1: 定义行业范围（scopes/）
   └─ 创建 industry_scope.example.yaml 对应的本行业 scope

步骤 2: 编译研究需求（requirements/）
   └─ 生成 Industry Knowledge Requirement 契约文件

步骤 3: 提交给外部资料采集工具生成行业资料
   └─ 采集工具返回：资料 + 引用清单 + 证据包 + 覆盖台账

步骤 4: 报告解析与证据解析（pipelines/）
   └─ report_ingestion → evidence_resolution

步骤 5: 知识抽取与分类（pipelines/）
   └─ extraction → 实体/关系/陈述，绑定原始证据

步骤 6: 知识晋升（pipelines/）
   └─ promotion → 通过 10 道门禁后写入稳定 L2
```

### 4.3 理解 Industry Knowledge Requirement

参考 `requirements/industry_requirement.example.yaml`。这是发给资料采集工具的任务合同，定义了：
- `required_dimensions`：必须研究哪些数据维度
- `source_requirements`：允许哪些来源类型、不允许哪些
- `report_contract`：报告格式、引用格式、必需交付物

### 4.4 L2 数据九大域

| 数据域 | 内容 |
|--------|------|
| 市场分类域 | 行业→品类→子品类→产品 |
| 市场参与者域 | 品牌、竞品、机构、来源主体 |
| 用户与决策链域 | 用户角色、组织属性、决策角色 |
| 问题与使用场景域 | problem / JTBD / use_case / outcome |
| 标准能力域 | 行业能力字典（v1.1.0 用 capability 实体） |
| 购买决策因素域 | 决策因素字典 |
| 主题与问题空间域 | 稳定主题树 |
| 行业事实域 | fact/claim/observation + 统计趋势 |
| 来源与内容生态域 | 来源实例、内容实体、证据链 |

### 4.5 L2 IS NOT

⚠️ L2 **不保存**：
- 客户内部文档和未公开信息
- 未经验证的单次搜索结果
- 社区帖子、用户评论、UGC 内容
- 没有来源的 LLM 推断
- 单个客户的目标定位和内容策略

> 注意：本版本明确**不采集社区网站和 UGC 平台**（知乎、小红书、B站、Reddit、G2 等）。这是设计决策，不是遗漏。

---

## 5. L3 品牌认知层使用说明

### 5.1 L3 是什么

L3 用于把某个客户品牌的官网、企业知识库、产品资料、案例、资质和经审核的内部信息，转换为可追溯、可版本化、可授权的**品牌知识子图**。核心产物是"品牌认知模型"：品牌是谁、提供什么产品、服务谁、解决什么问题、具备什么能力、有哪些证据、能说什么、不能说什么。

**复用方式**：
```
共享 L1 方法、本体和规则
    +
共享 L2 行业、品类、用户、问题、能力
    +
每个客户独立的 L3 品牌实例、私有证据、品牌口径和内容资产
```

### 5.2 L3 核心概念

**多租户隔离**（`policies/tenant_isolation.yaml`）：
- `tenant_id` = 客户数据安全边界
- `brand_id` = 目标品牌（一个租户可管理多个品牌）
- L2 实体为共享只读对象，不携带客户内部信息
- PostgreSQL 用 RLS 强制 `tenant_id = current_setting('app.tenant_id')`

**断言中心模型**（Assertion-centric）：
- 事实/主张/观测/推断存储为 `assertion`（带证据和条件）
- 每个 Assertion 有 `statement_class`（L1 四分类）+ `assertion_kind`（L3 业务语义）
- `assertion_kinds.yaml` 定义 8 种：identity_fact, product_spec, self_claim, attributed_claim, third_party_fact, internal_fact, draft_claim, inference

**权限传播**（`policies/permission_propagation.yaml`）：
- access_level（public/internal/confidential/restricted）沿证据链传播
- 公开网页不能引用只由 confidential 证据支持的结论

### 5.3 L3 文档处理流程（10 个 Pipeline）

```
来源登记 → 原件门禁 → 版式解析 → 语义分块 → 候选抽取
→ L3 层内实体归一 → 断言分类 → 证据核验 → 审核晋升
```

对应 `brand_knowledge/pipelines/` 下的 10 个文件。

### 5.4 L3 数据域（11 个）

identity, product_portfolio, positioning_and_category, audience_and_decision,
capability_and_use_case, deployment_integration, security_compliance,
proof_and_case, service_and_poc, messaging_and_content, competition_mapping

### 5.5 如何接入一个新品牌

1. 复制 `scopes/brand_scope.example.yaml` 为你的品牌，填写品牌信息、来源范围、必需维度
2. 登记来源清单（`sources/source_inventory.example.yaml`）
3. 按 10 个管道流程解析文档、抽取实体、映射 L2、核验证据
4. 人工审核后发布 `brand_snapshot`

### 5.6 L3 数据库

`brand_knowledge/database/brand_l3_migration.sql` 定义了 10 张业务表（tenant、brand_workspace、assertion、assertion_evidence、claim_policy 等）+ RLS。这是与 L1 定义注册库（`database/schema.sql`）**独立**的迁移。

该迁移依赖 `runtime/migrations/l2_migration.sql` 提供的 `entity`、`evidence`、`document` 等基础表。使用 `python -m runtime.migrations migrate` 按 L1 → L2 → L3 顺序初始化，随后可以运行 Neo4j 投影。

### 5.7 L3 IS NOT

- 不做 Context Builder、向量召回、混合检索、Rerank（后续应用阶段）
- 不保存原始客户业务数据、订单明细、个人敏感数据
- 不把品牌宣传语自动升级为客观事实
- 社区网站和 UGC 不属于 L3 采集范围

---

## 6. 数据库使用说明

### 6.1 初始化 L1 数据库

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 创建数据库（在 PostgreSQL 中执行）
CREATE DATABASE brand_atlas_kg;
CREATE USER kg_admin WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE brand_atlas_kg TO kg_admin;

# 3. 设置环境变量（Windows PowerShell）
$env:KG_DB_HOST = "localhost"
$env:KG_DB_PORT = "5432"
$env:KG_DB_NAME = "brand_atlas_kg"
$env:KG_DB_USER = "kg_admin"
$env:KG_DB_PASSWORD = "your_password"

# 4. 初始化 Schema
cd "d:\Brand Atlas\Knowledge_Graph"
python database/publish.py --init-db
```

### 6.2 验证全项目（无需数据库）

```bash
python database/publish.py --validate
```

该命令检查全部 YAML/JSON、重复键、JSON Schema 与示例、L1 交叉引用，以及发布字段能否写入 JSONB。

### 6.3 发布 L1 到数据库

```bash
# 先 dry-run 验证（不写入）
python database/publish.py --dry-run

# 正式发布全部
python database/publish.py

# 只发布单个文件
python database/publish.py --file ontology/l2_industry/entities.yaml
```

### 6.4 数据库 10 张表（9 核心 + 1 辅助）

| 表名 | 对应 YAML | 用途 |
|------|-----------|------|
| `knowledge_definition` | 所有文件 | 文件版本元数据 |
| `knowledge_version` | 自动 | 版本变更历史 |
| `entity_type` | ontology/l2_industry/entities.yaml、ontology/l3_brand/entities.yaml | 两套独立构图实体类型 |
| `relation_type` | ontology/l2_industry/relations.yaml、ontology/l3_brand/relations.yaml | 两套独立层内关系类型 |
| `intent_definition` | intents/intent_types.yaml | 13 种意图 |
| `task_template` | tasks/*.yaml | 4 个知识构建/治理任务 |
| `source_policy` | sources/source_types.yaml | 13 种来源类型 |
| `quality_rule` | sources/authority_rules.yaml | 20 条质量规则 |
| `example_case` | 预留 | 评测案例表，当前不随 L1 发布 |
| `decision_stage` | intents/intent_types.yaml | 7 个决策阶段（辅助表） |

---

## 7. 版本与变更管理

### 6.1 语义化版本规则

| 变化类型 | 版本增量 | 示例 |
|----------|----------|------|
| 实体/关系不兼容变化 | 主版本 | 1.0.0 → 2.0.0 |
| 新增类型/意图/任务 | 次版本 | 1.0.0 → 1.1.0 |
| 文字/示例修正 | 修订版本 | 1.1.0 → 1.1.1 |

### 6.2 版本历史

| 版本 | 标签 | 内容 |
|------|------|------|
| v1.0.0 | Git tag | L1 初始版本（15 实体、20 关系、8 来源、5 任务、3 策略） |
| v1.1.0 | Git tag | L1 升级（19 实体、27 关系、13 来源、9 任务、6 策略）+ L2 完整定义 |
| v1.2.0 | Git tag | L1 升级（21 实体、31 关系）+ L3 品牌认知层完整定义 |

### 6.3 变更流程

```
发现新规范或问题
  → 创建变更提案
  → 评估是否影响现有任务
  → 更新定义/规则/模板
  → 运行回归样例（database/publish.py --validate）
  → 小范围灰度
  → 发布新版本
  → 记录变更说明
```

### 6.4 Git 操作速查

```bash
# 查看当前版本
git tag -l

# 查看历史
git log --oneline

# 修改后提交
git add -A
git commit -m "描述你的变更"
git tag v1.1.1

# 回滚到某版本
git checkout v1.0.0
```

---

## 8. 快速上手示例

### 场景 A：为现有品牌进行品牌导入

1. 参考 `common_knowledge/tasks/industry_knowledge_build.yaml` 定义构建任务
2. 收集可追溯来源并按 L1 本体抽取实体、关系和陈述
3. 运行关系、证据、冲突和上下文校验
4. 通过 `knowledge_promotion` 流程晋升为可检索知识

### 场景 B：为某个行业建立 L2 知识库

1. 复制 `industry_knowledge/scopes/industry_scope.example.yaml` 为你的行业
2. 修改行业名称、品类、市场、目标受众
3. 复制 `industry_knowledge/requirements/industry_requirement.example.yaml`
4. 生成研究需求并交给外部采集工具，返回后按 pipelines/ 定义的处理流程抽取和验证知识
5. 报告返回后，按 pipelines/ 定义的处理流程抽取和验证知识

### 场景 C：验证当前知识定义是否一致

```bash
python database/publish.py --validate
```

如果新增了实体类型但忘记在 relations.yaml 引用，或新增了来源类型但没在 authority_rules 出现，验证会提示不一致。

---

## 9. 参考资源

- [L1 设计与使用说明](L1_DESIGN_AND_USAGE.md)
- [L2 技术文档](industry_knowledge/README.md)
- [Schema.org](https://schema.org/)
- [W3C SKOS](https://www.w3.org/TR/skos-reference/)
- [Graph RAG 论文](https://arxiv.org/abs/2404.16130)
