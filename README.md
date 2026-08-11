# Brand Atlas Knowledge Graph

> **版本**: 1.1.0  
> **状态**: Active  
> **创建日期**: 2026-08-07  
> **更新日期**: 2026-08-11  

## 概述

Brand Atlas 知识图谱是一个多层知识工程系统，用于支持 GEO（生成式引擎优化）、
品牌市场认知分析、提问词生成、主题规划和内容优化。

当前实现了两层：
- **L1 通用知识层**（v1.1.0）：跨品牌、跨行业复用的方法与规范层
- **L2 行业知识层**（v1.0.0）：行业市场坐标系，定义数据域、Pipeline、Schema 和策略

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
| L3 品牌认知层 | 品牌产品、能力、定位、案例、内部文档 | 仅定义引用接口 |
| L4 动态观测层 | 搜索回答、提及、引用、竞品变化、时序观测 | 仅定义观测对象 |

## 目录结构

```
Knowledge_Graph/
├── README.md
├── common_knowledge/              # L1 通用知识层
│   ├── ontology/                  # 19 实体 + 27 关系
│   ├── intents/                   # 13 意图 + 39 提问词模式
│   ├── sources/                   # 13 来源类型 + 20 质量规则
│   ├── tasks/                     # 9 任务模板 (+4 v1.1.0)
│   ├── policies/                  # 6 策略文件 (+3 v1.1.0)
│   └── examples/                  # 50 组正反例
├── industry_knowledge/            # L2 行业知识层
│   ├── README.md                  # L2 技术文档 (1916 行)
│   ├── scopes/                    # 行业范围定义
│   ├── requirements/              # 研究需求文件
│   ├── schemas/                   # 8 个 JSON Schema
│   ├── taxonomies/                # 能力/决策因素/主题模板
│   ├── pipelines/                 # 6 个数据处理流水线
│   ├── policies/                  # 3 个 L2 策略
│   └── examples/crm/              # CRM 试点示例
└── database/                      # 数据库层
    ├── schema.sql                 # PostgreSQL 9 表
    ├── publish.py                 # YAML → DB 发布
    └── README.md
```

## MVP 范围

### L1 通用知识层 v1.1.0

| 维度 | v1.0.0 | v1.1.0 | 变化 |
|------|--------|--------|------|
| 实体类型 | 15 | 19 | +4 (capability, decision_factor, JTBD, outcome) |
| 关系类型 | 20 | 27 | +7 (has_problem, has_decision_factor, capability_supports_use_case 等) |
| 意图类型 | 13 | 13 | 不变 |
| 决策阶段 | 7 | 7 | 不变 |
| 来源类型 | 8 | 13 | +5 (standards_body, industry_association, brokerage_research 等) |
| 任务模板 | 5 | 9 | +4 (industry_knowledge_build, refresh, source_discovery, knowledge_promotion) |
| 策略文件 | 3 | 6 | +3 (source_discovery, knowledge_promotion, report_evidence) |
| 质量规则 | 20 | 20 | 不变 |
| 正反例 | 50 | 50 | 不变 |

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
