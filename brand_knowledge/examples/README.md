# L3 品牌认知层 — 示例数据

> **版本**: 1.0.0  
> **创建日期**: 2026-08-11

## 概述

本目录包含 L3 品牌认知层的示例数据。当前以 **DeepCleer（深澈智算）** 作为试点案例，用于验证 L3 模型的完整流程。

## ⚠️ 重要说明

**DeepCleer 仅用于验证模型，不属于固定本体。**

- DeepCleer 的品牌名、产品名、能力名不得写入通用 Pipeline 的字段定义。
- 接入第二个品牌时，DeepCleer 专有产品名和能力不会成为通用 Schema 字段。
- 通用模板（`../scopes/brand_scope.example.yaml` 等）使用 `tenant_example` / `brand_example` 占位符，不含 DeepCleer 数据。

## DeepCleer 试点文件

| 文件 | 对应 L3 规范章节 | 内容 |
|------|----------------|------|
| `deepcleer/source_manifest.yaml` | §14.1 | 资料清单和版本冲突 |
| `deepcleer/entity_sample.yaml` | §14.2 | 组织/品牌/产品实体样例 |
| `deepcleer/conflicts.yaml` | §14.4 | 冲突和限定项清单 |
| `deepcleer/assertion_sample.json` | §14.5 | 示例 Assertion |
| `deepcleer/missing_information.yaml` | §14.6 | 缺失信息（不补齐） |

## 下一步

- 阶段 1：完成 DeepCleer 单品牌闭环（接入需求 → 解析 → 实体归一 → 审核 → 快照）
- 阶段 2：接入第二个不同类型品牌，验证无 DeepCleer 硬编码
