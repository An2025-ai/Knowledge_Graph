# Brand Atlas Knowledge Graph — 第一层通用知识层

> **版本**: 1.0.0  
> **状态**: Active  
> **创建日期**: 2026-08-07  

## 概述

本目录包含 Brand Atlas 知识图谱的**第一层通用知识层（L1 Common Knowledge Layer）**，
是跨品牌、跨行业复用的"方法与规范层"。它定义了系统使用的共同语言和操作方式。

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
| L2 行业/品类层 | 行业实体、市场主题、行业趋势、竞品公共信息 | 仅定义接入规范 |
| L3 品牌认知层 | 品牌产品、能力、定位、案例、内部文档 | 仅定义引用接口 |
| L4 动态观测层 | 搜索回答、提及、引用、竞品变化、时序观测 | 仅定义观测对象 |

## 目录结构

```
common_knowledge/
├── ontology/                    # 本体定义
│   ├── entities.yaml           # 15 种实体类型定义
│   └── relations.yaml          # 20 种关系类型定义
├── intents/                    # 意图定义
│   ├── intent_types.yaml       # 13 种意图 + 7 个决策阶段
│   └── prompt_patterns.yaml    # 提问词模式库
├── sources/                    # 来源规范
│   ├── source_types.yaml       # 8 种来源类型
│   └── authority_rules.yaml    # 20 条权威与质量规则
├── tasks/                      # 任务模板
│   ├── brand_onboarding.yaml   # 品牌导入
│   ├── prompt_generation.yaml  # 提问词生成
│   ├── topic_planning.yaml     # 主题规划
│   ├── search_diagnosis.yaml   # 搜索诊断
│   └── content_brief.yaml      # 内容 Brief
├── policies/                   # 策略规则
│   ├── claim_policy.yaml       # 事实与主张策略
│   ├── conflict_policy.yaml    # 冲突处理策略
│   └── context_policy.yaml     # 上下文检索策略
└── examples/                   # 示例
    ├── positive_examples.yaml  # 正确示例
    └── negative_examples.yaml  # 错误示例
```

## MVP 范围

| 维度 | 目标 | 实际 |
|------|------|------|
| 实体类型 | ≤15 | 15 |
| 关系类型 | ≤20 | 20 |
| 意图类型 | 10~13 | 13 |
| 决策阶段 | 7 | 7 |
| 来源类型 | 8~10 | 8 |
| 任务模板 | 5 | 5 |
| 质量规则 | ≤20 | 20 |
| 正反例 | 每任务 ≥5 组 | 每任务 5 组 |

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