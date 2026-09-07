# Knowledge Graph 架构审查 · 执行方案

> 生成时间：2026-08-26 · 原则：**最小改动、优先修复崩溃、再处理质量**

---

## 优先级说明

| 级别 | 含义 |
|------|------|
| 🔴 Critical | 运行时崩溃 / 数据损坏，必须先修 |
| 🟠 High | 功能缺陷 / 逻辑错误，影响正确性 |
| 🟡 Medium | 代码质量 / 文档不一致 |
| 🟢 Low | 性能优化 |

---

## 🔴 Critical Bugs（必须先修，共 6 项）

### 1. `content_inventory` 插入列不匹配 → 运行时崩溃

**文件：** `legacy/brand/pipelines/sensitive_content_warning.py:88`  
**问题：** 插入列包含 `attributes`，但 `legacy/database/l2_l3_schema.sql:568` 中该表无此列；同时缺少 NOT NULL 的 `brand_id`。  
**修改：**
- 插入语句改为 `(id, tenant_id, brand_id, document_id, content_type, status)`
- 从 pipeline 上下文传入 `brand_id`；删除 `attributes` 字段插入

---

### 2. Neo4j `projection.py` 构造函数语法错误 → 模块无法导入

**文件：** `legacy/neo4j/projection.py:97`  
**问题：** `def __init__(self, uri=None, user=None, ******` — 语法非法  
**修改：** 将 `******` 替换为实际参数名 `password=None`，从环境变量读取，不硬编码

---

### 3. Embedding 鉴权 Header 为占位符 → 所有 API 请求失败

**文件：** `legacy/clients/embeddings.py:95`  
**问题：** `headers["Authorization"] = f"******"` — 无法真实鉴权  
**修改：**
```python
headers["Authorization"] = f"Bearer {self.config.api_key}"
```

---

### 4. 关系候选 `predicate.type` 丢失 → 融合/晋级数据错误

**文件：** `shared/extraction/candidate_extraction.py:83,195`  
**问题：** trigger payload 用 `{"trigger": rel}`，但 row builder 读 `payload.get("type")`，所有关系 predicate type = None  
**修改：**
```python
"candidate_payload": {"trigger": rel, "type": rel},
```

---

### 5. Fusion `source_document_ids` 写入错误数据 → 溯源语义损坏

**文件：** `legacy/fusion/fusion_service.py:141-143`  
**问题：** 将 `evidence_unit_id` 追加进 `source_document_ids`，字段语义混淆  
**修改：**
- `source_document_ids` 改为读候选的 `source_document_id` 字段
- `evidence_unit_id` 只保留在 `evidence_refs` 中，不复制到 `source_document_ids`

---

### 6. `publish_l1.py` 只输出 JSON，不写库 → 注册表为空导致 FK 失败

**文件：** `legacy/database/publish_l1.py`  
**问题：** 仅输出 JSON snapshot，未写入 `entity_type_registry` / `relation_type_registry`，但 `l2_l3_schema.sql:291,332` 有 FK 引用  
**修改：** 在 publish 末尾增加 UPSERT 写入注册表；或提供独立 seed 脚本并在文档中说明

---

## 🟠 High — 功能缺陷（共 3 项）

### 7. Promotion `gate_schema` 永远通过 → 校验失效

**文件：** `legacy/promotion/promotion_service.py:81`  
**问题：** `k.get("schema_valid", True)` 默认 True；`gate_candidate_knowledge` 表无此列  
**修改：** 在 `l2_l3_schema.sql:251-277` 增加 `schema_valid BOOLEAN DEFAULT FALSE`，抽取写库时显式赋值

---

### 8. Model Config 路径不一致 → 配置找不到

**文件：** `legacy/clients/embeddings.py:19`、`legacy/clients/ner_client.py:46`  
**问题：** 代码指向 `legacy/clients/config/`，文档说在 `legacy/config/`  
**修改：**
```python
DEFAULT_MODEL_CONFIG = Path(__file__).resolve().parents[1] / "config" / "model-config.local.json"
```

---

### 9. `claim_policy.yaml` 出现非法 `statement_class: fact_conditional`

**文件：** `common_knowledge/policies/claim_policy.yaml:216,228`  
**问题：** DB CHECK 约束只允许 `fact|claim|observation|inference`，`fact_conditional` 非法  
**修改：** 将两处 `fact_conditional` 改为 `fact` 或 `claim`（按业务语义选择）

---

## 🟡 Medium — 代码质量 / 文档（共 3 项）

### 10. 删除死代码

| 文件 | 位置 | 内容 |
|------|------|------|
| `legacy/fusion/fusion_service.py` | 108-116 | `_cand_context` 函数，未被调用 |
| `legacy/industry/pipelines/content_parsing.py` | 41 | `unit_rows = []`，赋值后未使用 |
| `legacy/brand/pipelines/content_parsing.py` | 15 | `document_provenance` 导入，未使用 |
| `legacy/industry/pipelines/evidence_unit_merge.py` | 13 | 同上 |
| `legacy/promotion/promotion_service.py` | 225 | `_resolve_or_create_entity`，定义但从未调用 |

---

### 11. 修复文档错误命令

**文件：** `docs/USAGE.md:47`  
`python -m legacy.database.publish` → 改为 `python -m legacy.database.publish_l1`

### 12. 修复文档 DSN 掩码格式

**文件：** `docs/USAGE.md:25`  
`******localhost:5432/brand_atlas` → 改为 `postgresql://user:***@localhost:5432/brand_atlas`

---

## 🟢 Low — 性能优化（共 2 项）

### 13. 向量化 pipeline 重复创建 embedding client

**文件：** `legacy/industry/pipelines/candidate_vectorization.py`、`legacy/brand/pipelines/candidate_vectorization.py`  
**修改：** 在循环外创建一次 client，循环内复用

---

### 14. 晋级去重 O(N·M) 性能问题

**文件：** `legacy/promotion/promotion_service.py:173-179`  
**修改（可推迟）：** 增加 simhash 预筛或基于 embedding cosine ANN 去重，减少 SequenceMatcher 精确比对次数

---

## 📋 需要新增的内容

| 项 | 类型 | 说明 |
|----|------|------|
| `tests/test_schema_compat.py` | 测试 | 验证 pipeline 写入列与 SQL schema 列的一致性 |
| `tests/test_config_paths.py` | 测试 | 验证 EmbeddingConfig/NERConfig 能解析到正确路径 |
| `gate_candidate_knowledge.schema_valid` 列 | Schema | 新增 `schema_valid BOOLEAN DEFAULT FALSE` |
| Fail-fast 校验 | Runtime Guard | fusion 写入前检查 predicate.type 非空；promotion 写入前检查 brand_id 存在 |

---

## 执行顺序建议

```
Step 1 → 修 Critical #1-#6      确保系统能启动并运行
Step 2 → 修 High #7-#9          确保逻辑正确
Step 3 → 清理死代码 #10          减少维护负担
Step 4 → 修文档 #11-#12         让新成员能正确启动
Step 5 → 新增测试               防止回归
Step 6 → 优化 #13-#14           按需，不急
```

> 所有修改均为**局部改动**，不涉及模块重构或接口变更。
