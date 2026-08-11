# Industry Capability Dictionary

> **Purpose**: Standard capability dictionary for an industry.
> **Version**: 1.0.0
> **Status**: Active
> **Created**: 2026-08-11

## Overview

This directory holds the standard capability dictionary for an industry. A capability describes what a product can do -- for example, "sales forecasting" or "omnichannel lead management." It is distinct from a use case, which describes the context in which a user employs the product.

The capability dictionary is a shared coordinate system. L3 (Brand Knowledge Layer) maps individual brand products to L2 capabilities, enabling consistent cross-brand comparison and gap analysis.

## Relationship to L1 Ontology

As of L1 1.0.0, the `capability` entity type does not exist in the ontology. The MVP-compatible approach (per L2 Spec Section 5.3) is:

- **Store capabilities as `type: use_case` with `semantic_subtype: capability`**.
- All readers must filter by `semantic_subtype: capability` to distinguish capabilities from ordinary use cases.
- The L1 1.1.0 upgrade is expected to add `capability` as a first-class entity type.

Until L1 1.1.0 is released, **do not create unregistered entity types**.

## File Naming Convention

Place capability dictionary files in this directory using the pattern:

```
industry_knowledge/taxonomies/capabilities/{category_id}_capabilities.yaml
```

Example: `cat_crm_capabilities.yaml` for CRM capabilities.

## Field Definitions

Each capability entry uses the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Unique identifier, e.g. `cap_sales_forecasting` |
| `type` | string | Yes | Entity type. Always `use_case` until L1 1.1.0 |
| `semantic_subtype` | string | Yes | Always `capability` to distinguish from use cases |
| `canonical_name` | string | Yes | Primary display name in the target language, e.g. `销售预测` |
| `aliases` | list | No | Alternative names and common synonyms |
| `definition` | string | Yes | Clear, concise definition of what the capability is |
| `parent_capability_id` | string | No | ID of the parent capability in the hierarchy, for tree structure |
| `child_capability_ids` | list | No | IDs of child capabilities |
| `supported_use_case_ids` | list | No | IDs of use cases this capability supports |
| `related_problem_ids` | list | No | IDs of problems this capability addresses |
| `evaluation_dimensions` | list | No | Criteria by which this capability is evaluated |
| `category_ids` | list | No | Category IDs this capability applies to |
| `source_refs` | list | Yes | Evidence sources supporting this capability definition |
| `valid_from` | string | No | ISO date when this capability entry became valid |
| `valid_to` | string | No | ISO date when this capability entry expires |
| `version` | string | Yes | Semantic version of this entry |
| `status` | string | Yes | One of: `active`, `inactive`, `deprecated`, `superseded` |

## Example Entry

The following is a single capability entry for "sales forecasting" in CRM:

```yaml
id: cap_sales_forecasting
type: use_case
semantic_subtype: capability
canonical_name: 销售预测
aliases:
  - 销售预估
  - 业绩预测
  - sales forecast
definition: >
  基于历史销售数据、当前销售管道状态和市场趋势，
  运用统计模型或机器学习方法预测未来特定时间段的销售结果，
  包括收入金额、成交量、赢单率等关键指标。
parent_capability_id: cap_sales_analytics
child_capability_ids: []
supported_use_case_ids:
  - uc_quarter_sales_forecast
  - uc_annual_revenue_planning
related_problem_ids:
  - prob_sales_visibility_low
  - prob_revenue_unpredictable
evaluation_dimensions:
  - 数据输入范围: 支持的历史数据源、CRM 管道数据、外部市场数据
  - 预测粒度: 日/周/月/季度颗粒度，团队/个人/产品线维度
  - 模型类型: 统计模型、机器学习模型、混合模型
  - 可解释性: 预测结果的归因分析和影响因素可视化
  - 准确率: 在特定行业和规模下的预测偏差
  - 实时性: 是否支持实时更新和滚动预测
category_ids:
  - cat_crm
source_refs:
  - src_crm_capability_report_001
version: 1.0.0
status: active
valid_from: 2026-08-11
```

## Capability Hierarchy

Capabilities should be organized in a tree structure using `parent_capability_id` and `child_capability_ids`. The root level typically includes:

- **Core CRM capabilities**: sales management, customer management, marketing automation, service management
- **Analytics capabilities**: reporting, forecasting, AI-driven insights
- **Platform capabilities**: integration, customization, security, mobile

Each parent capability groups related child capabilities. For example:

```
cap_sales_analytics (parent)
  ├── cap_sales_forecasting
  ├── cap_sales_performance_analysis
  └── cap_pipeline_analytics
```

## How to Populate

Capability dictionaries are populated from geo-research industry reports. The process:

1. **Start from the report**: The geo-research report section "Standard Capabilities and Solution Structure" (Section 6 of the report contract, Section 4.4 of L2 spec) contains the initial capability inventory.

2. **Extract capability candidates**: The `industry_knowledge_extraction` skill parses the report and extracts capability candidates with their `[S#]` citations.

3. **Resolve evidence**: The `citation_evidence_resolution` skill maps each `[S#]` to the original source page and evidence text.

4. **Normalize**: Deduplicate capabilities across sources, resolve naming conflicts, and assign canonical names.

5. **Build hierarchy**: Establish parent-child relationships based on the capability structure described in reports.

6. **Validate**: Each capability must have a definition, at least one source reference, and a clear evaluation framework.

7. **Review**: New capabilities and hierarchy changes go through the `review_queue` for human validation.

8. **Write**: Use the `knowledge_upsert` skill to version and persist each capability entry.

## Quality Requirements

- Every capability must have a `definition` that is clear and testable.
- Every capability must have at least one `source_refs` entry.
- `evaluation_dimensions` must be specific to the capability, not generic.
- Capability hierarchy must be acyclic.
- Capability names must be distinct within the same category.
- Changes to the capability hierarchy require human review.

## Changelog

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-08-11 | Initial template with field definitions, example entry, and population instructions |