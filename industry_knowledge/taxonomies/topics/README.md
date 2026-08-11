# Industry Topic Tree

> **Purpose**: Stable topic hierarchy for content strategy in an industry.
> **Version**: 1.0.0
> **Status**: Active
> **Created**: 2026-08-11

## Overview

This directory holds the topic tree for an industry. A topic tree is a stable, hierarchical organization of subjects that matter for content strategy in a given industry. Topics are the backbone of:
- **Content planning**: Identifying which subjects to cover and in what depth.
- **Prompt mining**: Generating questions from `Topic -> QuestionPattern -> Intent` paths.
- **Content briefs**: Ensuring each article maps to the right topic node with appropriate evidence.
- **Search diagnosis**: Understanding which topics are underserved or over-covered.

A topic differs from a decision factor or a use case. It is a content-organizing concept -- an area of interest that generates articles, questions, and reader engagement. Topics should have lasting organizational value; a one-time news event should not become a stable topic.

## Relationship to L1 Ontology

Topics are native L1 entities (`type: topic`). No workaround is needed. The L2 topic tree extends L1 topics with industry-specific fields:

- `parent_topic_id` establishes the tree hierarchy.
- `related_audience_ids`, `related_problem_ids`, `related_intent_codes` connect topics to the rest of the knowledge graph.
- `question_patterns` seed prompt generation.
- `evidence_requirements` and `freshness_requirement` drive content quality rules.

## File Naming Convention

Place topic tree files in this directory using the pattern:

```
industry_knowledge/taxonomies/topics/{category_id}_topics.yaml
```

Example: `cat_crm_topics.yaml` for CRM topic tree.

## Field Definitions

Each topic entry uses the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Unique identifier, e.g. `topic_crm_selection` |
| `type` | string | Yes | Entity type. Always `topic` |
| `canonical_name` | string | Yes | Primary display name in the target language, e.g. `CRM 选型` |
| `aliases` | list | No | Alternative names and common synonyms |
| `parent_topic_id` | string | No | ID of the parent topic. `null` for root topics |
| `child_topic_ids` | list | No | IDs of child topics, derived from parent relationships |
| `related_audience_ids` | list | No | Audience IDs interested in this topic |
| `related_problem_ids` | list | No | Problem IDs this topic addresses |
| `related_use_case_ids` | list | No | Use case IDs related to this topic |
| `related_intent_codes` | list | No | Intent codes associated with this topic, e.g. `intent_comparison` |
| `question_patterns` | list | No | Typical questions that belong to this topic, used for prompt generation |
| `evidence_requirements` | list | No | Types of evidence required for content under this topic |
| `freshness_requirement` | string | No | How often content should be refreshed: `daily`, `weekly`, `monthly`, `quarterly`, `annual` |
| `source_refs` | list | Yes | Evidence sources supporting this topic definition |
| `valid_from` | string | No | ISO date when this topic entry became valid |
| `valid_to` | string | No | ISO date when this topic entry expires |
| `version` | string | Yes | Semantic version of this entry |
| `status` | string | Yes | One of: `active`, `inactive`, `deprecated`, `superseded` |

## Example Entry

The following is a single topic entry for "CRM Selection" in CRM:

```yaml
id: topic_crm_selection
type: topic
canonical_name: CRM 选型
aliases:
  - CRM 选购
  - CRM 系统选择
  - CRM evaluation
  - CRM vendor selection
parent_topic_id: topic_crm
child_topic_ids: []
related_audience_ids:
  - aud_smb_sales_manager
  - aud_enterprise_sales_director
  - aud_it_procurement_decision_maker
related_problem_ids:
  - prob_leads_fragmented
  - prob_team_collaboration_low
  - prob_customer_data_siloed
related_use_case_ids:
  - uc_omnichannel_lead_management
  - uc_sales_performance_tracking
related_intent_codes:
  - intent_comparison
  - intent_recommendation
  - intent_pricing
  - intent_how_to
question_patterns:
  - 中小企业选择 CRM 应考虑什么？
  - 哪些 CRM 更适合{行业}企业？
  - CRM 的价格和功能如何权衡？
  - {年份}年中国市场 CRM 排名和对比？
  - 销售易和纷享销客哪个更适合{规模}企业？
evidence_requirements:
  - product_documentation
  - independent_review
  - pricing_data
  - customer_case_study
freshness_requirement: quarterly
source_refs:
  - src_crm_buyer_guide_001
  - src_industry_survey_002
version: 1.0.0
status: active
valid_from: 2026-08-11
```

## Topic Hierarchy Principles

The topic tree should follow these principles:

1. **Stability over novelty**: A topic should remain relevant for at least one quarter. Breaking news, one-time events, and short-lived trends should not become stable topics. They may be captured as `observation` or `event` entities.

2. **Depth limit**: Maximum depth of 4 levels. Beyond that, content becomes too granular to organize meaningfully.

3. **Mutual exclusivity at each level**: Child topics should not overlap in meaning. If two topics cover the same ground, merge them.

4. **Coverage completeness**: The topic tree should cover all major content areas for the industry. Gaps should be documented in the coverage ledger.

5. **Audience relevance**: Every topic should connect to at least one audience. Topics with no audience are content without readers.

### Example CRM Topic Hierarchy

```
topic_crm (CRM)
├── topic_crm_selection (CRM 选型)
│   ├── topic_crm_feature_comparison (CRM 功能对比)
│   ├── topic_crm_pricing_guide (CRM 价格指南)
│   └── topic_crm_deployment_model (CRM 部署方式选择)
├── topic_crm_implementation (CRM 实施)
│   ├── topic_crm_data_migration (数据迁移)
│   ├── topic_crm_user_training (用户培训)
│   └── topic_crm_integration (系统集成)
├── topic_crm_usage (CRM 使用)
│   ├── topic_crm_sales_management (销售管理)
│   ├── topic_crm_customer_analytics (客户分析)
│   └── topic_crm_workflow_automation (自动化工作流)
├── topic_crm_security_compliance (CRM 安全与合规)
└── topic_crm_trends (CRM 趋势)
    ├── topic_crm_ai_applications (AI 在 CRM 中的应用)
    └── topic_crm_mobile (移动 CRM)
```

## How to Populate

Topic trees are populated from geo-research industry reports and refined over time. The process:

1. **Start from the report**: The geo-research report section "Industry Topics and Typical Questions" (Section 8 of the report contract) contains the initial topic inventory with `[S#]` citations.

2. **Extract candidates**: The `industry_knowledge_extraction` skill parses the report using the topic extraction profile, which constrains extracted entities to `topic`.

3. **Resolve evidence**: The `citation_evidence_resolution` skill maps each `[S#]` to the original source and evidence text.

4. **Build hierarchy**: The `industry_topic_modeling` skill organizes topics into a tree using `parent_topic_id` relationships. The hierarchy should be validated against multiple source reports to ensure stability.

5. **Link to graph**: Connect topics to audiences (`related_audience_ids`), problems (`related_problem_ids`), use cases (`related_use_case_ids`), and intents (`related_intent_codes`).

6. **Generate question patterns**: `question_patterns` should be derived from the report's question space section and refined by the prompt mining pipeline. Use `{placeholder}` syntax for parameterized patterns.

7. **Assign freshness**: Based on the topic's nature -- pricing topics need `monthly`, trend topics need `quarterly`, definitional topics can be `annual`.

8. **Review**: New root topics, hierarchy restructuring, and major question pattern changes go through the `review_queue` for human validation.

9. **Write**: Use the `knowledge_upsert` skill to version and persist each topic entry.

## Quality Requirements

- Every topic must have at least one `source_refs` entry.
- `question_patterns` must be specific to the topic, not generic catch-all questions.
- The topic hierarchy must be acyclic. Validate with a topological sort.
- Root topics should be limited to 5-10 per industry.
- Maximum depth of 4 levels.
- `freshness_requirement` must be set for every topic. Default is `quarterly`.
- Changes to the topic tree structure (adding/removing/renaming nodes) require human review.
- Prompt instances should be generated by the downstream `prompt_generation` skill, not stored directly in the topic tree. `question_patterns` are templates, not exhaustive prompt lists.

## Changelog

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-08-11 | Initial template with field definitions, example entry, hierarchy principles, and population instructions |