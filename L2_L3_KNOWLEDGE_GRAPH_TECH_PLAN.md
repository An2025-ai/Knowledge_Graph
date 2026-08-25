# L2/L3 知识图谱构建技术执行方案

## 1. 背景与目标

当前项目已经将 L1 层 `common_knowledge` 作为统一的声明定义层，L1 内负责定义 L2/L3 的实体类型、关系类型、指标类型、抽取语义、门禁与晋级规则。后续 L2 `industry_knowledge` 和 L3 `brand_knowledge` 不再单独维护一套知识图谱构建维度、门禁标准或判定规则，而是作为执行层读取 L1 的定义来完成处理。

本方案的目标是重构 L2/L3 的文本解析与知识图谱构建流程，使其从“文件/报告导向”转为“证据与候选知识导向”。

核心变化如下：

| 层级 | 当前问题 | 新目标 |
| --- | --- | --- |
| L1 `common_knowledge` | 已基本成为统一定义层 | 继续作为 ontology、schema profile、抽取规则、晋级门禁的唯一控制平面 |
| L2 `industry_knowledge` | 当前仍偏向 Markdown 研究报告流，存在 source quality / authority 逻辑 | 改为直接处理信源文章正文，不再生成或依赖 md 报告；不做信源质量门禁 |
| L3 `brand_knowledge` | 当前有独立 ontology、独立文件门禁和较重的治理流程 | 改为读取 L1 的 L3 profile；仅保留敏感内容/公开引用风险提醒 |
| Runtime | L2/L3 pipeline 各自割裂，抽取、证据、融合链路不统一 | 形成统一的 document -> evidence -> document candidate -> gate candidate -> active graph 流程 |

## 2. 总体原则

### 2.1 L1 是唯一规则来源

L2/L3 执行逻辑必须读取以下 L1 定义：

- `common_knowledge/schema_profiles/l2_industry_profile.yaml`
- `common_knowledge/schema_profiles/l3_brand_profile.yaml`
- `common_knowledge/schema_profiles/extraction_rules.yaml`
- `common_knowledge/ontology/l2_industry/entities.yaml`
- `common_knowledge/ontology/l2_industry/relations.yaml`
- `common_knowledge/ontology/l2_industry/metrics.yaml`
- `common_knowledge/ontology/l3_brand/entities.yaml`
- `common_knowledge/ontology/l3_brand/relations.yaml`
- `common_knowledge/ontology/l3_brand/metrics.yaml`

L2/L3 不再单独定义：

- 知识图谱构建维度
- 实体/关系/指标标准
- 证据判定标准
- 晋级门禁标准
- claim/fact/observation/inference 分类标准

L2/L3 只保留执行流程、样例、局部词典、运行参数、用户上传文件处理逻辑。

### 2.2 文本块不是知识，候选知识才是图谱雏形

系统中要区分五类对象：

| 对象 | 类型 | 作用 |
| --- | --- | --- |
| `document` | 来源文档记录 | 记录文章/文件的唯一 ID、发布时间、原始链接 |
| `evidence_span` | 原文段落级证据 | 保存原文段落、标题路径、顺序、定位信息 |
| `evidence_unit` | 合并后的抽取输入块 | 由一个或多个相邻 span 合并而成，用于后续抽取 |
| `knowledge_candidate` | 单篇文章抽取出的结构化候选知识 | 已包含实体、关系、指标、事件、论点、证据引用、文章ID+段落ID |
| `gate_candidate_knowledge` | 门禁候选知识 | 经过跨文章处理后，准备进入 L1 门控和正式图谱的知识数据 |
| `active_knowledge` | 生效知识图谱 | 通过 L1 门禁后进入主图的正式知识 |

因此：

```text
原文正文
→ evidence_span / evidence_unit
→ knowledge_candidate
→ gate_candidate_knowledge
→ active_knowledge_graph
```

`knowledge_candidate` 不是文本块本身，而是已经完成结构化抽取的结果，只是还没有经过跨文章融合、冲突判断、补充聚合和 L1 晋级门禁。

## 3. 新版整体流程

### 3.0 主处理顺序

新版 L2/L3 主链路建议固定为：

```text
正文解析与 evidence_unit 生成
→ NER 识别候选实体
→ 正则/规则识别数值、时间、单位、显式关系触发词
→ 将 NER 与规则结果映射到 L1 ontology / extraction_rules
→ 基于 L1 映射结果筛选有关系的 evidence_unit，把无关的删除掉
→ LLM 在 L1 约束下抽取有价值的结构化知识候选
→ 对 knowledge_candidate 做向量化
→ 带完整溯源信息入库（文章ID）
→ 跨文章四类处理：融合、冲突、补充、跨实体建联
→ 形成证据层和门禁候选知识层
→ 基于 L1 门控规则晋级 active graph
```

这里要注意两个顺序边界：

1. NER 和正则/规则先识别实体、指标、时间、单位和关系线索，再映射到 L1 定义做预筛；它们是为了降低 LLM 成本，并帮助 LLM 聚焦 L1 定义内的有效信息，不是最终图谱结果。
2. 向量化建议发生在候选知识抽取之后、跨文章融合之前，这样后续 entity resolution、relation alignment、claim clustering、冲突检测都可以复用同一批 embedding。

所有中间产物都必须保留溯源信息，至少包括：

```yaml
document_id: DOC_001
published_at: "2026-08-01"
original_url: "https://example.com/article"
evidence_unit_id: EU_004
source_span_ids:
  - ES_010
  - ES_011
content_hash: "..."
```

这样后续如果某篇文章过期、失效、撤稿或版本更新，可以按 `document_id` 或 `content_hash` 追踪并处理它影响到的证据、文档级候选知识、门禁候选知识和 active graph。

### 3.1 L2 行业文章流

L2 新流程应从“研究报告 ingestion”改为“信源文章正文 ingestion”。

```text
article_registration
→ content_parsing
→ paragraph_span_generation
→ evidence_unit_merge
→ L1-aware candidate_extraction
→ candidate_normalization
→ candidate_vectorization_and_storage
→ cross_document_fusion
→ conflict_detection
→ complementary_enrichment
→ cross_entity_linking
→ L1_gate_promotion
→ active_industry_graph
```

L2 来源登记只做最小建档：

| 字段 | 说明 |
| --- | --- |
| `document_id` | 每篇文章唯一 ID |
| `layer` | 固定为 `l2_industry` |
| `published_at` | 文章发布时间 |
| `original_url` | 原始链接 | |

L2 不做以下检查：

- 不检查信源质量
- 不检查 source authority
- 不做权限门禁
- 不因来源等级拒绝进入解析流程

### 3.2 L3 品牌文件流

L3 与 L2 b主体流程基本相似，但增加一个轻量的敏感内容提醒步骤。注意L2、L3不共用主题流程，各自备份在自己的文件目录下。

```text
document_registration
→ sensitive_content_warning
→ content_parsing
→ paragraph_span_generation
→ evidence_unit_merge
→ L1-aware candidate_extraction
→ candidate_normalization
→ candidate_vectorization_and_storage
→ cross_document_fusion
→ conflict_detection
→ complementary_enrichment
→ cross_entity_linking
→ L1_gate_promotion
→ active_brand_graph
```

L3 的 `sensitive_content_warning` 只提醒，不直接阻断流程，除非未来产品层明确要求强阻断。

检查范围包括：

- PII / 个人信息
- 商业秘密
- 合同条款
- 未发布路线图
- 内部口径
- 客户案例是否允许公开引用
- 合同、价格、合作细节是否允许公开引用

输出建议：

```yaml
warning_id: WARN_001
document_id: DOC_001
warning_type: possible_pii | possible_contract | possible_roadmap | possible_confidential_claim
evidence_span_id: ES_012
message: "该段可能包含客户名称和未公开项目细节，建议用户确认是否允许公开引用。"
severity: low | medium | high
action: user_notice
```  

## 4. 正文解析与切片流程

### 4.1 正文解析的定义

正文解析不是直接抽取知识图谱，而是把原文变成可追溯、可引用、可抽取的结构化证据材料。

```text
原始文件/网页正文
→ 清洗
→ 结构化
→ 段落级切分
→ 证据 span 编号
→ 相邻 span 合并为 evidence_unit
```

解析阶段的目标：

- 保留原文证据
- 保留标题层级
- 保留段落顺序
- 保留上下文关系
- 为后续抽取提供大小合适的文本块

解析阶段不应该承担太重的图谱判断，否则成本高、误差早、后续难修正。

### 4.2 推荐切分粒度

第一阶段只处理三类文本来源：Markdown、PDF、HTML。切分以结构为主，不做过细语义切分。

三类来源的解析路线如下：

| 来源类型 | 切分方式 |
| --- | --- |
| Markdown | 使用 Markdown parser 解析 heading、paragraph、list、table、blockquote、code block；按 block 生成 `evidence_span` |
| HTML | 使用正文抽取器先去除导航、广告、脚注、推荐区，再按 DOM block 解析 `h1-h6`、`p`、`li`、`table`、`figure/caption` |
| PDF | 使用 PDF parser 提取页码、文本块、表格和版面顺序；先按页内阅读顺序还原，再按标题、段落、表格生成 `evidence_span` |

每个基础块生成一个 `evidence_span`。

```yaml
span_id: ES_001
document_id: DOC_001
span_type: heading | paragraph | list_item | table | caption
text: "原文段落内容"
heading_path:
  - "行业趋势"
  - "海外产能"
order_index: 12
locator:
  page: 3
  paragraph: 5
char_start: 1024
char_end: 1390
```

### 4.3 三类文本解析执行路线

#### 4.3.1 Markdown

推荐实现：

```text
读取 .md
→ 解析 heading / paragraph / list / table / blockquote
→ 维护 heading_path
→ 每个结构块生成 evidence_span
→ 保留原始字符 offset 或 block_index
```

建议技术：

- 轻量实现：按 Markdown block 解析
- 可选 parser：`markdown-it-py` 或 Python Markdown AST parser
- 表格：按完整 table block 保留，不拆成孤立单元格

输出规则：

| Markdown 元素 | span_type | 处理方式 |
| --- | --- | --- |
| `# / ## / ###` | `heading` | 更新 `heading_path`，同时生成 span |
| 普通段落 | `paragraph` | 生成独立 span |
| 列表项 | `list_item` | 每个列表项生成 span，后续可与前导句合并 |
| 表格 | `table` | 整表生成 span，保留原始 Markdown |
| 引用 | `blockquote` | 生成 span，标记引用来源上下文 |

#### 4.3.2 HTML

推荐实现：

```text
读取 HTML / URL 抓取正文
→ trafilatura 提取正文
→ BeautifulSoup 解析 DOM 结构
→ 去除 nav / footer / script / style / ads / related links
→ 解析 h1-h6 / p / li / table / figure / caption
→ 生成 evidence_span
```

建议技术：

- 正文抽取：`trafilatura`
- DOM 解析：`beautifulsoup4 + lxml`
- HTML 清洗：删除导航、广告、推荐阅读、脚注、脚本样式

输出规则：

| HTML 元素 | span_type | 处理方式 |
| --- | --- | --- |
| `h1-h6` | `heading` | 维护层级路径 |
| `p` | `paragraph` | 过滤过短噪声段 |
| `li` | `list_item` | 保留列表顺序 |
| `table` | `table` | 转为 Markdown table 或结构化 JSON |
| `figcaption/caption` | `caption` | 与图片/表格说明一起保留 |

#### 4.3.3 PDF

推荐实现：

```text
读取 PDF
→ PyMuPDF 按页提取 text blocks
→ 按页码、block 坐标、阅读顺序排序
→ 识别标题、段落、表格候选
→ 生成 evidence_span
```

建议技术：

- 默认：`pymupdf`
- 表格增强：必要时引入 `pdfplumber`
- 复杂扫描件：第一版不默认处理 OCR，进入人工或异步 OCR 队列

输出规则：

| PDF 内容 | span_type | 处理方式 |
| --- | --- | --- |
| 字号较大/加粗/短文本 | `heading` | 作为标题候选，更新 `heading_path` |
| 普通文本块 | `paragraph` | 按阅读顺序合并同一段落断行 |
| 表格区域 | `table` | 能识别则结构化，不能识别则保留页内文本块 |
| 页眉页脚 | `noise` | 默认过滤，但记录过滤规则 |

PDF 必须保留定位信息：

```yaml
locator:
  page: 3
  block_no: 12
  bbox: [72.0, 140.5, 510.0, 198.0]
```

### 4.4 为什么不能切得太细

切分的目的不是把文本拆成最小 token，而是为后续做两件事：

1. 用 L1 预筛、NER、正则规则快速判断这个块是否值得进入抽取。
2. 给 LLM 抽取提供足够上下文，减少断章取义。

如果切得过细，会出现：

- 标题和正文分离，导致语义丢失
- 指标值和指标对象分离
- 代词、简称、上下文关系丢失
- 后续需要大量补上下文，成本反而更高

所以建议：

```text
基础 span：段落级
抽取 unit：1-5 个相邻 span 合并
超长 unit：按 token 上限拆成多个窗口，但保留 overlap 和 heading_path
```

### 4.5 evidence_span 是什么

`evidence_span` 是证据定位单元。它的作用不是判断知识是否正确，而是回答：

```text
这条候选知识来自哪篇文章的哪一段原文？
```

它要支持：

- 原文追溯
- 人工复核
- LLM 证据校验
- 跨文章融合后的证据聚合
- 之后前端展示“证据来源”

技术实现上，`evidence_span` 不需要复杂模型。主要依靠结构解析器、段落切分、原文 offset、标题路径和唯一编号。

## 5. evidence_unit 合并策略

### 5.1 evidence_unit 的定位

`evidence_unit` 是后续抽取阶段的输入块。它通常由一个或多个相邻 `evidence_span` 合并而来。

例如：

```text
ES_010: "海外产能加速"
ES_011: "宁德时代正在加快海外产能建设..."
ES_012: "2025 年欧洲电池工厂产能预计达到 100GWh..."
```

可以合并为：

```yaml
unit_id: EU_004
document_id: DOC_001
source_span_ids:
  - ES_010
  - ES_011
  - ES_012
text: "海外产能加速\n宁德时代正在加快海外产能建设...\n2025 年欧洲电池工厂产能预计达到 100GWh..."
merge_reason:
  - heading_with_following_paragraph
  - metric_context_dependency
```

### 5.2 合并时使用哪些技术

合并阶段只使用两类技术：

```text
结构规则
→ 小 LLM 合并判断
→ 生成 evidence_unit
→ 导入抽取阶段
```

#### 5.2.1 结构规则

直接基于文本结构判断：

- 标题与其后的正文合并
- 列表项与前导句合并
- 表格 caption 与表格合并
- 短段落与后文合并
- 单独数字/指标段落与前后段合并
- 引用说明、注释与被说明段落合并

这是性价比最高的一层，不依赖模型。

#### 5.2.2 小 LLM 合并判断

LLM 只处理结构规则无法确定的边界，避免成本过高。

输入：

```yaml
profile_id: l2_industry / l3_brand
heading_path: [...]
previous_span: ...
current_span: ...
next_span: ...
l1_semantic_terms: [...]
```

输出：

```yaml
merge_with_previous: true
merge_with_next: false
reason: "当前段落中的指标缺少主体，需要与上一段合并。"
```

LLM 在这个阶段只回答“是否合并”，不要承担深度抽取。

#### 5.2.3 合并执行规则

合并执行时按文章顺序扫描 `evidence_span`：

```text
读取 document 下全部 evidence_span
→ 按 order_index 排序
→ 先应用结构规则生成确定合并组
→ 对不确定边界调用小 LLM
→ 生成 evidence_unit
→ 写入 evidence_units
→ 将 evidence_unit 导入 candidate_extraction
```

每个 `evidence_unit` 必须记录：

```yaml
unit_id: EU_004
document_id: DOC_001
source_span_ids:
  - ES_010
  - ES_011
heading_path:
  - "行业趋势"
text: "合并后的原文文本"
merge_method: structure_rule | llm_boundary_decision
merge_reason:
  - heading_with_following_paragraph
token_count: 620
order_start: 10
order_end: 11
```

合并后的 `evidence_unit` 直接进入抽取阶段。embedding 不参与当前合并流程，候选知识抽取完成后再做向量化，用于跨文章融合、冲突、补充和建联。

### 5.3 是否需要提前做大词典/别名扩充

不建议一开始投入大量时间做庞大词典。更高性价比的路线是：

```text
L1 ontology 基础词
→ 运行时自动归一化
→ NER 抽取高频实体
→ embedding 发现近似表达
→ LLM 对高频/高价值别名做确认
→ 逐步沉淀 alias dictionary
```

也就是说，先让系统跑起来，再从实际文章中增量扩充词典。

## 6. 候选知识抽取

### 6.1 抽取输入

候选知识抽取以 `evidence_unit` 为输入，而不是整篇文章，也不是孤立短句。

输入上下文包括：

- `document_id`
- `published_at`
- `original_url`
- `heading_path`
- `evidence_unit.text`
- `source_span_ids`
- 当前 layer 的 L1 profile
- 当前 layer 的 entity/relation/metric ontology
- L1 extraction_rules

### 6.2 抽取输出

每个 `knowledge_candidate` 应该已经结构化，包括实体、关系、指标、事件或论点。

示例：

```yaml
candidate_id: KC_001
profile_id: l2_industry
layer: l2_industry
document_id: DOC_001
evidence_unit_id: EU_004
source_span_ids:
  - ES_010
  - ES_011
  - ES_012
candidate_type: relation | metric | statement | event

subject:
  name: "宁德时代"
  entity_type: company
  normalized_name: "CATL"

predicate:
  relation_type: supplies_to

object:
  name: "特斯拉"
  entity_type: company

metric:
  metric_name: "产能"
  metric_value: 100
  metric_unit: "GWh"
  time_scope: "2025"
  geo_scope: "欧洲"

statement:
  text: "宁德时代 2025 年欧洲电池工厂产能预计达到 100GWh，并继续向特斯拉供货。"
  statement_class: observation

evidence:
  evidence_text: "原文证据片段"
  evidence_unit_id: EU_004
  source_doc: DOC_001

confidence: 0.82
extraction_method:
  - ner
  - l1_prompted_llm
```

### 6.3 抽取技术路线

候选抽取建议采用分层模型路由，而不是所有文本都直接交给大模型。

```text
NER 识别候选实体 mention
→ 规则/正则识别数值、时间、单位、关系触发词
→ 将 NER / 规则结果映射到 L1 ontology / extraction_rules
→ 基于 L1 映射结果进行预筛选
→ LLM 结构化抽取
→ schema validate
→ evidence support check
→ candidate vectorization
→ source-aware storage
```

#### 6.3.1 预筛选

预筛选不是直接让 LLM 判断，也不是只做关键词匹配，而是用 NER 和规则/正则先识别文本中的结构化信号，再映射到 L1 判断是否属于当前层的抽取范围。

执行逻辑：

```text
输入 evidence_unit
→ NER 识别候选实体 mention
→ 正则/规则识别数值、时间、单位、关系触发词
→ 将实体类型、关系线索、指标线索映射到 L1 定义
→ 检查是否符合当前 profile 的 include / exclude / ontology 范围
→ 输出 should_extract
```

预筛选必须基于当前 layer 的 L1 profile 执行。例如：

- L2 只筛选行业、品类、市场、客群、需求、痛点、机会、风险、趋势、竞争、行业指标等相关内容。
- L3 只筛选品牌、产品、解决方案、能力、服务、客户、案例、认证、交付结果、品牌主张、适用边界等相关内容。

判断规则：

| 判断项 | 处理方式 |
| --- | --- |
| NER 识别出实体，且实体类型可映射到当前 L1 entity type | 作为有效实体信号 |
| NER 识别出实体，但类型不在当前 L1 profile 范围内 | 不作为抽取信号，只保留为上下文 |
| 正则识别出数值、单位、时间 | 作为 metric / time_scope 信号 |
| 规则命中关系触发词 | 作为 relation candidate signal，不直接生成最终关系 |
| 命中 L1 exclude 范围 | 降低分数或跳过抽取 |
| 无实体、无指标、无关系线索、无 L1 维度信号 | 只存证据，不进入 LLM 抽取 |

预筛选输出建议：

```yaml
unit_id: EU_004
profile_id: l2_industry
entity_mentions:
  - text: "宁德时代"
    ner_type: ORG
    mapped_l1_type: company
    l1_allowed: true
  - text: "特斯拉"
    ner_type: ORG
    mapped_l1_type: company
    l1_allowed: true
metric_signals:
  - text: "100GWh"
    signal_type: metric_value
relation_signals:
  - trigger: "供应"
    mapped_l1_relation_candidates:
      - supplies_to
matched_l1_terms:
  - company
  - metric
  - supplies_to
should_extract: true
prefilter_confidence: 0.74
```

#### 6.3.2 NER

NER 用于发现候选实体：

- 公司
- 品牌
- 产品
- 地区
- 人群
- 技术
- 认证
- 客户
- 时间
- 数值

NER 的输出不是最终实体，只是候选实体 mention。系统需要把 NER 类型映射到 L1 entity type，再判断是否允许进入当前层的抽取范围。

示例：

```text
NER 输出：ORG
→ L1 映射：company / brand / institution
→ 当前 profile 校验：l2_industry 是否允许 company
→ 允许则进入候选实体信号，不允许则只作为证据上下文保留
```

因此，NER 本身负责“识别文本里像实体的片段”，L1 负责“判断这个实体类型是否符合当前层的图谱规则”。

#### 6.3.3 正则与规则

正则指的是通过固定文本模式识别明确结构。它在这里主要做识别和辅助抽取，不负责复杂语义判断，例如：

- 数值：`100GWh`、`15%`、`3.5亿元`
- 时间：`2025年`、`Q3`、`过去三年`
- 增长表达：`同比增长`、`CAGR`、`环比下降`
- 关系触发词：`供应给`、`合作伙伴`、`用于`、`认证通过`
- 列表结构：`包括 A、B、C`

正则适合识别“形式明确”的内容，不适合判断复杂语义。关系触发词只表示这里可能存在某类关系，不等于已经生成最终关系。

示例：

```text
原文：宁德时代向特斯拉供应电池。
NER：宁德时代=ORG，特斯拉=ORG
正则/规则：命中“向 X 供应 Y”
L1 映射：ORG -> company；供应 -> supplies_to
预筛结果：should_extract=true
LLM 抽取：宁德时代 -- supplies_to --> 特斯拉
```

正则结果应作为 LLM 的辅助上下文传入，帮助 LLM 更稳定地抽取指标、时间、单位和关系对象。

#### 6.3.4 LLM

LLM 负责最有价值的一步：

- 在 L1 约束下输出结构化 JSON
- 从 evidence_unit 中抽取真正有价值的知识单元
- 区分 fact / claim / observation / inference
- 从原文中绑定 evidence_text
- 补齐 scope、time、metric condition 等上下文字段
- 对不确定内容标记低置信度或保留 statement

LLM 必须遵守：

```text
只抽取原文直接支持的信息
不补充外部知识
不输出 L1 profile 未定义的实体、关系、指标类型
每条候选知识必须带 evidence_unit_id / source_span_ids
```

LLM 抽取出来的不是最终主图节点，而是 `knowledge_candidate`。它必须能够被后续融合、冲突、补充、建联流程消费。

#### 6.3.5 候选知识向量化与溯源入库

LLM 生成 `knowledge_candidate` 后，应立即做向量化和溯源入库。

本方案中 embedding 不参与切片合并，也不作为预筛选的必要步骤；它主要服务于候选知识生成后的跨文章处理。

向量化只处理实体、关系和知识内容本身，不把来源、证据编号、文章 ID、发布时间、原始链接等溯源字段拼进 embedding 文本。

建议向量化对象：

| 对象 | 向量化文本 |
| --- | --- |
| 实体 | `entity name + entity type + aliases/normalized_name` |
| 关系 | `subject name + relation type + object name + scope` |
| 指标知识 | `subject name + metric_name + metric_value + unit + scope + time_scope` |
| 论点/事件知识 | `statement_text / event_type + subject + object + scope + time_scope` |

向量化后的结果用于：

- 跨文章实体归一
- 候选关系去重
- 论点聚类
- 相似指标召回
- 冲突候选发现
- 证据检索和人工复核

不建议用 embedding 直接决定事实真假。它只回答“语义是否接近”。

入库时必须把向量信息和溯源信息分开保存：

```yaml
candidate_id: KC_001
candidate_embedding_id: EMB_KC_001

document_id: DOC_001
published_at: "2026-08-01"
original_url: "https://example.com/article"
content_hash: "..."
evidence_unit_id: EU_004
source_span_ids:
  - ES_010
  - ES_011
```

这样后续处理时间失效文章时，可以执行：

```text
document_id 失效
→ 找到该 document 下的 evidence_span / evidence_unit
→ 找到依赖这些 evidence 的 knowledge_candidate
→ 找到受影响的 gate_candidate_knowledge / active_knowledge
→ 重新计算 support_count、confidence、conflict_status
→ 必要时降级、撤回或重新晋级
```

## 7. L1-aware 上下文补充

### 7.1 什么是 L1-aware

L1-aware 不是指在切片或合并阶段完成完整抽取。新版流程中，解析/合并阶段主要保留原文结构和上下文；L1 主要用于预筛选、LLM 抽取、schema 校验和晋级门控。

例如 L2 关注：

- 行业
- 品类
- 市场分层
- 客群
- 需求
- 痛点
- 机会
- 风险
- 趋势
- 竞争格局
- 行业指标

L3 关注：

- 品牌
- 产品
- 解决方案
- 能力
- 服务
- 客户
- 案例
- 认证
- 交付结果
- 品牌主张
- 适用边界

### 7.2 在预筛选阶段如何使用 L1-aware

预筛选阶段使用 NER 与正则/规则的识别结果，再映射到 L1：

- NER 实体类型是否能映射到当前 L1 entity type
- 关系触发词是否能映射到当前 L1 relation type
- 数值、时间、单位是否能映射到当前 L1 metric type
- evidence_unit 是否符合当前 profile 的 include 范围
- evidence_unit 是否命中当前 profile 的 exclude 范围

预筛选阶段只决定 `should_extract`，不输出最终实体关系。

### 7.3 在抽取阶段如何使用 L1-aware

抽取阶段深度使用 L1：

- 限定可抽取实体类型
- 限定可抽取关系类型
- 限定可抽取指标类型
- 限定 statement class
- 应用 L1 prompt_output_rules
- 应用 L1 promotion_policy

## 8. 跨文章知识融合

### 8.1 为什么需要跨文章处理

如果基于 50 篇文章构建图谱，不能把 50 篇文章的抽取结果直接堆到主图。不同文章之间会出现：

- 同一实体的不同叫法
- 同一关系的重复表达
- 同一指标的多个数值
- 同一事件的不同补充信息
- 不同文章实体之间的新关系
- 时间版本不同造成的信息更新
- 真实冲突

因此必须有独立的 `Graph Consolidation / Knowledge Fusion` 阶段。

### 8.2 跨文章处理的四类动作

#### 8.2.1 融合

将不同文章中表达相同含义的实体、关系、指标、事件、论点合并为一条门禁候选知识。

示例：

```text
文章 A：特斯拉
文章 B：Tesla
文章 C：Tesla Inc.
```

融合后：

```yaml
entity_id: GE_001
name: "Tesla"
aliases:
  - "特斯拉"
  - "Tesla Inc."
source_mentions:
  - document_id: DOC_001
    evidence_unit_id: EU_003
  - document_id: DOC_014
    evidence_unit_id: EU_008
confidence: 0.94
```

#### 8.2.2 冲突

不同文章对同一对象、同一范围、同一时间给出不一致信息时，标记冲突，不强行覆盖。

冲突类型：

| 类型 | 说明 |
| --- | --- |
| `value_conflict` | 数值冲突 |
| `time_conflict` | 时间冲突 |
| `polarity_conflict` | 肯定/否定冲突 |
| `scope_conflict` | 范围不同造成的表面冲突 |
| `version_conflict` | 新旧版本信息不一致 |

处理原则：

```text
能解释为 scope 不同：标记 scope_difference，不作为强冲突
能解释为时间更新：保留版本链，默认 latest 可作为当前推荐值
不能解释：进入 conflict_pending
```

#### 8.2.3 补充

不同文章对同一事件或同一知识点提供不同侧面时，做结构化补充。

例如：

```text
文章 A：品牌 X 进入东南亚市场
文章 B：首站选择泰国
文章 C：采用经销商模式
文章 D：主推中端产品线
```

补充后：

```yaml
knowledge_id: GK_001
event_type: market_entry
subject: Brand X
target_market: Southeast Asia
first_country: Thailand
go_to_market_model: distributor
product_focus: mid-range products
evidence_refs:
  - DOC_001 / EU_003
  - DOC_002 / EU_006
  - DOC_003 / EU_002
  - DOC_004 / EU_008
```

#### 8.2.4 跨实体建联

不同文章中抽出的实体之间可能通过已有关系链形成新边。

例如：

```text
文章 A：品牌 A 推出产品 X
文章 B：产品 X 采用供应商 B 的部件
文章 C：供应商 B 同时服务竞品 C
```

可以得到：

```text
品牌 A -- owns_product --> 产品 X
产品 X -- uses_component_from --> 供应商 B
供应商 B -- supplies_to --> 竞品 C
品牌 A -- indirect_supply_overlap_with --> 竞品 C
```

最后一条是推导关系，必须标记：

```yaml
relation_id: IR_001
relation_type: indirect_supply_overlap_with
subject: Brand A
object: Competitor C
is_inferred: true
derived_from:
  - relation_id: CR_101
  - relation_id: CR_102
inference_rule: shared_supplier_chain
confidence: 0.72
```

显式关系和推导关系要分开存储或至少明确标记。

### 8.3 跨文章融合主流技术路线

跨文章处理的目标不是保存“融合过程”，而是把多篇文章的 `knowledge_candidates` 整理成可以进入 L1 门控的 `gate_candidate_entities` 和 `gate_candidate_knowledge`。

推荐采用规则 + embedding + LLM 兜底的混合方案。

输入：

```text
knowledge_candidates
candidate embeddings（只包含实体、关系、知识内容语义）
L1 ontology / extraction_rules / promotion_policy
```

输出：

```text
gate_candidate_knowledge
```

主流程：

```text
1. candidate_pool_loading
2. entity_resolution
3. knowledge_grouping
4. group_decision
5. gate_candidate_generation
6. L1_gate_promotion
```

#### 8.3.1 candidate_pool_loading

读取所有文档级候选知识，按当前 `profile_id`、`layer`、业务 scope 和处理批次形成候选池。

候选池最小输入字段：

```yaml
candidate_id: KC_001
profile_id: l2_industry
document_id: DOC_001
published_at: "2026-08-01"
knowledge_type: relation | metric | statement | event
subject: object
predicate: object optional
object: object optional
metric: object optional
statement: object optional
event: object optional
evidence_refs: array
embedding_id: string
confidence: float
```

处理要求：

- 只处理同一 `profile_id` 下的候选知识。
- L2 和 L3 不跨层融合。
- 已失效、撤稿、被用户排除的 document 不进入候选池。
- 每条候选必须带 `document_id` 和 `evidence_refs`，但这些字段只用于溯源和门禁，不参与 embedding 文本。

#### 8.3.2 entity_resolution

判断不同文章中的实体 mention 是否为同一个实体。

技术组合：

- 名称标准化：大小写、符号、公司后缀、简称处理
- NER 类型约束：公司只和公司合并，产品只和产品合并
- alias dictionary：从 L1、已有图谱、运行时高频别名沉淀
- embedding：比较实体名称 + 上下文描述
- LLM：只处理高价值且不确定的合并

执行逻辑：

```text
实体 mention 标准化
→ 按 entity_type 分桶
→ 同名/别名/简称规则合并
→ 对剩余相似实体用 embedding 召回候选
→ 对高相似但不确定样本调用 LLM 判断
→ 生成 gate_candidate_entity
```

判断输出：

```yaml
entity_id: GE_001
entity_type: company
name: "Tesla"
aliases:
  - "特斯拉"
  - "Tesla Inc."
source_candidate_ids:
  - KC_001
  - KC_018
evidence_refs:
  - DOC_001 / EU_004
  - DOC_014 / EU_002
confidence: 0.94
```

#### 8.3.3 knowledge_grouping

把文档级候选知识按照类型分组，分别处理 relation、metric、statement、event。

##### Relation Grouping

判断不同候选关系是否应进入同一条门禁候选关系。

优先使用确定性 key：

```text
profile_id
subject_entity_id
relation_type
object_entity_id
scope
time_scope
```

如果 key 相同，直接进入同组；如果 key 不完全相同但 embedding 相似度高，再交给 LLM 判断是否同组。

##### Statement Grouping

判断不同 statement 是否表达同一论点。

优先使用：

```text
profile_id
subject_entity_id
statement_class
normalized_claim
scope
time_scope
```

处理方式：

- 规则归一化
- embedding 召回相似论点
- LLM 小批量判断是否同一论点

##### Metric Grouping

指标融合需要更严格，不能只看语义相似。

优先使用：

```text
profile_id
subject_entity_id
metric_name
geo_scope
time_scope
market_scope
calculation_method
unit
```

如果 `metric_name` 一样但时间、区域或口径不同，应该作为补充，不作为冲突。

如果时间、区域、口径都相同但数值不同，才进入冲突检测。

##### Event Grouping

事件融合适用于市场进入、合作、发布、融资、认证、召回、政策变化等。

优先使用：

```text
event_type
subject_entity_id
object_entity_id / target_scope
event_time
geo_scope
```

事件可以被多篇文章持续补充属性。

#### 8.3.4 group_decision

对每个候选组做四类处理判断：融合、冲突、补充、跨实体建联。

| 处理类型 | 判断条件 | 输出方式 |
| --- | --- | --- |
| 融合 | 多条候选表达同一实体、关系、指标、事件或论点 | 合并为一条 `gate_candidate_knowledge`，聚合证据 |
| 冲突 | 同一 subject、predicate、scope、time 下出现相反结论或不同数值 | 不生成通过态知识；可生成 `gate_status: pending` 的门禁候选，并在 `decision_note` 标注冲突原因 |
| 补充 | 多条候选描述同一对象的不同属性、不同时间、不同区域或不同口径 | 合并到同一知识对象的不同字段或 evidence_refs 中 |
| 跨实体建联 | 多条显式关系可以组成新的有效关系 | 生成 `knowledge_type: relation` 的门禁候选，并标记 `is_inferred: true` |

冲突和补充不作为独立长期数据表存储，只影响门禁候选知识的字段、状态和证据聚合方式。

建议 `group_decision` 输出：

```yaml
group_id: KG_001
decision_type: merge | conflict_pending | complementary_merge | inferred_relation
target_gate_candidate_type: relation | metric | statement | event
source_candidate_ids:
  - KC_001
  - KC_018
decision_note: "两条候选关系主体、客体、关系类型一致，证据来自不同文章，可合并。"
gate_status: pending
```

#### 8.3.5 gate_candidate_generation

将 `group_decision` 结果转换为门禁候选知识。

关系型输出：

```yaml
knowledge_id: GK_001
profile_id: l2_industry
layer: l2_industry
knowledge_type: relation
subject_entity_id: GE_001
predicate_type: supplies_to
object_entity_id: GE_002
scope:
  product: "battery"
time_scope:
  value: "2025"
evidence_refs:
  - document_id: DOC_001
    evidence_unit_id: EU_004
  - document_id: DOC_014
    evidence_unit_id: EU_002
source_candidate_ids:
  - KC_001
  - KC_018
source_document_ids:
  - DOC_001
  - DOC_014
latest_published_at: "2026-08-01"
confidence: 0.88
gate_status: pending
```

指标型输出：

```yaml
knowledge_id: GK_002
profile_id: l2_industry
layer: l2_industry
knowledge_type: metric
subject_entity_id: GE_003
metric_name: market_size
metric_value:
  value: 500
  unit: "亿元"
scope:
  market: "中国"
time_scope:
  value: "2025"
evidence_refs:
  - document_id: DOC_006
    evidence_unit_id: EU_009
source_candidate_ids:
  - KC_031
latest_published_at: "2026-07-20"
confidence: 0.81
gate_status: pending
```

推导关系输出：

```yaml
knowledge_id: GK_003
profile_id: l3_brand
layer: l3_brand
knowledge_type: relation
subject_entity_id: GE_010
predicate_type: indirect_supply_overlap_with
object_entity_id: GE_023
is_inferred: true
derived_from_candidate_ids:
  - KC_041
  - KC_044
inference_rule: shared_supplier_chain
evidence_refs:
  - document_id: DOC_011
    evidence_unit_id: EU_003
  - document_id: DOC_019
    evidence_unit_id: EU_007
confidence: 0.72
gate_status: pending
```

#### 8.3.6 L1_gate_promotion

门禁候选知识生成后，再进入 L1 门控。

L1 门控检查：

- entity_type 是否属于当前 L1 ontology
- relation_type / metric_name 是否属于当前 L1 ontology
- evidence_refs 是否存在且可追溯
- confidence 是否达到 L1 profile 阈值
- `gate_status` 是否允许晋级
- 推导关系是否带 `is_inferred`、`derived_from_candidate_ids` 和 `inference_rule`

通过后写入 `active_knowledge_graph`；不通过则保留在门禁候选知识层，状态为 `rejected` 或 `pending`。

## 9. 数据存储建议

### 9.1 证据层

#### `documents`

```yaml
document_id: string
layer: l2_industry | l3_brand
published_at: datetime
original_url: string
title: string optional
content_hash: string optional
source_status: active | expired | retracted | updated optional
created_at: datetime
```

#### `evidence_spans`

```yaml
span_id: string
document_id: string
span_type: heading | paragraph | list_item | table | caption
text: string
heading_path: array
order_index: int
locator: object
char_start: int
char_end: int
embedding_id: string optional
```

#### `evidence_units`

```yaml
unit_id: string
document_id: string
source_span_ids: array
text: string
heading_path: array
merge_reason: array
token_count: int
embedding_id: string optional
```

### 9.2 文档级候选知识层

#### `knowledge_candidates`

```yaml
candidate_id: string
profile_id: l2_industry | l3_brand
layer: l2_industry | l3_brand
document_id: string
evidence_unit_id: string
source_span_ids: array
candidate_type: relation | metric | statement | event
subject: object
predicate: object optional
object: object optional
metric: object optional
statement: object optional
event: object optional
evidence_text: string
confidence: float
extraction_method: array
embedding_id: string optional
schema_valid: bool
source_status: active | expired | retracted | updated optional
created_at: datetime
```

候选知识层必须保留 `document_id`、`published_at`、`original_url`、`content_hash`、`evidence_unit_id` 和 `source_span_ids`。这不是冗余字段，而是为了支持后续来源文章失效、撤稿、更新时进行影响面追踪。

### 9.3 门禁候选知识层

门禁候选知识层位于 `knowledge_candidates` 和 `active_knowledge_graph` 之间，只存储经过跨文章处理后、准备进入 L1 门控和正式知识图谱的知识信息数据。

跨文章阶段中的融合、冲突、补充、跨实体建联是处理逻辑，不在这一层单独设计 `knowledge_conflicts`、`inferred_relations` 等过程型数据表。处理后的结果只体现为可进入门禁的实体、关系、指标、事件或论点记录。

#### `gate_candidate_entities`

```yaml
entity_id: string
profile_id: l2_industry | l3_brand
layer: l2_industry | l3_brand
entity_type: string
name: string
aliases: array optional
description: string optional
source_candidate_ids: array
evidence_refs: array
confidence: float
embedding_id: string optional
created_at: datetime
```

#### `gate_candidate_knowledge`

```yaml
knowledge_id: string
profile_id: l2_industry | l3_brand
layer: l2_industry | l3_brand
knowledge_type: relation | metric | statement | event
subject_entity_id: string
predicate_type: string optional
object_entity_id: string optional
statement_text: string optional
metric_name: string optional
metric_value: object optional
event: object optional
scope: object
time_scope: object
evidence_refs: array
source_candidate_ids: array
source_document_ids: array
latest_published_at: datetime
confidence: float
embedding_id: string optional
gate_status: pending | passed | rejected
created_at: datetime
```

## 10. 门禁与晋级

### 10.1 L2 门禁

L2 不设立来源质量和权限门禁。

L2 晋级只看 L1 中定义的 promotion policy 和抽取质量，例如：

- schema 是否符合当前 profile
- entity/relation/metric 是否属于 L1 ontology
- evidence_text 是否直接支持候选知识
- confidence 是否达到阈值
- 是否存在未解决冲突
- 是否是重复知识

### 10.2 L3 门禁

L3 不再维护独立图谱维度门禁，但保留敏感内容提醒。

L3 晋级同样读取 L1 promotion policy，额外记录：

- `sensitive_warning_status`
- `public_quote_risk`
- `user_notice_required`

建议默认策略：

```text
低风险：继续抽取，记录提醒
中风险：继续抽取，晋级前提醒用户
高风险：候选层保留，进入 review 队列
```

## 11. 代码改造建议

### 11.1 L2 runtime 改造

当前 L2 入口：

- `runtime/l2/executor.py`
- `runtime/l2/pipelines/report_ingestion.py`
- `runtime/l2/pipelines/evidence_resolution.py`
- `runtime/l2/pipelines/extraction.py`
- `runtime/l2/pipelines/source_enrichment.py`
- `runtime/l2/pipelines/promotion.py`

建议新增或重命名为：

```text
runtime/l2/pipelines/article_registration.py
runtime/l2/pipelines/content_parsing.py
runtime/l2/pipelines/evidence_unit_merge.py
runtime/l2/pipelines/candidate_extraction.py
runtime/l2/pipelines/candidate_normalization.py
runtime/l2/pipelines/candidate_vectorization.py
runtime/l2/pipelines/knowledge_fusion.py
runtime/l2/pipelines/promotion.py
```

旧的 `report_ingestion` 后续明确废弃。

L2 executor 的新 `--all` 顺序建议：

```python
ALL_ORDER = [
    "article_registration",
    "content_parsing",
    "evidence_unit_merge",
    "candidate_extraction",
    "candidate_normalization",
    "candidate_vectorization",
    "knowledge_fusion",
    "promotion",
]
```

### 11.2 L3 runtime 改造

当前 L3 入口：

- `runtime/l3/executor.py`
- `runtime/l3/pipelines/source_registration.py`
- `runtime/l3/pipelines/original_file_gate.py`
- `runtime/l3/pipelines/layout_aware_parsing.py`
- `runtime/l3/pipelines/semantic_chunking.py`
- `runtime/l3/pipelines/candidate_pre_extraction.py`
- `runtime/l3/pipelines/candidate_extraction.py`
- `runtime/l3/pipelines/entity_resolution.py`
- `runtime/l3/pipelines/assertion_classification.py`
- `runtime/l3/pipelines/evidence_verification.py`
- `runtime/l3/pipelines/review_promotion.py`

建议调整为：

```text
runtime/l3/pipelines/document_registration.py
runtime/l3/pipelines/sensitive_content_warning.py
runtime/l3/pipelines/content_parsing.py
runtime/l3/pipelines/evidence_unit_merge.py
runtime/l3/pipelines/candidate_extraction.py
runtime/l3/pipelines/candidate_normalization.py
runtime/l3/pipelines/candidate_vectorization.py
runtime/l3/pipelines/knowledge_fusion.py
runtime/l3/pipelines/promotion.py
```

其中：

- `original_file_gate.py` 不再作为质量/权限阻断门禁，应替换为 `sensitive_content_warning.py`
- `layout_aware_parsing.py` 可保留解析能力，但命名和职责建议统一到 `content_parsing.py`
- `semantic_chunking.py` 应改为 evidence span/unit 生成，不做过深语义判断
- `assertion_classification.py` 的分类规则应迁移到 L1-aware extraction 内，由 L1 `extraction_rules.yaml` 驱动
- `evidence_verification.py` 可保留，但规则来源必须改为 L1
- `entity_resolution.py` 应升级为跨文档融合的一部分，而不是只在单文档内做
```

## 12. 模型使用与成本控制

### 12.1 推荐模型分工

| 能力 | 用途 | 成本策略 |
| --- | --- | --- |
| 规则/正则 | 数值、单位、时间、标题、列表、明显关系触发词 | 全量使用 |
| NER | 实体 mention 发现 | 全量或批量使用 |
| embedding | 候选知识去重、跨文章实体归一、关系/论点相似度、冲突候选召回 | LLM 抽取候选知识后生成并复用 |
| 小 LLM | 合并边界判断、低风险结构化抽取 | 只处理不确定或命中预筛选的 unit |
| 强 LLM | 复杂抽取、冲突解释、跨文章归并、推导关系确认 | 只处理高价值候选和冲突样本 |

### 12.2 成本控制原则

```text
不要整篇文章直接进 LLM
不要所有相邻段落都问 LLM
不要一开始构建巨大词典
不要把冲突全部交给人工
不要把候选知识直接写入主图
```

推荐路线：

```text
NER 批量跑
规则/正则全量跑
映射 L1 后预筛
embedding 复用
LLM 只做结构化抽取和疑难判断
跨文章融合按候选聚类后小批量处理
```

## 13. 推荐实施阶段

### Phase 1：统一数据链路

目标：

- 建立 `document`、`evidence_span`、`evidence_unit`、`knowledge_candidate` 的统一结构
- L2 支持直接输入文章正文
- L3 支持品牌文件正文解析
- 每条候选知识都带 `document_id` 和 `evidence_unit_id`

优先改造：

- L2 去掉 md report 强依赖
- L3 去掉旧 `original_file_gate`
- 新增最小 `content_parsing`
- 新增 evidence span/unit 编号

### Phase 2：L1-aware 抽取

目标：

- L2/L3 抽取统一读取 L1 profile
- 抽取 JSON schema 受 L1 ontology 约束
- statement_class 由 L1 extraction_rules 指导
- evidence_text 必填

优先改造：

- `runtime/l1/registry.py`
- `runtime/l1/policy_engine.py`
- L2/L3 candidate extraction prompt
- schema validate

### Phase 3：跨文章融合

目标：

- 建立门禁候选实体
- 建立门禁候选 relation / metric / statement / event
- 聚合 evidence
- 标记重复、补充、冲突

优先实现：

- entity resolution
- relation alignment
- metric alignment
- conflict detection
- evidence aggregation

### Phase 4：推导关系与主动图谱

目标：

- 支持跨实体建联
- 支持 inferred relation
- 支持 evidence chain
- 通过 L1 gate 后晋级 active graph

优先实现：

- 显式关系链查询
- 简单推导规则
- inferred relation 标记
- active graph update

## 14. 最终推荐架构

```text
L1 common_knowledge
  ├── schema_profiles
  ├── ontology
  ├── extraction_rules
  └── promotion_policy

L2 industry_knowledge runtime
  ├── article_registration
  ├── content_parsing
  ├── evidence_unit_merge
  ├── candidate_extraction
  ├── candidate_vectorization
  ├── knowledge_fusion
  └── promotion

L3 brand_knowledge runtime
  ├── document_registration
  ├── sensitive_content_warning
  ├── content_parsing
  ├── evidence_unit_merge
  ├── candidate_extraction
  ├── candidate_vectorization
  ├── knowledge_fusion
  └── promotion

Storage
  ├── Evidence Graph
  ├── Candidate Knowledge Graph
  ├── Gate Candidate Knowledge
  └── Active Knowledge Graph
```

一句话总结：

```text
L1 定规则，L2/L3 跑流程；原文先变证据，证据经过 L1 预筛、NER、正则和 LLM 抽取后生成候选知识，再完成向量化与溯源入库，随后跨文章融合、冲突、补充、建联，最后通过 L1 门禁进入正式图谱。
```
