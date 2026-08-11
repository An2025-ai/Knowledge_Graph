# L3 品牌认知层 — Skills 与 Tools

> **版本**: 1.0.0  
> **参照**: L3 技术文档 §15

## Skill 与 Tool 的关系

- **Skill** 是带业务规则的工作能力（可版本化的业务步骤）。
- **Tool** 是原子操作接口（可替换实现）。
- Skill 不应直接耦合某一家搜索或模型供应商。例如 `layout_aware_parser` 可先用一种 PDF 解析器，未来更换工具不改变上层数据契约。

## 逻辑 Skills

| Skill | 职责 |
|-------|------|
| brand_scope_compiler | 把用户指定品牌和需求编译为接入范围 |
| official_site_inventory | 枚举官网 URL、产品页、FAQ、案例、新闻和下载项 |
| enterprise_document_ingestion | 导入企业 PDF、Word、PPT、Markdown 和 Excel |
| layout_aware_parser | 保留页码、标题、表格和图示关系 |
| brand_entity_extraction | 按 Profile 抽取品牌、产品、版本和内容实体 |
| capability_l2_mapper | 把品牌功能映射到 L2 标准能力 |
| assertion_classifier | 判定 fact、claim、observation 和 inference |
| evidence_verifier | 验证 Evidence Span 是否直接支持陈述 |
| entity_resolution | 品牌、组织、产品、别名和版本消歧 |
| claim_governance | 管理 Approved、Restricted 和 Prohibited Claims |
| brand_graph_publisher | 审核后写 PostgreSQL 并投影 Neo4j |
| brand_change_monitor | 官网和文档版本变化检测 |

## Tools

| 类别 | 推荐工具能力 |
|------|-------------|
| 官网采集 | Playwright、站点地图解析、robots/限速、HTML 快照和 DOM Diff |
| 文档解析 | PDF 文本与渲染、OCR、DOCX/PPTX/XLSX 结构解析 |
| 原件存储 | S3/MinIO/对象存储、SHA-256 和版本清单 |
| 结构化抽取 | 支持 JSON Schema/Structured Output 的 LLM |
| 数据质量 | JSON Schema、SHACL 风格约束、规则引擎和人工审核台 |
| 主存储 | PostgreSQL、RLS、JSONB 和事务迁移 |
| 图分析 | Neo4j 和参数化 Cypher |
| 调度 | Airflow、Dagster、Temporal 或现有任务系统 |
| 观测 | OpenTelemetry、任务日志、抽取模型和 Prompt 版本记录 |
| 安全 | 病毒扫描、DLP、密钥管理、访问审计和脱敏 |
