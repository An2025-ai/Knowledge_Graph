# Brand Atlas Knowledge Graph

> **版本**: 1.2.0
> **状态**: 规范与样例可用，L2/L3 执行链路待实现
> **创建日期**: 2026-08-07  
> **更新日期**: 2026-08-11  

## 概述

Brand Atlas 知识图谱是一个多层知识工程系统，用于支持 GEO（生成式引擎优化）、
品牌市场认知分析、提问词生成、主题规划和内容优化。

当前已形成三层技术基线：
- **L1 通用知识层**（v1.2.0）：跨品牌、跨行业复用的方法与规范层
- **L2 行业知识层**（v1.0.0）：行业市场坐标系，定义数据域、Pipeline、Schema 和策略
- **L3 品牌认知层**（v1.0.1）：多租户品牌实例、产品版本、能力映射、证据链和图谱投影规范

第一层不是行业百科，也不是客户品牌知识库，而是：
- 统一知识对象定义
- 统一关系表达
- 统一意图分类
- 统一任务输出规范
- 统一证据规则

## 四层知识架构

| 层级 | 内容 | 位置 |
|------|------|------|
| **L1 通用知识层** | 本体、意图、任务模板、来源规则、质量规则、示例 | 本目录 |
| L2 行业/品类层 | 行业实体、市场主题、行业趋势、竞品公共信息 | industry_knowledge/ |
| **L3 品牌认知层** | 品牌产品、能力、定位、案例、内部文档 | brand_knowledge/ |
| L4 动态观测层 | 搜索回答、提及、引用、竞品变化、时序观测 | 仅定义观测对象 |

## 目录结构

```
Knowledge_Graph/
├── README.md
├── common_knowledge/              # L1 通用知识层
│   ├── ontology/                  # 21 实体 + 31 关系
│   ├── intents/                   # 13 意图 + 41 提问词模式
│   ├── sources/                   # 13 来源类型 + 20 质量规则
│   ├── tasks/                     # 9 任务模板 (+4 v1.1.0)
│   ├── policies/                  # 6 策略文件 (+3 v1.1.0)
│   └── examples/                  # 51 组正反例
├── industry_knowledge/            # L2 行业知识层
│   ├── README.md                  # L2 技术文档 (1916 行)
│   ├── scopes/                    # 行业范围定义
│   ├── requirements/              # 研究需求文件
│   ├── schemas/                   # 8 个 JSON Schema
│   ├── taxonomies/                # 能力/决策因素/主题模板
│   ├── pipelines/                 # 6 个数据处理流水线
│   ├── policies/                  # 3 个 L2 策略
│   └── examples/crm/              # CRM 试点示例
├── brand_knowledge/               # L3 品牌认知层
│   ├── README.md                  # L3 技术文档 (1069 行)
│   ├── INPUT_OUTPUT.md            # L2/L3 输入资料和输出数据简版说明
│   ├── scopes/                    # 品牌接入范围 + 多租户配置
│   ├── sources/                   # 品牌来源策略和权限
│   ├── domains/                   # 11 数据域 + 抽取 Profile
│   ├── ontology/                  # L3 实体/关系/assertion_kind
│   ├── schemas/                   # 9 个 JSON Schema
│   ├── pipelines/                 # 10 个品牌处理流水线
│   ├── policies/                  # 6 个 L3 策略
│   ├── database/                  # L3 迁移 SQL (11 表 + RLS)
│   ├── examples/                  # DeepCleer 试点数据
│   └── skills/                    # 12 个逻辑 Skills
└── database/                      # 数据库层
    ├── schema.sql                 # PostgreSQL 10 表（9 核心 + 1 辅助）
    ├── publish.py                 # YAML → DB 发布
    └── README.md
```

## 当前实现状态

| 能力 | 当前状态 |
|------|----------|
| L1 YAML/Schema/策略定义 | 已完成，可执行全项目校验 |
| L1 PostgreSQL 注册库 | 已有 Schema 和发布器，需外部 PostgreSQL 实例 |
| L2 行业数据处理 | 已有需求、Schema 和 Pipeline 契约；没有执行器和 L2 migration |
| L3 品牌数据处理 | 已有契约、样例和依赖 L2 表的 migration；没有 10 个 Pipeline 的执行器 |
| Neo4j 图谱投影 | 仅有设计与映射说明；没有投影服务、Cypher 初始化或一致性测试 |
| L4 动态观测 | 仅定义对象，未实现 |

因此，本仓库目前已经进入“图谱模型与数据契约设计”阶段，但还没有到“可生成并查询 Neo4j 图谱”的运行阶段。

## MVP 范围

### L1 通用知识层 v1.2.0

| 维度 | v1.0.0 | v1.1.0 | v1.2.0 | 变化 |
|------|--------|--------|--------|------|
| 实体类型 | 15 | 19 | 21 | +2 (organization, product_version) |
| 关系类型 | 20 | 27 | 31 | +4 (owns_brand, offers, version_of, supersedes) |
| 意图类型 | 13 | 13 | 13 | 不变 |
| 决策阶段 | 7 | 7 | 7 | 不变 |
| 来源类型 | 8 | 13 | 13 | 不变 |
| 任务模板 | 5 | 9 | 9 | 品牌导入支持多租户/产品版本/L2映射 |
| 策略文件 | 3 | 6 | 6 | 冲突新增4类，上下文新增硬过滤 |
| 质量规则 | 20 | 20 | 20 | 不变 |
| 正反例 | 50 | 50 | 51 | +1 正例 |

### L2 行业知识层 v1.0.0

| 维度 | 数量 |
|------|------|
| JSON Schema | 8 |
| 数据域 | 9 |
| Pipeline 定义 | 6 |
| L2 策略文件 | 3 |
| 分类模板 | 3 (capabilities, decision_factors, topics) |
| L2 技能定义 | 14 |
| L2 工具定义 | ~50 |

### L3 品牌认知层 v1.0.1

| 维度 | 数量 |
|------|------|
| 数据域 | 11 |
| Pipeline 定义 | 10 |
| L3 策略文件 | 6 |
| JSON Schema | 9 |
| 抽取 Profile | 7 |
| 逻辑 Skills | 12 |
| 信息来源类型 | 9 |
| 数据库迁移表 | 11 + RLS |

## 版本规范

使用语义化版本（Semantic Versioning）：

- **主版本（MAJOR）**：实体或关系发生不兼容变化
- **次版本（MINOR）**：新增类型、意图或任务模板
- **修订版本（PATCH）**：文字、示例和描述修正

## 维护频率

| 内容 | 频率 |
|------|------|
| 实体和关系定义 | 每月或按需求评审 |
| 意图分类 | 每季度评审 |
| 任务模板 | 出现失败案例后更新 |
| 来源等级 | 每季度复核 |
| 规则策略 | 每月复盘 |
| 正反例 | 持续增加 |
| 外部标准 | 有版本更新时评估 |

## 变更流程

```
发现新规范或问题
  → 创建变更提案
  → 评估是否影响现有任务
  → 更新定义/规则/模板
  → 运行回归样例
  → 小范围灰度
  → 发布新版本
  → 记录变更说明
```

## 核心原则

- **稳定规则结构化**：规则和模板以结构化 YAML 定义，版本化管理
- **方法知识文档化**：所有方法、流程和判断标准在文档中明确
- **案例和反例样例化**：每个任务有正反例示范
- **品牌事实不进入第一层**：L1 只包含通用规则，具体数据在 L2-L4
- **所有定义必须有版本、来源和变更记录**

## 参考标准

- [Schema.org](https://schema.org/)
- [W3C SKOS](https://www.w3.org/TR/skos-reference/)
- [Wikidata](https://www.wikidata.org/)
- [Google Search Central](https://developers.google.com/search/docs)
- [GEO: Generative Engine Optimization](https://arxiv.org/abs/2311.09735)
- [Graph RAG](https://arxiv.org/abs/2404.16130)

## 关联项目

- `d:\Brand Atlas\geo-research` — GEO 研究采集模块
