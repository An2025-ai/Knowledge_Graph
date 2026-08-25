# L1 设计与使用说明

## 1. 定位

L1 是本体定义与治理层。它分别保存 L2 行业本体和 L3 品牌本体，并定义知识如何被校验、
检索和更新。L1 不提供共享业务实体或共享业务关系；同名代码只在所属 Profile 内解析。

L1 不保存行业事实、品牌事实、AI 回答分析结果或文章优化结果。L2 与 L3 不继承彼此、
不建立跨层关系，也不允许指标依赖另一层。L4 暂不定义，待反馈层边界确定后再新增。

## 2. L1 文件

| 目录/文件 | 维度 | 用途 |
|---|---|---|
| `ontology/l2_industry/entities.yaml` | L2 实体类型 | 定义 41 种行业构图实体 |
| `ontology/l2_industry/relations.yaml` | L2 关系类型 | 定义 37 种行业内部关系及 domain/range |
| `ontology/l2_industry/metrics.yaml` | L2 指标 | 定义 24 项行业指标及计算上下文 |
| `ontology/l3_brand/entities.yaml` | L3 实体类型 | 定义 44 种品牌构图实体 |
| `ontology/l3_brand/relations.yaml` | L3 关系类型 | 定义 43 种品牌内部关系及 domain/range |
| `ontology/l3_brand/metrics.yaml` | L3 指标 | 定义 19 项只依赖品牌资料的指标 |
| `contracts/governance.yaml` | 治理定义 | 合并陈述类型、上下文类型和构图质量指标 |
| `contracts/protocols.yaml` | 运行协议 | 合并 LLM 操作、检索上下文和更新协议 |
| `schema_profiles/extraction_rules.yaml` | 抽取规则 | 定义 L2/L3 同名语义差异、叙事链和 prompt 规则 |
| `schema_profiles/l2_industry_profile.yaml` | L2 Profile | 只引用 L2 的三份本体文件 |
| `schema_profiles/l3_brand_profile.yaml` | L3 Profile | 只引用 L3 的三份本体文件 |
| `policies/*.yaml` | 治理策略 | 证据、冲突、来源、生命周期和晋升规则 |

## 3. 核心维度

### 3.1 实体类型

实体类型是层内业务概念约束。L2 和 L3 各自完整定义，即使代码同名也没有继承关系。
`metric`、`evidence`、`content`、`source`、`source_domain`、`fact`、`claim`、
`observation` 和 `prompt` 都不是构图实体；指标在本层 `metrics.yaml` 中定义，证据和陈述
属于运行时记录。

API：

```powershell
python -m runtime.common.entity_types --profile l2_industry
python -m runtime.common.entity_types --profile l3_brand
```

### 3.2 关系类型

关系类型只定义本层对象之间的连接。关系验证同时检查 Profile、类型、方向、基数、
置信度和证据要求；不存在 L2 到 L3 或 L3 到 L2 的关系。

API：

```powershell
python -m runtime.common.relation_types --profile l2_industry
python -m runtime.common.relation_types --profile l3_brand
```

Profile 和治理策略也分别提供 API，避免调用方直接读取 YAML：

```powershell
python -m runtime.common.profiles
python -m runtime.common.policies
```

### 3.3 陈述类型

| 类型 | 含义 | 证据 | 可否直接变成 active |
|---|---|---|---|
| `fact` | 可验证事实 | 必须有来源 | 条件允许 |
| `claim` | 主体主张或自述 | 必须保留来源和主体 | 不允许 |
| `observation` | 有时间边界的资料快照 | 必须有有效时间 | 不允许 |
| `inference` | 基于多个陈述的推断 | 必须引用支持陈述 | 不允许 |

API：

```powershell
python -m runtime.common.assertion_types
```

### 3.4 上下文

上下文保证知识不是脱离条件的孤立文本。当前定义：`valid_time`、`geography`、`language`、
`industry_scope`、`brand_scope`、`product_version`、`audience`、`source_scope`。

API：

```powershell
python -m runtime.common.contexts
```

### 3.5 LLM 操作

LLM 不直接写 active 知识。操作协议将能力拆开，每个操作单独定义输入、输出和写入模式：

| 操作 | 写入模式 | 用途 |
|---|---|---|
| `extract_knowledge` | candidate | 从资料提取实体、关系、陈述和证据引用 |
| `classify_assertion` | candidate | 判断事实、主张、观测或推断 |
| `resolve_entity` | candidate | 消歧和归并实体 |
| `validate_relation` | read-only | 检查关系是否合法 |
| `detect_conflict` | candidate | 发现冲突并给出理由 |
| `propose_update` | proposal | 生成 L1/L2/L3 变更提案 |
| `retrieve_context` | read-only | 构建给 LLM 的上下文包 |

API：

```powershell
python -m runtime.common.operations
```

### 3.6 检索上下文

使用 `runtime.common.retrieval.build_context_package()` 生成统一上下文，包含：查询、范围、实体、
关系、陈述、证据、冲突、缺失信息和检索轨迹。LLM 应消费这个结构，而不是直接读取数据库表。

### 3.7 更新提案

更新流程：

```text
draft -> validated -> benchmarked -> approved -> published
                                      └───────> rejected
```

LLM 和未来 L4 只能创建 `candidate_assertion` 或 `change_proposal`。已发布的 L1 定义不得被
无版本覆盖；发布变更必须有证据、回放结果和回滚方案。

API：

```powershell
python -m runtime.common.change_proposals proposal.json
python -m runtime.common.validate
```

## 4. 构图质量指标

这些指标只衡量知识图谱构建质量，不衡量外部平台表现：

| 指标 | 用途 |
|---|---|
| `entity_resolution_accuracy` | 实体提及正确归并的比例 |
| `relation_validity_rate` | 抽取关系满足 domain/range 的比例 |
| `evidence_coverage` | 事实和主张带可追溯证据的比例 |
| `conflict_detection_rate` | 已知冲突被识别并记录的比例 |
| `duplicate_rate` | 重复实体或陈述的比例 |
| `stale_detection_rate` | 过期知识被及时发现的比例 |
| `promotion_acceptance_rate` | 候选知识通过治理门禁的比例 |
| `retrieval_grounding_rate` | LLM 输出引用检索知识和证据的比例 |

API：

```powershell
python -m runtime.common.quality_metrics
```

## 5. 校验和发布顺序

```text
1. 修改单个 L1 定义文件
2. python -m runtime.common.validate
3. python database/publish.py --validate
4. python -m pytest -q
5. 运行样本回放和兼容性检查
6. 发布 L1 注册表
```

L1 注册表数据库结构位于 `database/l1_registry.sql`，与 L2/L3 事实表独立。生成确定性注册快照：

```powershell
python database/publish_l1.py --out runtime/common/output/registry.json
```
