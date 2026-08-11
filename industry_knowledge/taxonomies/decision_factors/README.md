# Purchase Decision Factor Taxonomy

> **Purpose**: Cross-brand decision factor taxonomy for an industry.
> **Version**: 1.0.0
> **Status**: Active
> **Created**: 2026-08-11

## Overview

This directory holds the decision factor taxonomy for an industry. A decision factor is a criterion that buyers use to evaluate and compare products or vendors when making a purchase decision -- for example, "implementation time," "total cost of ownership," or "data security compliance."

The decision factor taxonomy is a shared coordinate system that powers:
- **Prompt mining**: Generating comparison and evaluation prompts from `Audience -> DecisionFactor` paths.
- **Content briefs**: Ensuring articles address the decision factors that matter to target audiences.
- **Competitive analysis**: Enabling cross-brand comparison on standardized dimensions.
- **L3 brand mapping**: Allowing individual brands to position themselves against L2 decision factors.

## Relationship to L1 Ontology

As of L1 1.0.0, the `decision_factor` entity type does not exist in the ontology. The MVP-compatible approach (per L2 Spec Section 6.6) is:

- **Store decision factors as `type: topic` with `semantic_subtype: decision_factor`**.
- All readers must filter by `semantic_subtype: decision_factor` to distinguish decision factors from ordinary topics.
- The L1 1.1.0 upgrade is expected to add `decision_factor` as a first-class entity type.

Until L1 1.1.0 is released, **do not create unregistered entity types**.

## File Naming Convention

Place decision factor taxonomy files in this directory using the pattern:

```
industry_knowledge/taxonomies/decision_factors/{category_id}_decision_factors.yaml
```

Example: `cat_crm_decision_factors.yaml` for CRM decision factors.

## Field Definitions

Each decision factor entry uses the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Unique identifier, e.g. `df_implementation_time` |
| `type` | string | Yes | Entity type. Always `topic` until L1 1.1.0 |
| `semantic_subtype` | string | Yes | Always `decision_factor` to distinguish from topics |
| `canonical_name` | string | Yes | Primary display name in the target language, e.g. `实施周期` |
| `aliases` | list | No | Alternative names and common synonyms |
| `definition` | string | Yes | Clear, concise definition of what this decision factor measures |
| `applicable_category_ids` | list | Yes | Category IDs this factor applies to |
| `related_audience_ids` | list | No | Audience IDs for whom this factor is most relevant |
| `evaluation_method` | list | No | Common ways this factor is evaluated by buyers |
| `importance` | string | No | Known importance level: `critical`, `high`, `medium`, `low`, `unknown` |
| `importance_by_audience` | map | No | Importance level keyed by audience_id, for audience-specific weighting |
| `tradeoff_with` | list | No | IDs of decision factors that commonly trade off against this one |
| `source_refs` | list | Yes | Evidence sources supporting this decision factor |
| `valid_from` | string | No | ISO date when this entry became valid |
| `valid_to` | string | No | ISO date when this entry expires |
| `version` | string | Yes | Semantic version of this entry |
| `status` | string | Yes | One of: `active`, `inactive`, `deprecated`, `superseded` |

## Example Entry

The following is a single decision factor entry for "implementation time" in CRM:

```yaml
id: df_implementation_time
type: topic
semantic_subtype: decision_factor
canonical_name: 实施周期
aliases:
  - 部署时间
  - 上线周期
  - 实施时长
  - implementation duration
  - deployment time
definition: >
  从采购合同确认到主要用户群体可以正常使用 CRM 系统所需的总时间，
  包括系统部署、数据迁移、集成配置、用户培训和试运行阶段。
  通常以周或月为单位衡量。
applicable_category_ids:
  - cat_crm
related_audience_ids:
  - aud_smb_sales_manager
  - aud_enterprise_sales_director
  - aud_it_procurement_decision_maker
evaluation_method:
  - 平均项目周期: 行业内同类规模和复杂度的项目平均实施时间
  - 数据迁移复杂度: 从现有系统迁移历史数据所需的预估时间和风险
  - 培训时间: 管理员和终端用户达到熟练操作所需的培训时长
  - 试运行周期: 从系统部署到正式切换的并行运行时间
  - 供应商实施能力: 供应商是否有成熟的实施方法论和本地化实施团队
importance: unknown
importance_by_audience:
  aud_smb_sales_manager: high
  aud_enterprise_sales_director: medium
  aud_it_procurement_decision_maker: high
tradeoff_with:
  - df_customization_depth
  - df_total_cost_of_ownership
source_refs:
  - src_crm_buyer_guide_001
  - src_industry_survey_002
version: 1.0.0
status: active
valid_from: 2026-08-11
```

## Common Decision Factor Categories

Decision factors typically cluster into the following categories. Each category may contain multiple specific factors:

| Category | Example Factors |
|---|---|
| **Cost** | total cost of ownership, license pricing, implementation cost, maintenance cost |
| **Functionality** | feature completeness, industry fit, customization depth, scalability |
| **Usability** | ease of use, learning curve, mobile experience, UI/UX quality |
| **Deployment** | implementation time, deployment model (cloud/on-premise/hybrid), data migration |
| **Integration** | API availability, ecosystem integration, third-party connectors, data import/export |
| **Security & Compliance** | data security certification, privacy compliance, data residency, access control |
| **Service & Support** | local support availability, SLA terms, training services, community and documentation |
| **Vendor** | vendor stability, market reputation, local presence, financial health |
| **Industry Fit** | industry-specific features, vertical solutions, industry best practices |

## How to Populate

Decision factor taxonomies are populated from geo-research industry reports. The process:

1. **Start from the report**: The geo-research report section "Purchase Decision Factors" (Section 7 of the report contract) contains the initial decision factor inventory with `[S#]` citations.

2. **Extract candidates**: The `industry_knowledge_extraction` skill parses the report using the decision factor extraction profile, which constrains extracted entities to `decision_factor` and relations to `has_decision_factor`.

3. **Resolve evidence**: The `citation_evidence_resolution` skill maps each `[S#]` to the original source and evidence text.

4. **Normalize**: Merge equivalent factors from different sources. For example, "实施周期" and "部署时间" may refer to the same factor. Resolve to a single canonical name.

5. **Assign importance**: Where source evidence supports it, assign `importance` levels. If multiple sources disagree or no source provides ranking, use `unknown`.

6. **Link to audiences**: Map each factor to the audiences that care about it, using the `has_decision_factor` relation from the audience domain.

7. **Review**: Importance assignments and new factors go through the `review_queue` for human validation.

8. **Write**: Use the `knowledge_upsert` skill to version and persist each decision factor entry.

## Quality Requirements

- Every decision factor must have a `definition` that is clear and measurable.
- Every decision factor must have at least one `source_refs` entry.
- `evaluation_method` entries must be specific and actionable, not generic.
- `importance` must be supported by evidence (survey data, buyer research) or explicitly marked as `unknown`.
- Avoid duplicating factors under different names. Run the entity resolution pipeline before writing.
- Conflicting importance ratings from different sources must be preserved as `disputed` and flagged for review.

## Changelog

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-08-11 | Initial template with field definitions, example entry, and population instructions |