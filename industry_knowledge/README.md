# Brand Atlas Knowledge Graph — 第二层行业市场知识层搭建技术文档

> **版本**：1.0.0  
> **状态**：Design Complete / Implementation Pending  
> **创建日期**：2026-08-10  
> **上游依赖**：L1 Common Knowledge Layer 1.0.0、geo-research 第三方机构清单爬虫 Demo  
> **下游消费者**：L3 品牌认知层、提问词挖掘、主题规划、文章优化、内容 Brief、搜索诊断

## 1. 文档目的

本文定义 Brand Atlas 第二层行业市场知识层（L2 Industry & Market Knowledge Layer）的搭建方法，包括：

- L2 的范围、边界和与 L1/L3/L4 的关系
- L2 数据需求规范如何驱动 geo-research 生成完整行业报告
- 行业报告、引用清单和原始证据包的交付与增量导入流程
- 文档清洗、信息抽取、实体归一、事实验证和知识晋升
- 需要抽取的行业市场维度和字段
- PostgreSQL、对象存储、全文索引、向量索引和图谱投影的职责
- 数据在主题树、实体关系图和证据链中的排列方式
- Skills、Tools、任务编排和接口约定
- 质量门禁、版本、时效、权限、回滚和维护机制
- MVP 实施范围和验收标准

L2 的目标不是积累尽可能多的网页，而是建立可复用的行业坐标系：

~~~text
行业中有什么品类？
有哪些用户角色和问题？
用户在什么场景下寻找什么能力？
购买时关注哪些因素？
市场参与者和替代方案是谁？
行业围绕哪些主题和问题展开？
哪些结论有证据、何时有效、适用于什么范围？
~~~

本版本明确不采集社区网站和 UGC 平台。知乎、小红书、知识星球、B站、Reddit、G2、Product Hunt 等来源不进入 L2 采集、抽取和知识晋升流程。

## 2. 层级职责

### 2.1 L1、L2、L3、L4 分工

| 层级 | 核心职责 | 示例 |
|---|---|---|
| L1 通用知识层 | 定义对象、关系、意图、任务和证据规则 | 什么是 topic、fact、comparison |
| L2 行业市场层 | 实例化共享行业坐标系 | CRM 品类、销售负责人、线索管理 |
| L3 品牌认知层 | 将具体品牌映射到 L2 | 品牌 A 服务销售负责人并支持线索管理 |
| L4 动态观测层 | 保存搜索和 AI 回答的时序结果 | 某日 ChatGPT 在某问题中推荐品牌 B |

### 2.2 L2 应保存

- 行业、品类、子品类和解决方案类别
- 共享的用户角色、JTBD、问题和使用场景
- 行业标准能力和购买决策因素
- 行业主题、子主题、典型问题和意图关联
- 公开市场参与者及其行业角色
- 经过验证的行业事实、统计、趋势、政策和事件
- 行业来源生态和证据链
- 公开竞品关系及适用范围

### 2.3 L2 不应保存

- 客户内部文档和未公开信息
- 单个客户的目标定位、内容策略和合规边界
- 未经验证的单次搜索结果
- 某个品牌专属的私有产品能力
- 直接用于报告的汇总指标计算结果
- 没有来源的 LLM 推断
- 社区帖子、用户评论、问答平台内容及其摘要

单次联网结果默认进入观测暂存区；经过验证后，才可晋升为 L2 的 fact、claim 或稳定关系。

## 3. 总体架构

~~~text
L2 Industry Knowledge Requirement
定义行业报告必须回答的数据维度、字段、来源和证据要求
                         ↓
geo-research 根据需求生成查询计划和第三方机构覆盖清单
                         ↓
搜索发现 → Playwright 抓取 → 原始证据归档
                         ↓
生成完整行业报告 + 引用清单 + Evidence Package + Coverage Ledger
                         ↓
L2 Report Ingestor 解析报告章节、结论、表格和 [S#] 引用
                         ↓
Evidence Resolver 将每条候选知识回指已打开的原始证据
                         ↓
实体消歧、Fact/Claim 分类、关系校验、冲突检测、人工审核
                         ↓
PostgreSQL 规范知识与证据链
     ↙                 ↓                 ↘
全文索引             向量索引            图谱投影
     ↘                 ↓                 ↙
                  Context Builder
                         ↓
          L3 / 提问词挖掘 / 文章优化 / 诊断
~~~

核心原则：

1. 原始材料、结构化知识和派生结论分开保存。
2. 图谱中的边必须能追溯到证据。
3. 搜索结果不是事实，LLM 输出也不是事实。
4. 结构化过滤优先，语义检索作为补充。
5. 更新采用增量和版本化，不覆盖历史。
6. L2 数据默认共享，但来源许可和版权约束必须单独记录。
7. Knowledge_Graph 不重复爬取网页，主要抽取对象是 geo-research 生成的完整行业报告。
8. 行业报告是二次归纳产物，不是独立信源；任何入图结论必须回指原始证据。

## 4. geo-research 集成边界

### 4.1 系统职责

geo-research 负责：

- 接收 L2 输出的行业研究数据需求规范
- 维护第三方机构和公开来源清单
- 根据需求维度生成搜索计划并保存覆盖台账
- 使用 SearXNG 发现候选原始页面
- 使用 Playwright 打开允许访问的页面
- 执行 robots 和基本内容质量检查
- 保存 JSONL 记录、正文文件、URL、状态和内容 Hash
- 生成符合 L2 章节规范的完整行业报告
- 交付报告引用清单、Evidence Package 和 Coverage Ledger

Knowledge_Graph L2 负责：

- 定义行业报告需要调研和输出的数据维度
- 生成 Industry Knowledge Requirement，并提交给 geo-research
- 读取完整行业报告及其运行清单和证据包
- 从报告章节、表格和结论中抽取行业实体、关系、主题、事实和主张候选
- 将候选知识的 [S#] 引用解析到原始网页证据
- 实体消歧、证据绑定、冲突检测和人工审核
- 写入第二层 PostgreSQL、全文索引和向量索引
- 生成供 L3、提问词挖掘和文章优化使用的行业子图

Knowledge_Graph 不负责：

- 重新调用搜索引擎
- 绕过 robots、登录、验证码或付费墙
- 把搜索摘要作为证据
- 采集或导入社区网站数据
- 把行业报告的无引用总结直接写成 fact

### 4.2 Industry Knowledge Requirement

L2 在每次行业研究前生成机器可读的需求文件。该文件不是自然语言提示词，而是 geo-research 的任务合同。

~~~yaml
requirement_id: ikr_crm_cn_2026_v1
schema_version: 1.0.0
industry:
  industry_id: ind_enterprise_software
  category_ids: [cat_crm]
  market: CN
  languages: [zh-CN]
time_scope:
  preferred_from: 2025-01-01
  fallback_from: 2024-01-01
excluded_source_classes:
  - community
  - social_media
  - ugc_review
required_dimensions:
  - market_definition
  - category_structure
  - market_participants
  - audience_and_decision_chain
  - problems_and_jobs
  - use_cases
  - capabilities
  - decision_factors
  - topics_and_questions
  - market_facts_and_trends
  - regulation_and_risks
source_requirements:
  primary_mode: whitelist_first
  fallback_discovery:
    enabled: true
    trigger_on: [missing, partial, outdated, conflicting]
    require_original_url: true
    require_selection_reason: true
  allowed_source_classes:
    - government
    - regulator
    - industry_research
    - academic
    - brokerage_research
    - reliable_media
    - competitor_official
  critical_claim_min_independent_sources: 2
report_contract:
  format: markdown
  inline_citation_format: "[S#]"
  require_coverage_ledger: true
  require_evidence_package: true
  require_missing_data_section: true
~~~

需求文件必须版本化。需求字段变化后重新生成报告时，应记录 requirement_id 和 schema_version，避免不同口径的报告被当成同一批数据。

### 4.3 行业报告必须覆盖的数据清单

L2 应先告诉 geo-research 需要下列数据，而不是让爬虫自由决定报告内容。

| 数据维度 | 必需信息 | 建议证据 |
|---|---|---|
| 行业和品类定义 | 定义、边界、别名、父子品类、相邻品类 | 标准、协会、研究机构 |
| 市场范围 | 地区、时间、统计口径、价值链位置 | 政府、报告方法页 |
| 市场参与者 | 品牌、产品、机构、市场角色、适用品类 | 研究报告、公司原始资料 |
| 用户角色 | 组织类型、规模、业务角色、决策角色 | 有样本的用户调查 |
| 用户问题 | 痛点、发生条件、受影响角色、严重性依据 | 调查、可靠媒体调查 |
| JTBD 与使用场景 | 用户任务、触发条件、期望结果 | 调查、行业研究、案例 |
| 标准能力 | 能力定义、父子能力、支持场景、评价维度 | 标准、技术资料、行业报告 |
| 决策因素 | 价格、部署、集成、安全、合规、服务等 | 采购研究、调查、选型报告 |
| 行业主题 | 主题层级、关联问题、意图、时效要求 | 多来源内容归纳 |
| 市场事实 | 数值、单位、地区、年份、样本、方法 | 政府、原始研究报告 |
| 趋势与预测 | 趋势方向、驱动因素、预测主体和假设 | 多来源研究、券商报告 |
| 政策与风险 | 法规、标准、实施时间、适用主体、风险 | 政府、监管、标准组织 |
| 竞争结构 | 直接竞品、替代方案、竞争范围和比较维度 | 行业报告、竞品原始资料 |
| 来源生态 | 权威机构、常见引用来源、覆盖主题 | 来源清单和引用统计 |
| 证据缺口 | 未找到、受阻、冲突和无法验证的信息 | Coverage Ledger |

每个维度在报告中必须明确：

~~~text
结论或数据
适用对象
地区
时间
统计/研究口径
原始 [S#] 引用
可信度或限制
是否存在冲突
~~~

### 4.4 报告章节合同

geo-research 输出的完整行业报告应采用稳定章节，以便 L2 解析：

~~~text
1. 研究范围与方法
2. 行业和品类定义
3. 市场结构与参与者
4. 用户角色与决策链
5. 用户问题、JTBD 与使用场景
6. 产品标准能力与解决方案结构
7. 购买决策因素
8. 行业主题与典型问题
9. 市场事实、规模和趋势
10. 政策、风险与限制
11. 竞争格局和替代方案
12. 冲突证据与待核验项
13. 缺失数据和研究局限
14. 搜索覆盖清单
15. 完整信源清单
~~~

报告中的事实、数字、比较和趋势必须紧跟 [S#]。无引用段落只能作为报告叙述，不能产生稳定知识。

报告数量策略：

- 普通行业首次创建：一份 baseline 主报告。
- 范围过大：一份总报告加 market、audience、capability、competition、policy 等模块报告。
- 缺失维度补充：incremental 报告。
- 定期更新：refresh 变更报告，不重复生成全部历史内容。
- 冲突修正：correction 专项报告。

所有模块必须共享 industry_id、snapshot_id 和 requirement_id，不能形成互相独立的行业知识库。所有准备进入 L2 的报告都必须先解析成统一 Structured Report。

### 4.5 上游交付文件

默认上游根目录：

~~~text
D:\Brand Atlas\geo-research
~~~

L2 的主要抽取输入：

~~~text
reports/generated/<industry-report>.md
或 reports/latest-search-report.md
~~~

报告必须同时提供：

~~~text
data/runs/<run_id>/run.json
data/runs/<run_id>/plan.json
data/runs/<run_id>/evidence.json
搜索覆盖清单
完整信源清单
~~~

以下文件只用于证据核验和血缘，不是首要抽取对象：

~~~text
data/market/browser-items.jsonl
data/products/browser-items.jsonl
data/academic/browser-items.jsonl
data/<dataset>/pages/*.txt
~~~

L2 不得使用：

~~~text
data/<dataset>/search-items.jsonl
搜索结果摘要
reports/*.md 中没有原始页面回指的模型归纳
data/user-voice/*
~~~

search-items.jsonl 仅可用于 geo-research 内部的候选发现和覆盖审计。

### 4.6 第三方机构白名单

现有 sources.json 的 category 不能准确区分媒体和社区。实施前应增加 source_class：

~~~json
{
  "name": "CAICT White Papers",
  "category": "domestic_industry",
  "source_class": "industry_research",
  "type": "page",
  "url": "https://www.caict.ac.cn/kxyj/qwfb/bps/",
  "enabled": true,
  "l2_enabled": true
}
~~~

允许进入 L2 的 source_class：

~~~text
government
regulator
standards_body
industry_association
industry_research
academic
brokerage_research
reliable_media
competitor_official
company_disclosure
~~~

仅用于发现原始来源：

~~~text
aggregator
search_engine
~~~

禁止进入 L2：

~~~text
community
social_media
ugc_review
forum
creator_platform
~~~

域名黑名单至少包括：

~~~text
zhihu.com
xiaohongshu.com
wx.zsxq.com
bilibili.com
reddit.com
g2.com
producthunt.com
~~~

过滤顺序必须是 source_class 白名单、l2_enabled、域名黑名单、抓取状态，而不能仅根据 dataset 名称过滤。央广网、21财经、经济日报、中国青年报、央视等虽然现有配置可能位于 user 类 category，但属于可靠媒体，可在补充 source_class 后进入 L2。

现有清单建议映射：

| 来源组 | 代表来源 | L2 用途 |
|---|---|---|
| 政府和公共机构 | 国家统计局、CNNIC、中国信通院 | 宏观、用户规模、政策和行业基础事实 |
| 行业研究 | 艾瑞、爱分析、头豹、QuestMobile、极光、CBNData、腾讯研究院、阿里研究院 | 市场、用户、品类、趋势和决策因素 |
| 可靠媒体 | 央广网、21财经、经济日报、中国青年报、央视、36氪、虎嗅、Morketing、梅花网 | 事件、公司动态、市场观点和问题线索 |
| 券商研究 | 中信、中金、华泰、申万宏源 | 长期趋势和预测；必须标记为研究判断 |
| 学术 | arXiv、ACL、知网、万方等可访问原文 | 概念、机制、方法和研究结论 |
| 聚合发现 | 199IT、东方财富研报检索 | 只发现原报告，优先追溯原发布机构 |

同一机构不是在所有主题上都具有同等权威性。source_class 负责准入，具体陈述仍要根据研究方法、时间、范围和证据内容判断。

#### 白名单缺口扩展

首次建库仍以用户提供的第三方机构清单为首选，但某个必需维度出现 missing、partial、outdated 或 conflicting 时，geo-research 可以自主发现其他高质量机构。

~~~text
白名单搜索
→ 维度覆盖检查
→ 触发扩展来源发现
→ 机构身份和方法核验
→ 抓取原始发布页
→ 记录选择理由和局限
→ 纳入报告证据集
~~~

扩展来源至少记录：

~~~yaml
source_id:
organization:
official_domain:
source_class:
discovered_by: geo-research
discovery_query:
discovery_reason:
identity_verified:
original_publisher:
methodology_available:
independence_level:
allowed_uses: []
limitations: []
original_url:
published_at:
approval_status:
~~~

来源状态：

~~~text
discovered → candidate → verified → active
                         → rejected
active → suspended / deprecated
~~~

高质量非关键材料可以在自动核验通过后进入报告，并完整注明来源。市场规模、份额、监管、安全、效果和排名等关键结论，需要政府/监管原始来源或至少两个独立高质量来源交叉验证。扩展来源不能绕过社区黑名单和原始证据要求。

不采集社区后的用户需求口径：

- 用户问题、痛点和决策因素主要来自有样本和方法说明的行业调查、研究报告、可靠媒体调查及公开客户研究。
- 机构报告中的受访者原话应记录为“报告引用的用户表达”，不能标记为平台直接采集的用户评论。
- 厂商客户案例只能证明厂商公开陈述及案例内容，不能代表行业总体需求。
- 没有抽样方法、样本范围或原始证据的问题判断，应保存为 claim 或待验证候选。
- 因不采集社区，L2 不声称覆盖自然发生的 UGC 讨论；该限制必须进入 knowledge coverage 和下游 Context Package 的 missing_information。

### 4.7 报告和证据契约

报告候选知识的最小解析结果：

~~~json
{
  "report_id": "report_crm_cn_2026",
  "requirement_id": "ikr_crm_cn_2026_v1",
  "section": "购买决策因素",
  "statement": "中小企业在选择CRM时关注实施周期和数据安全",
  "knowledge_candidate_type": "claim",
  "subject_candidates": ["中小企业", "CRM"],
  "relation_candidates": [],
  "citation_labels": ["S3", "S8"],
  "report_span": {
    "start_line": 120,
    "end_line": 123
  }
}
~~~

Evidence Resolver 将 S3、S8 映射为：

~~~json
{
  "citation_label": "S3",
  "source_record_id": "source_003",
  "original_url": "https://example.com/report",
  "access_status": "crawled",
  "source_class": "industry_research",
  "content_sha256": "sha256...",
  "evidence_text": "原始页面中的直接支持文本",
  "evidence_location": {
    "content_path": "data/market/pages/source_003.txt",
    "start_offset": 1024,
    "end_offset": 1180
  }
}
~~~

只有 evidence_text 直接支持 statement 时，候选知识才通过证据一致性检查。

现有 browser-items.jsonl 可作为证据定位记录，其字段包括：

geo-research 当前 browser-items.jsonl 记录包含：

~~~json
{
  "id": "f5bcaa00c1e2c74f",
  "source": "MobTech Research",
  "dataset": "market",
  "category": "domestic_industry",
  "title": "页面标题",
  "url": "https://example.com/report",
  "requested_url": "https://example.com/report",
  "final_url": "https://example.com/report",
  "http_status": 200,
  "published_at": null,
  "collected_at": "2026-08-07T02:51:02Z",
  "collector": "playwright",
  "status": "ok",
  "requires_login": false,
  "summary": "正文摘要或截断文本",
  "content_sha256": "70fcc6...",
  "content_path": "data\\market\\pages\\f5bcaa00c1e2c74f.txt"
}
~~~

建议上游后续补充：

~~~text
source_class, l2_enabled, run_id, canonical_url,
robots_result, content_type, parser_version,
license_or_usage_note, publication_author
~~~

L2 Import Adapter 必须兼容当前字段，并允许新增字段向前兼容。

### 4.8 报告知识导入门禁

一条从行业报告抽取的候选知识只有满足以下条件才进入审核或稳定知识队列：

1. 来自已登记 requirement_id 对应的完整行业报告。
2. 报告段落属于已注册数据维度。
3. 至少包含一个可解析的 [S#]。
4. [S#] 能映射到 Evidence Package 中的原始 URL。
5. 来源在允许白名单，且不在域名黑名单。
6. access_status 为 crawled/ok，不是 search-snippet 或 robots-blocked。
7. 原始正文存在，Hash 校验通过。
8. evidence_text 与报告陈述直接一致，不只是主题相似。
9. 类型、关系、地区、时间和适用范围符合 L1/L2 Schema。
10. 记录未被同一 report_id、report_span 和 evidence_hash 成功导入。

没有引用、引用失效、引用只指向搜索摘要或证据不支持结论时：

- 不得写入 fact。
- 保存为 rejected_candidate 或 unverified_candidate。
- 在行业知识覆盖缺口中记录原因。
- 高价值缺口可生成新的 geo-research 补充研究需求。

### 4.9 幂等和血缘

L2 为每次导入保存：

~~~yaml
external_system: geo-research
requirement_id: ikr_crm_cn_2026_v1
report_id: report_crm_cn_2026
report_path: reports/generated/crm-industry-report.md
report_section: 购买决策因素
report_span: 120-123
external_record_id: f5bcaa00c1e2c74f
external_dataset: market
external_content_path: data/market/pages/f5bcaa00c1e2c74f.txt
external_content_sha256: 70fcc6...
external_collected_at: 2026-08-07T02:51:02Z
import_run_id: l2-import-20260810-001
import_status: accepted
~~~

报告知识候选的幂等键：

~~~text
report_id + report_span + normalized_statement_hash + evidence_hash
~~~

同一 requirement_id 的新报告视为新研究版本。相同结论和证据只合并来源；结论或证据发生变化时创建新版本，不覆盖旧知识。

### 4.10 当前 geo-research Demo 就绪度

当前 Demo 已具备搜索计划、网页打开、正文归档、报告生成、[S#] 引用和运行审计的基础能力，但现有样例报告不能直接作为 L2 生产输入，原因包括：

- 完整信源清单中仍包含 robots-blocked 和 search-snippet。
- 部分报告结论引用聚合页、内容平台或非白名单来源。
- 个别市场数字和排行榜缺少可复核的方法、样本或原始发布机构。
- 当前报告章节与 L2 数据维度尚未完全固定映射。

接入 L2 前必须完成：

1. sources.json 增加 source_class 和 l2_enabled。
2. 报告生成器只允许使用 crawled/ok 且白名单来源作为有效证据。
3. 报告正文禁止引用 search-snippet、blocked、社区和 UGC 来源。
4. 报告按 4.4 的章节合同生成。
5. 输出 requirement_id、run_id、Evidence Package 和 Coverage Ledger。
6. 无法验证的数据进入“缺失数据/待核验”，不得由模型补齐。

## 5. 与 L1 的兼容性

L2 必须使用 L1 已注册的实体和关系代码。

### 5.1 当前可直接使用的 L1 实体

~~~text
brand, product, industry, category, audience,
use_case, problem, topic, prompt, competitor,
content, source, fact, claim, observation
~~~

### 5.2 当前可直接使用的核心关系

~~~text
belongs_to, operates_in, serves, supports_use_case, solves,
has_capability, competes_with, alternative_to, partner_of,
has_topic, covers, targets, expresses_intent, mentions,
cites, supports, contradicts, derived_from, recommended_for,
has_content_gap
~~~

### 5.3 已识别的本体缺口

L1 1.0.0 中，has_capability 的客体类型为 use_case。能力与使用场景语义不同：

~~~text
能力：产品能做什么，例如销售预测
使用场景：用户在何种情境下使用，例如预测季度销售额
~~~

MVP 兼容方案：

- 暂时将能力保存为 use_case，并增加 semantic_subtype: capability。
- 所有读取端必须按 semantic_subtype 区分 capability 与普通 use_case。

推荐正式方案：

- 在 L1 1.1.0 增加 capability 实体类型。
- 为保持兼容，先将 has_capability 的 object_types 扩展为 [use_case, capability]，新数据只允许 capability。
- 在 L1 2.0.0 再移除 has_capability 对 use_case 的兼容。
- 使用 supports_use_case 表达 product → use_case。
- 使用 capability_supports_use_case 或通用关联关系表达 capability → use_case。

在 L1 变更完成前，L2 不得自行创造未注册实体类型。

### 5.4 L1 需要修改吗

需要升级到 L1 1.1.0，但属于增量扩展，不需要推翻现有设计。

必须增加的实体：

| 实体 | 原因 |
|---|---|
| capability | 区分“产品能做什么”和“用户如何使用” |
| decision_factor | 作为提问词挖掘、选型比较和文章优化的核心坐标 |

建议增加的实体：

| 实体 | 原因 |
|---|---|
| job_to_be_done | 区分用户任务与具体使用场景 |
| outcome | 表达用户希望取得的业务结果 |

必须增加或扩展的关系：

~~~text
audience -[HAS_PROBLEM]-> problem
audience -[HAS_DECISION_FACTOR]-> decision_factor
category -[HAS_DECISION_FACTOR]-> decision_factor
capability -[SUPPORTS_USE_CASE]-> use_case
use_case -[REQUIRES_CAPABILITY]-> capability
audience -[PERFORMS]-> job_to_be_done             # 若增加JTBD
use_case -[PRODUCES_OUTCOME]-> outcome             # 若增加Outcome
~~~

必须扩展的来源类型：

~~~text
standards_body
industry_association
brokerage_research
company_disclosure
aggregator
~~~

保留现有 media 类型以兼容，并增加 source_subtype: reliable_media。aggregator 只能用于发现原始来源。

必须增加的通用任务：

~~~text
industry_knowledge_build
industry_knowledge_refresh
source_discovery
knowledge_promotion
~~~

必须增加的策略：

~~~text
source_discovery_policy
knowledge_promotion_policy
report_evidence_policy
~~~

需要修正的一致性问题：

- claim_policy 已定义 inference，但实体注册表没有 inference。推荐把 fact、claim、observation、inference 统一建模为 statement_class，而不是新增四类图谱业务节点。
- Evidence、Assertion、ResearchReport 属于知识血缘和存储模型，不必全部加入 L1 业务本体，可在 L2 数据库 Schema 中注册。
- context_policy 增加 industry_id、snapshot_id、requirement_id、market、valid_at 和 verification_status 过滤维度。

L1 1.1.0 采用添加类型和扩展允许范围的方式保持兼容；删除旧类型或收紧已有关系客体，应留到 L1 2.0.0。

## 6. L2 数据域

L2 按九个数据域组织。数据域是管理和检索视图，不是九套相互隔离的数据库。

### 6.1 市场分类域

目的：建立行业、品类和子品类的统一边界。

必需字段：

~~~yaml
id: ind_enterprise_software
type: industry
canonical_name: 企业软件
aliases: []
description: 面向组织客户的软件产品和服务
scope: industry
market: CN
language: zh-CN
status: active
source_refs: []
valid_from: null
valid_to: null
version: 1.0.0
~~~

品类扩展字段：

~~~yaml
category_level: 1
parent_category_id: null
category_definition: 客户关系管理软件
inclusion_criteria: []
exclusion_criteria: []
adjacent_category_ids: []
~~~

推荐排列：

~~~text
Industry
  └── Category
       └── Subcategory
            └── Product
~~~

### 6.2 市场参与者域

目的：识别市场中的品牌、产品、竞品、替代方案、研究机构和来源主体。

字段：

~~~yaml
entity_id:
entity_type: brand | product | competitor | source
canonical_name:
aliases:
market_role:
category_ids:
region_codes:
official_domains:
source_refs:
valid_from:
valid_to:
~~~

竞争关系必须记录竞争范围：

~~~yaml
subject_id: brand_a
relation: competes_with
object_id: brand_b
scope:
  category_id: cat_crm
  audience_ids: [aud_smb_sales]
  use_case_ids: [uc_lead_management]
  region: CN
confidence: 0.81
source_refs: [src_review_001, src_category_report_002]
~~~

不得只因两个品牌出现在同一榜单中就建立直接竞争关系。

### 6.3 用户与决策链域

目的：统一行业中的用户角色、组织属性和购买角色。

~~~yaml
id: aud_smb_sales_manager
type: audience
canonical_name: 中小企业销售负责人
organization_type: enterprise
organization_size: 50-500
decision_roles:
  - user
  - influencer
  - decision_maker
job_to_be_done:
  - 统一管理销售线索
pain_point_ids:
  - prob_leads_fragmented
decision_factor_ids:
  - topic_implementation_time
  - topic_data_security
source_refs:
  - src_report_001
~~~

决策角色建议限定为：

~~~text
user, influencer, evaluator, buyer, decision_maker, administrator
~~~

### 6.4 问题与使用场景域

区分：

| 对象 | 含义 |
|---|---|
| problem | 用户遇到的痛点 |
| job_to_be_done | 用户想完成的任务 |
| use_case | 产品被使用的具体情境 |
| desired_outcome | 用户期望取得的结果 |

示例：

~~~yaml
problem:
  id: prob_leads_fragmented
  type: problem
  canonical_name: 销售线索分散
  affected_audience_ids: [aud_smb_sales_manager]
  severity: high
  source_refs: [src_user_research_001]

use_case:
  id: uc_omnichannel_lead_management
  type: use_case
  canonical_name: 多渠道销售线索统一管理
  related_problem_ids: [prob_leads_fragmented]
  desired_outcomes:
    - 缩短线索响应时间
    - 提升线索转化率
  source_refs: [src_report_001]
~~~

### 6.5 标准能力域

目的：建立行业共享能力字典，使 L3 能将品牌产品映射到同一能力坐标系。

在 L1 增加 capability 前，临时格式：

~~~yaml
id: cap_sales_forecasting
type: use_case
semantic_subtype: capability
canonical_name: 销售预测
definition: 基于历史和当前数据预测未来销售结果
parent_capability_id: cap_sales_analytics
related_problem_ids: []
supported_use_case_ids: [uc_quarter_sales_forecast]
evaluation_dimensions:
  - 数据输入范围
  - 预测粒度
  - 可解释性
source_refs: [src_standard_001]
~~~

能力字典只描述能力本身；具体品牌是否具备该能力属于 L3。

### 6.6 购买决策因素域

决策因素前期使用 topic 实体并增加 semantic_subtype: decision_factor。

~~~yaml
id: df_implementation_time
type: topic
semantic_subtype: decision_factor
canonical_name: 实施周期
definition: 从采购确认到主要用户可正常使用所需时间
applicable_category_ids: [cat_crm]
related_audience_ids: [aud_smb_sales_manager]
evaluation_method:
  - 平均项目周期
  - 数据迁移复杂度
  - 培训时间
importance: unknown
source_refs: [src_buyer_guide_001]
~~~

常见决策因素包括价格、总体拥有成本、功能、易用性、部署周期、集成、数据安全、合规、扩展性、服务、本地化和行业适配。

### 6.7 主题与问题空间域

主题应具有持续组织价值，不能把一次性新闻直接作为稳定主题。

~~~yaml
id: topic_crm_selection
type: topic
canonical_name: CRM 选型
parent_topic_id: topic_crm
related_audience_ids: [aud_smb_sales_manager]
related_problem_ids: [prob_leads_fragmented]
related_use_case_ids: [uc_omnichannel_lead_management]
related_intent_codes:
  - intent_comparison
  - intent_recommendation
question_patterns:
  - 中小企业选择 CRM 应考虑什么？
  - 哪些 CRM 更适合某类企业？
evidence_requirements:
  - product_documentation
  - independent_review
freshness_requirement: quarterly
source_refs: [src_buyer_guide_001]
~~~

Prompt 实例应由下游提问词挖掘任务生成，不应在 L2 抓取阶段无限生成。

### 6.8 行业事实、主张、趋势和事件域

使用 L1 的 fact、claim、observation 分类。统计、趋势、政策、事件作为 semantic_subtype。

~~~yaml
id: fact_crm_market_size_cn_2025
type: fact
semantic_subtype: statistic
canonical_name: 2025年中国CRM市场规模
statement: 某研究口径下的市场规模为 X
subject_entity_ids: [cat_crm]
value:
  amount: null
  unit: CNY
  scale: million
time_period:
  start: 2025-01-01
  end: 2025-12-31
geography: CN
methodology_summary:
applicable_scope:
source_refs: [src_report_001]
confidence: 0.80
verification_status: verified
valid_from: 2025-12-31
valid_to: null
~~~

统计数据必须保留：

- 原始值、单位和数量级
- 币种及是否换算
- 时间范围
- 地区和样本
- 市场口径
- 历史值还是预测值
- 报告方法和来源页码

### 6.9 来源与内容生态域

~~~yaml
id: src_report_001
type: source
canonical_name: 某机构CRM行业报告
source_type: industry_report
publisher:
url:
canonical_url:
language: zh-CN
market: CN
published_at:
collected_at:
authority_level: high
independence_level: high
access_policy:
copyright_policy:
content_hash:
raw_object_uri:
status: active
~~~

内容实体：

~~~yaml
id: content_001
type: content
canonical_name: 2026 CRM选型指南
content_type: buyer_guide
source_id: src_001
covered_topic_ids: [topic_crm_selection]
target_audience_ids: [aud_smb_sales_manager]
published_at:
updated_at:
content_hash:
source_refs: [src_001]
~~~

## 7. Skills 与 Tools

Skill 是带业务规则的工作能力；Tool 是原子操作接口。Skill 不应直接耦合某一家搜索或模型供应商。

### 7.1 Skills

| Skill | 职责 | 主要输出 |
|---|---|---|
| industry_scope_definition | 定义行业、市场、语言和研究边界 | scope manifest |
| industry_requirement_compilation | 把 L2 数据维度编译为机器可读研究需求 | Industry Knowledge Requirement |
| geo_research_job_planning | 将研究需求转成 geo-research 请求和覆盖要求 | upstream job request |
| industry_report_validation | 校验报告章节、来源清单、覆盖清单和证据包 | validated report package |
| industry_report_ingestion | 解析行业报告章节、表格、陈述和引用 | report candidates |
| citation_evidence_resolution | 将报告 [S#] 映射到已归档原始证据 | resolved evidence |
| industry_knowledge_extraction | 从报告候选中抽取实体、主题、问题、事实和关系 | extraction candidates |
| entity_resolution | 实体去重、别名归一和消歧 | canonical entities |
| claim_fact_verification | 用原始证据分类并验证事实、主张和观测 | verified statements |
| industry_topic_modeling | 建立稳定主题树和问题空间 | topic graph |
| knowledge_promotion | 将候选知识晋升到稳定 L2 | promotion decisions |
| knowledge_upsert | 版本化写入规范库和索引 | persisted records |
| knowledge_quality_audit | 检查完整性、冲突和过期数据 | quality report |
| context_compilation | 为下游任务提取行业子图和证据 | context package |

### 7.2 Tools

~~~text
compile_industry_requirement(scope, dimension_registry, source_policy)
run_geo_research(requirement, profile, source_policy)
read_industry_report(report_path)
validate_report_contract(report, requirement)
parse_report_sections(report)
parse_report_citations(report)
read_evidence_package(run_id)
resolve_citation(citation_label, evidence_package)
read_geo_research_content(content_path)
verify_content_hash(content, expected_sha256)
verify_evidence_support(statement, evidence_text)
register_report_import(report, requirement, run)
detect_duplicate(content_hash, semantic_hash)
extract_structured_knowledge(report_candidate, schema)
resolve_entity(candidate)
upsert_source(source)
upsert_document(document)
upsert_entity(entity)
upsert_relation(relation)
upsert_statement(statement)
build_text_index(records)
build_vector_index(records)
get_industry_subgraph(industry_id, topic_id, filters)
~~~

推荐工具类别：

- 上游搜索与抓取：复用 geo-research 的 SearXNG、Playwright 和机构清单。
- 上游报告和证据：复用 reports/*.md、run.json、plan.json、evidence.json、browser-items.jsonl 和 pages/*.txt。
- Markdown 解析：CommonMark 兼容 AST 解析器，保留标题、列表、表格、行号和 [S#]。
- Evidence Resolver：以 run_id 和 citation_label 做精确映射，不以语义搜索替代引用解析。
- 原始文档复核：必要时使用 Unstructured、Apache Tika 或定制清洗器，不覆盖原文。
- 调度：MVP 使用 Celery；复杂可靠流程使用 Temporal 或 Dagster。
- 对象存储：S3 兼容存储或 MinIO。
- 结构化存储：PostgreSQL。
- 全文检索：OpenSearch；MVP 可先使用 PostgreSQL Full Text Search。
- 向量索引：pgvector；规模增大后评估 Qdrant/Milvus。

## 8. 需求驱动的报告生成与知识抽取流程

### 8.1 定义行业范围

每个行业启动前创建 scope manifest：

~~~yaml
request_id: industry_crm_cn_001
mode: create
industry_id: ind_crm
industry_name: 企业软件
market: CN
languages: [zh-CN]
included_categories: [cat_crm]
excluded_categories: []
target_audiences:
  - 中小企业销售负责人
seed_competitors: []
seed_sources: []
priority_dimensions:
  - audience_and_decision_chain
  - problems_and_jobs
  - use_cases
  - capabilities
  - decision_factors
  - competition
research_questions:
  - 中小企业选择CRM最关注什么？
  - CRM产品需要哪些标准能力？
freshness_policy: weekly
~~~

行业边界不明确时不得生成研究任务。

mode 支持：

~~~text
create  新建行业基线
extend  增加地区、品类、用户或数据维度
refresh 更新过期事实、趋势和政策
correct 针对冲突或错误重新研究
~~~

系统先查询现有 coverage，只对缺失、过期或冲突维度生成补充研究，不重复构建整个行业。

### 8.2 编译行业数据需求

industry_requirement_compilation 从 L2 数据域注册表生成 Industry Knowledge Requirement。每个 required_dimension 必须包含：

~~~yaml
dimension_code: audience_and_decision_chain
required: true
questions:
  - 该品类有哪些核心用户角色？
  - 谁是使用者、评估者、采购者和决策者？
expected_fields:
  - audience_name
  - organization_type
  - organization_size
  - decision_role
  - job_to_be_done
required_source_classes:
  - industry_research
  - reliable_media
evidence_rules:
  require_sample_or_method: true
  min_independent_sources_for_generalization: 2
~~~

需求编译结果必须通过 Schema 校验后才能发送给 geo-research。

### 8.3 geo-research 生成完整行业报告

geo-research 根据需求执行：

~~~text
Industry Knowledge Requirement
→ 查询计划
→ 第三方机构覆盖
→ 搜索候选
→ 打开原始网页
→ 归档原始证据
→ 生成规范章节的完整行业报告
→ 输出引用和覆盖清单
~~~

来源覆盖顺序：

1. 政府、监管、标准和行业协会。
2. 学术论文和研究机构。
3. 行业报告和专业研究。
4. 可靠媒体、券商研究和上市公司披露。
5. 代表性竞品官网和产品文档。
6. 聚合入口仅用于追溯原始发布机构。

不调度社区和 UGC 来源。搜索摘要只用于发现，不进入行业报告的有效证据集。

每个 required_dimension 搜索完成后计算覆盖状态：

~~~text
covered_by_whitelist
covered_by_extended_sources
partial
missing
conflicting
blocked
not_applicable
~~~

当状态为 partial、missing、conflicting 或主要材料过期时，启动扩展权威来源发现。新来源通过身份、正式域名、专业相关性、原始发布、方法透明、时间范围、独立性和可追溯性核验后使用，并在报告的扩展来源记录中注明发现查询、选择理由、采用事实和局限。

### 8.4 校验报告交付包

industry_report_validation 检查：

1. report_id、requirement_id、run_id 一致。
2. 必需章节存在。
3. required_dimensions 均标记为 covered、partial 或 missing。
4. 所有 [S#] 在完整信源清单中存在。
5. 使用的 [S#] 可映射到 evidence.json 或已归档正文。
6. search-snippet、blocked 和社区来源没有进入有效证据。
7. 报告包含冲突、缺失数据和研究局限。
8. 报告生成模型和 Prompt 版本可追踪。

不合格报告返回 geo-research 补充研究或修订，不进入知识抽取。

### 8.5 解析行业报告

使用 Markdown AST 按稳定章节解析：

~~~text
heading
paragraph
list_item
table_row
blockquote
citation
~~~

每个候选保留 report_id、章节、行号、原文、表格坐标和 citation_labels。报告摘要可以辅助定位，但默认不产生稳定知识。

### 8.6 解析引用和核验证据

citation_evidence_resolution 对每条候选执行：

~~~text
[S#]
→ 完整信源清单
→ Evidence Package
→ browser record
→ pages/*.txt 原始正文
→ 精确证据片段
~~~

验证必须判断“证据是否直接支持陈述”，而不只是文本主题相似。若报告将厂商主张写成行业事实，应降级为 claim 或拒绝。

### 8.7 结构化知识抽取

抽取模型按 JSON Schema 输出：

~~~yaml
report_id:
requirement_id:
report_span:
entities: []
relations: []
statements: []
topics: []
questions: []
evidence_spans:
  - citation_label:
    source_record_id:
    quote:
    content_path:
extraction_model:
prompt_version:
extracted_at:
~~~

每个关系和陈述必须绑定原始 evidence_span。报告行号只用于报告血缘，不能代替来源证据。

抽取维度不是由 LLM 临时决定，而是三层约束：

~~~text
L1：允许的实体类型、关系类型和statement_class
L2：行业数据维度注册表、语义子类型和章节Extraction Profile
Request：本次研究实际启用的维度
~~~

每个报告章节绑定独立 Extraction Profile。例如 audience_and_decision_chain 只允许 audience、job_to_be_done、problem、decision_factor 及对应关系；market_facts 只允许 fact/statistic 及其数值字段。

实体抽取按以下优先级执行：

1. 已有规范实体和 aliases 字典精确匹配。
2. 章节字段和表格列的确定性规则映射。
3. 可选 NER/UIE 模型发现机构、产品、地点、时间和数值候选。
4. LLM 按章节 JSON Schema 抽取复杂实体。
5. L1 类型约束和原文 evidence_quote 校验。

关系识别按以下优先级执行：

1. 结构化表格和字段直接生成关系。
2. “属于、服务、解决、支持、竞争”等模式规则。
3. LLM 只能从当前 Extraction Profile 的 allowed_relations 枚举中选择。
4. 校验 subject_types、object_types、时间、地区和证据。
5. 无法映射的关系输出 unmapped_relation，不得自动创造新关系。

示例：

~~~yaml
extraction_profile: audience_and_decision_chain_v1
allowed_entity_types:
  - audience
  - problem
  - job_to_be_done
  - decision_factor
allowed_relations:
  - has_problem
  - performs
  - has_decision_factor
required_evidence:
  - citation_label
  - source_record_id
  - evidence_quote
~~~

### 8.8 实体归一

候选实体匹配顺序：

1. 精确 canonical_name。
2. aliases 和官方域名。
3. 外部稳定 ID，如 Wikidata ID。
4. 字符串与语义相似。
5. 关系上下文消歧。
6. 低置信度进入人工审核。

不得仅凭向量相似度自动合并品牌和产品。

推荐采用级联评分：

~~~text
稳定ID/官方域名
→ 规范名和别名
→ 字符串模糊匹配
→ Embedding候选召回
→ 行业、类型和邻接关系上下文
→ Cross-Encoder或LLM裁决
→ 人工审核
~~~

常用查询字段的归一结果必须保存 match_method、candidate_ids、match_score 和 reviewer。自动合并阈值通过首个行业黄金集校准，不在规范中凭经验写死。

### 8.9 知识分类与验证

执行 L1 claim_policy：

- 来源主体可验证、陈述客观且证据充分：fact。
- 含立场或营销判断：claim。
- 单次搜索或时点结果：observation。
- 基于多条前提得出的判断：inference，不直接进入稳定事实。

判定依据：

| 类别 | 判定条件 |
|---|---|
| fact | 原始证据直接陈述、客观可验证、范围和时间明确、证据满足来源策略 |
| claim | 带立场、评价、预测、营销、归因，或仅代表某机构/品牌观点 |
| observation | 特定时间、平台和条件下的搜索或市场观测 |
| inference | 原始证据未直接表达完整结论，结论由多个前提推导 |

规则引擎先根据来源、时态词、评价词、预测词、引用主体和是否直接陈述进行初判；LLM 在 statement_class 枚举中辅助分类；市场规模、监管、安全、效果、排名和冲突数据进入人工审核。

验证结果：

~~~text
verified
partially_verified
unverified
disputed
expired
rejected
~~~

### 8.10 知识晋升

候选知识经过以下门禁后写入稳定 L2：

1. 在行业范围内。
2. 实体类型和关系符合 L1。
3. 有可追溯来源和原文证据。
4. 通过事实/主张分类。
5. 无未解决的高风险冲突。
6. 时间、地区和适用范围明确。
7. 不与已有数据重复，或已完成版本合并。

未通过的记录保留在 staging，不删除原始证据。

## 9. 数据排列与查询视图

底层按规范对象存一次，上层提供四种视图。

### 9.1 市场分类树

~~~text
Industry → Category → Subcategory → Product
~~~

用于行业导航、范围过滤和品牌品类定位。

### 9.2 用户需求链

~~~text
Audience → Problem → UseCase → Desired Outcome
~~~

用于提问词挖掘、内容意图和选题。

### 9.3 解决方案链

~~~text
Problem → Capability → UseCase → Product → Brand
~~~

用于品牌匹配、竞品比较和文章中的解决方案完整性检查。

### 9.4 主题与证据链

~~~text
Topic → Question → Intent
  ↓
Fact / Claim → Evidence Span → Content → Source
~~~

用于内容 Brief、文章核验和引用。

不得将一份文档的全文复制到每个主题节点；主题节点只保存引用 ID。

## 10. 存储设计

### 10.1 原始文件与对象存储

geo-research 是原始抓取事实源。L2 可以将通过门禁的正文复制到独立对象存储，但必须保留 external_content_path 和 Hash。保存：

- 原始 HTML、PDF、Word 和图片
- 抓取响应和页面快照
- 解析后的 Markdown/JSON
- 文档版本和差异文件

### 10.2 PostgreSQL

建议新增 L2 表：

| 表 | 用途 |
|---|---|
| industry_scope | 行业研究范围 |
| industry_requirement | L2 行业数据需求及其版本 |
| research_report | geo-research 行业报告及交付状态 |
| report_section | 报告章节、表格和行号结构 |
| report_candidate | 从报告抽取的知识候选 |
| citation_resolution | 报告 [S#] 到原始证据的映射和验证结果 |
| external_import_record | geo-research 报告、运行和证据包的导入血缘 |
| source_instance | 实际来源实例 |
| document | 文档和版本元数据 |
| document_chunk | 结构化语义单元 |
| entity | L2/L3 实体实例 |
| entity_alias | 实体别名 |
| relation | 实体关系实例 |
| statement | fact/claim/observation/inference |
| evidence | 原文证据片段 |
| topic_membership | 主题层级和成员关系 |
| ingestion_job | 采集任务 |
| extraction_run | 抽取模型和版本 |
| review_queue | 人工审核队列 |

建议实体表关键字段：

~~~sql
id UUID PRIMARY KEY,
entity_type VARCHAR(50) REFERENCES entity_type(type_code),
canonical_name TEXT NOT NULL,
semantic_subtype VARCHAR(50),
scope VARCHAR(20) NOT NULL,
industry_id UUID,
market VARCHAR(20),
language VARCHAR(20),
attributes JSONB,
status VARCHAR(20),
valid_from TIMESTAMPTZ,
valid_to TIMESTAMPTZ,
version VARCHAR(20),
created_at TIMESTAMPTZ,
updated_at TIMESTAMPTZ
~~~

关系表关键字段：

~~~sql
id UUID PRIMARY KEY,
subject_id UUID NOT NULL,
relation_type VARCHAR(50) REFERENCES relation_type(relation_code),
object_id UUID NOT NULL,
scope JSONB,
confidence NUMERIC(4,3),
verification_status VARCHAR(30),
valid_from TIMESTAMPTZ,
valid_to TIMESTAMPTZ,
status VARCHAR(20),
created_at TIMESTAMPTZ,
updated_at TIMESTAMPTZ
~~~

证据关系建议独立成 relation_evidence，多对多关联 relation/statement 与 evidence。

industry_requirement 至少保存 requirement_id、industry_id、schema_version、required_dimensions、source_requirements、report_contract、status 和 content_hash。

research_report 至少保存 report_id、requirement_id、geo_research_run_id、report_path、report_hash、model、prompt_version、coverage_status 和 validation_status。

report_candidate 至少保存 report_id、section_code、report_span、statement、candidate_type、citation_labels、normalized_statement_hash 和 status。

citation_resolution 至少保存 report_candidate_id、citation_label、source_id、evidence_id、support_status、support_reason 和 verifier_version。

external_import_record 保存外部文件级血缘，不直接作为知识事实。

### 10.3 全文与向量索引

全文索引字段：

~~~text
title, section_title, normalized_text, entity_names,
topic_ids, source_type, market, language, published_at
~~~

向量索引单位：

- 文档语义块
- 主题摘要
- 事实陈述
- 用户问题

不要只为整篇文档生成单一向量。

### 10.4 图数据库

PostgreSQL 是唯一权威事实源；Neo4j 是可删除、可重建的图查询投影。业务写入、审核、版本和权限只发生在 PostgreSQL。

~~~text
PostgreSQL active + verified 数据
→ Graph Projection Service
→ Neo4j节点、Assertion和物化关系
~~~

节点映射：

~~~text
entity.entity_type=industry        → :Entity:Industry
entity.entity_type=category        → :Entity:Category
entity.entity_type=audience        → :Entity:Audience
entity.entity_type=problem         → :Entity:Problem
entity.entity_type=use_case        → :Entity:UseCase
entity.entity_type=capability      → :Entity:Capability
entity.entity_type=decision_factor → :Entity:DecisionFactor
entity.entity_type=topic           → :Entity:Topic
source_instance                    → :Source
research_report                    → :Report
evidence                           → :Evidence
statement/relation assertion       → :Assertion
~~~

关系映射：

~~~text
belongs_to               → BELONGS_TO
operates_in              → OPERATES_IN
serves                   → SERVES
has_problem              → HAS_PROBLEM
solves                   → SOLVES
has_capability           → HAS_CAPABILITY
supports_use_case        → SUPPORTS_USE_CASE
has_decision_factor      → HAS_DECISION_FACTOR
competes_with            → COMPETES_WITH
covers                   → COVERS
~~~

为保留证据、时间和审核状态，关系同时使用 Assertion 节点表达：

~~~text
(:Assertion)-[:SUBJECT]->(:Entity)
(:Assertion)-[:OBJECT]->(:Entity)
(:Assertion)-[:SUPPORTED_BY]->(:Evidence)
(:Assertion)-[:EXTRACTED_FROM]->(:Report)
(:Evidence)-[:FROM_SOURCE]->(:Source)
~~~

并为高频遍历生成物化直接关系：

~~~text
(:Audience)-[:HAS_DECISION_FACTOR {
  relation_id,
  assertion_id,
  confidence,
  verification_status,
  valid_from,
  valid_to
}]->(:DecisionFactor)
~~~

Assertion 负责证据与审计，直接关系负责查询性能。

Neo4j 至少创建 id 唯一约束：

~~~cypher
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (n:Entity) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT assertion_id_unique IF NOT EXISTS
FOR (n:Assertion) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS
FOR (n:Evidence) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT source_id_unique IF NOT EXISTS
FOR (n:Source) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT report_id_unique IF NOT EXISTS
FOR (n:Report) REQUIRE n.id IS UNIQUE;
~~~

同步顺序：

~~~text
1. Source和Report
2. Entity
3. Evidence
4. Assertion
5. Assertion证据链
6. 物化直接关系
7. 失效投影处理
8. 数量、孤立节点和抽样一致性校验
~~~

首次使用批量全量同步；增量使用 PostgreSQL Outbox：

~~~sql
CREATE TABLE graph_outbox (
  id UUID PRIMARY KEY,
  aggregate_type VARCHAR(50) NOT NULL,
  aggregate_id UUID NOT NULL,
  event_type VARCHAR(30) NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  retry_count INT NOT NULL DEFAULT 0,
  error TEXT
);
~~~

同步服务按稳定 UUID 执行幂等 MERGE。实体类型和关系类型必须经过 L1 白名单映射，不能把数据库字符串未经校验直接拼接到 Cypher。

PostgreSQL JSONB 中常用查询字段需扁平化为 Neo4j 标量属性；复杂嵌套 JSON 保留在 PostgreSQL。失效知识在 PostgreSQL 标记 inactive/expired，Neo4j 删除物化直接关系并按历史策略保留或停用 Assertion。

同步失败不能影响 PostgreSQL 事务。Neo4j 出现故障时，应能按 snapshot_id 从 PostgreSQL 完整重建。

## 11. Context Builder 接口

L2 不直接把整个行业库交给模型。下游通过统一接口请求子图。

请求：

~~~json
{
  "task": "prompt_generation",
  "industry_id": "ind_crm",
  "category_ids": ["cat_crm"],
  "audience_ids": ["aud_smb_sales_manager"],
  "topic_ids": ["topic_crm_selection"],
  "market": "CN",
  "language": "zh-CN",
  "freshness": "P365D",
  "evidence_level": "verified",
  "max_nodes": 80,
  "max_evidence": 20
}
~~~

返回：

~~~json
{
  "scope": {},
  "entities": [],
  "relations": [],
  "facts": [],
  "claims": [],
  "topic_summary": [],
  "question_space": [],
  "evidence": [],
  "conflicts": [],
  "missing_information": []
}
~~~

检索顺序遵循 L1 context_policy：

~~~text
结构化过滤
→ 规范实体和关系
→ 关键词与向量召回
→ 来源权威和时效排序
→ 去重与冲突标记
→ 证据压缩
~~~

## 12. 面向下游任务的输出

### 12.1 提问词挖掘

使用路径：

~~~text
Audience → Problem → UseCase → Category
Audience → DecisionFactor → Category
Category → Capability → Risk
Category → Competitor → ComparisonFactor
~~~

L2 提供问题空间和行业约束；L3 后续加入具体品牌。

### 12.2 文章优化

L2 提供目标主题的行业基准子图：

- 必须解释的概念
- 关键用户问题
- 主要决策因素
- 标准能力
- 风险和限制
- 可用权威来源

文章解析为内容子图后，与 L2 基准子图比较，得到主题缺失和证据缺失。

### 12.3 L3 品牌认知

L3 不重复创建行业对象，而是引用 L2 ID：

~~~text
品牌产品 → belongs_to → L2 品类
品牌产品 → has_capability → L2 能力
品牌 → serves → L2 用户角色
品牌内容 → covers → L2 主题
~~~

## 13. 更新策略

| 内容 | 建议更新方式 |
|---|---|
| 政策和监管 | 每日监测，事件触发重抓 |
| 竞品产品页和定价 | 每日变化检测，变化后解析 |
| 行业新闻 | 每日采集，默认进入 observation |
| 行业报告 | 每周发现、发布时抓取 |
| 行业主题树 | 每月评审，不随单次热点重建 |
| 稳定定义和能力字典 | 每季度复核 |
| 事实和统计 | 按 valid_to 或季度复核 |

更新采用 append + version，不原地删除历史数据。失效记录改为 inactive/expired。

## 14. 质量控制

### 14.1 自动检查

- 必需字段完整
- L1 类型和关系约束通过
- URL、时间和语言有效
- 有 source_refs 和 evidence_span
- 数值具备单位、时间和范围
- 内容 Hash 和近似重复检测
- 实体别名冲突
- 自环、非法关系和孤立节点
- 过期记录
- 高风险冲突

### 14.2 人工审核触发

- 新增行业根节点或一级品类
- 品牌/产品实体疑似错误合并
- 高权威来源相互冲突
- 市场规模、份额、监管和安全结论
- 新建直接竞争关系
- 低置信度实体映射
- 修改稳定主题树

### 14.3 数据质量状态

~~~text
candidate → normalized → extracted → verified
          → rejected
verified → active → expired / disputed / superseded
~~~

## 15. 安全、版权和合规

- 保存来源许可、抓取政策和使用限制。
- 遵守 robots.txt、站点条款和访问频率。
- 不绕过登录、付费墙、验证码或技术访问限制。
- 原始文档与对外生成权限分离。
- 受版权保护的内容默认只用于内部分析和短证据引用。
- 删除请求和来源撤回应能定位并清除派生索引。
- 搜索 API 密钥和客户凭证不得写入知识记录。
- L2 不读取 geo-research 的浏览器 profile、Cookie、登录凭证或 llm-config.local.json。
- 本版本不调度、导入或处理任何社区网站内容。

## 16. 推荐目录

~~~text
industry_knowledge/
├── README.md
├── scopes/
│   └── industry_scope.example.yaml
├── requirements/
│   └── industry_requirement.example.yaml
├── schemas/
│   ├── industry_requirement.schema.json
│   ├── research_report.schema.json
│   ├── report_candidate.schema.json
│   ├── citation_resolution.schema.json
│   ├── source.schema.json
│   ├── document.schema.json
│   ├── extraction.schema.json
│   └── context_package.schema.json
├── taxonomies/
│   ├── capabilities/
│   ├── decision_factors/
│   └── topics/
├── pipelines/
│   ├── requirement_compilation.yaml
│   ├── geo_research_report_job.yaml
│   ├── report_ingestion.yaml
│   ├── evidence_resolution.yaml
│   ├── extraction.yaml
│   └── promotion.yaml
├── policies/
│   ├── freshness.yaml
│   ├── deduplication.yaml
│   └── review.yaml
└── examples/
    └── crm/
~~~

采集运行数据、原始网页和密钥不得提交到 Git。

## 17. MVP 实施计划

### 阶段 1：单行业报告驱动闭环

- 选择一个行业和一个地区
- 实现 L2 行业数据维度注册表
- 生成并验证 Industry Knowledge Requirement
- 在 geo-research 中配置并标注 20～50 个第三方机构来源
- 为 sources.json 增加 source_class 和 l2_enabled
- 明确社区域名黑名单并验证不会进入 L2
- 让 geo-research 按报告章节合同输出完整行业报告
- 实现 Markdown 报告解析器和 [S#] Evidence Resolver
- 完成 requirement、report、candidate、citation、source、entity、relation、statement、evidence 表
- 抽取行业、品类、用户、问题、场景、主题和事实
- 建立人工审核队列

### 阶段 2：可检索知识

- BM25 与向量索引
- 实体别名和消歧
- 主题树和能力字典
- Context Builder
- 支持提问词生成和文章优化的子图输出

### 阶段 3：持续更新

- 定时任务和变化检测
- 冲突与过期处理
- 来源质量复核
- L4 观测暂存与知识晋升

## 18. MVP 验收标准

功能验收：

- 可以为一个行业创建并版本化 scope。
- 可以由 L2 生成完整、版本化的 Industry Knowledge Requirement。
- geo-research 能按需求合同生成包含固定章节、引用、覆盖清单和证据包的行业报告。
- L2 能从行业报告完成校验、解析、证据解析、抽取和入库。
- 重复导入同一报告版本不产生重复知识。
- 社区来源和 search-items.jsonl 无法通过导入门禁。
- 每个稳定实体、关系和事实可以追溯到原文证据。
- 能识别重复文档和重复实体。
- 能区分 fact、claim 和 observation。
- 能输出行业主题子图、用户需求链和证据链。
- Context Builder 能按行业、主题、时间和权威等级过滤。
- 下游可以用返回结果生成提问词或文章优化清单。

质量验收：

- 关键实体类型准确率由人工抽样评估。
- 高风险事实无来源率为 0。
- 稳定关系无证据率为 0。
- 统计数据缺少时间、单位或范围时禁止晋升。
- 高风险冲突必须进入人工审核。
- 所有抽取结果记录模型、Prompt 和 Schema 版本。
- 报告中的无引用结论和引用不支持结论不得晋升为 fact。

具体准确率阈值应在首个行业黄金集完成后设定，不在本版本中凭经验写死。

## 19. 后续需要形成的实现文档

本技术文档通过评审后，建议依次补充：

1. L2 PostgreSQL migration SQL。
2. Industry Knowledge Requirement 和数据维度注册表 Schema。
3. Research Report、Report Candidate、Citation Resolution 和 Context Package Schema。
4. Skill 输入输出协议。
5. geo-research 报告章节合同、Evidence Package 协议和 sources.json 来源分类迁移。
6. 首个试点行业 scope、需求文件、标准报告和黄金样例集。
7. L1 1.1.0 capability 本体变更提案。
8. L2 到 L3 的实体引用和租户隔离规范。
9. PostgreSQL Graph Outbox 与 Neo4j Projection Service。
10. Neo4j 节点、Assertion、关系约束和一致性测试。

## 20. 参考依据

标准规范：

- Schema.org：实体和网页内容类型
- W3C SKOS：概念体系、层级、别名和映射
- Wikidata：实体 ID、别名和跨语言对齐参考
- RFC 9309 Robots Exclusion Protocol
- Google Search Central：抓取、索引和结构化数据实践

研究方法：

- Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks
- From Local to Global: A Graph RAG Approach to Query-Focused Summarization
- GEO: Generative Engine Optimization
- Self-RAG
- Corrective Retrieval Augmented Generation

产品和行业实践：

- Profound：Prompt、引用、品牌与竞品可见度工作流
- Peec AI：品牌感知、Entity Map、Prompt Gap 和内容缺口
- Ahrefs Brand Radar：品牌提及、引用域名和竞争分析
- Scrunch AI：品牌信息、AI 抓取和答案准确性
- OpenSearch / pgvector / Neo4j：检索和图谱工程实践

产品公开口径仅作为功能参考，不直接作为 L2 稳定事实或质量阈值。
