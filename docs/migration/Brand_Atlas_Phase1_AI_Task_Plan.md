# Brand Atlas 第一阶段修改框架与 AI 执行任务书

> 适用项目：`An2025-ai/Knowledge_Graph`  
> 文档目标：指导 AI 编程助手分批完成新版桌面运行基础的加固。  
> 核心原则：一次只执行一个任务；每个任务独立验证、独立提交、完成后停止。

## 1. 当前阶段的目标

Brand Atlas 当前同时保留两套系统：

- `legacy/`：旧版 PostgreSQL + Neo4j 知识生产与治理后台；
- 新版：Tauri + React + FastAPI Sidecar + SQLite 本地桌面应用。

第一阶段不迁移旧版完整治理系统，也不引入 PostgreSQL、Neo4j、Docker、Qdrant 或新的微服务。第一阶段只解决新版桌面应用的运行基础问题，使它具备以下性质：

1. 安装后数据存放在稳定、可写、可备份的位置；
2. 用户修改模型设置后，不重启应用也能影响聊天、抽取和 Embedding；
3. SQLite Schema 可以按版本可靠升级；
4. 文档重新处理后不会残留已经失效的关系或陈述；
5. 所有改动均有自动化测试和明确的运维文档。

完成第一阶段之后，才能进入“混合检索”和“候选—审核—晋升”迁移。

## 2. 交给 AI 的总执行协议

将下面这段内容与具体任务一起交给 AI：

```text
你正在维护 Brand Atlas。请严格遵守以下执行协议：

1. 本轮只能执行用户指定的一个任务编号，不得提前执行后续任务。
2. 修改前先阅读任务列出的文件及仓库中的 AGENTS.md（如果存在）。
3. 先用文字说明现状、拟修改文件和测试方法，再开始修改。
4. 采用最小改动，不做与当前任务无关的重构、改名、格式化或依赖升级。
5. 不得从 legacy/ 导入运行时代码；可以参考旧版行为，但新版必须独立实现。
6. 不得引入 PostgreSQL、Neo4j、Docker、Qdrant或新的常驻进程。
7. 不得破坏 common_knowledge/ 和 shared/ 的纯领域边界。
8. 必须添加或更新自动化测试；测试失败时先查明原因，不得删除测试绕过问题。
9. 完成后输出：修改摘要、变更文件、测试结果、已知风险、下一任务建议。
10. 汇报完成后立即停止，等待用户确认；不得继续执行下一任务。
```

建议每个任务单独建立分支或提交：

```text
phase1/task-01-baseline
phase1/task-02-data-path
phase1/task-03-runtime-settings
phase1/task-04-schema-migrations
phase1/task-05-reprocess-consistency
phase1/task-06-operations-docs
```

## 3. 第一阶段范围边界

### 3.1 本阶段允许修改

- `backend/app/config.py`
- `backend/app/infrastructure/database.py`
- `backend/app/factory.py`
- `backend/app/infrastructure/repositories.py`
- `backend/app/application/services/`
- `backend/app/routes/system.py`
- `desktop/src-tauri/src/main.rs`
- `tests/`
- `scripts/`
- `docs/`
- README 中与实际运行路径、开发命令和维护方式有关的内容

### 3.2 本阶段禁止修改

- 不迁移 `legacy/promotion/`、`legacy/fusion/` 或 Neo4j 投影；
- 不设计审核队列和冲突治理页面；
- 不实现向量检索、Rerank 或 GraphRAG；
- 不大规模重写前端；
- 不一次性移动全部目录；
- 不删除 `legacy/`；
- 不修改 L1/L2/L3 业务本体，除非现有测试证明其定义错误；
- 不为了“架构整洁”引入仓储基类、依赖注入框架或微服务。

## 4. 分步任务

每个任务都必须在上一个任务验收并得到用户确认后才能开始。

---

## Task 01：建立修改基线

### 目标

先记录当前系统真实状态，避免后续把环境缺依赖误判为代码问题，也避免修改后无法判断是否回归。

### 需要检查的文件

- `README.md`
- `requirements-desktop.txt`
- `backend/app/config.py`
- `backend/app/infrastructure/database.py`
- `backend/app/factory.py`
- `desktop/src-tauri/src/main.rs`
- `scripts/build/build-sidecar.ps1`
- `tests/test_local_app.py`
- `tests/test_runtime_regressions.py`

### 执行内容

1. 使用 `requirements-desktop.txt` 准备新版测试环境；
2. 运行全部 Python 测试；
3. 运行前端 TypeScript/Vite 构建；
4. 若 Windows/Tauri 环境可用，运行 `cargo check`；
5. 新增 `docs/maintenance/BASELINE.md`，记录：
   - Python、Node、npm、Rust 版本；
   - 测试数量和结果；
   - 前端构建结果；
   - 当前默认数据库路径；
   - 当前开发启动链路和打包链路；
   - 无法在当前环境验证的项目。

### 禁止事项

- 本任务不修复业务代码；
- 不因为测试依赖缺失而修改测试；
- 不升级依赖版本；
- 不重排目录。

### 验收标准

- 新增基线文档；
- 所有可以运行的检查均有明确结果；
- 失败项区分为代码失败、依赖缺失和平台限制；
- 除文档外没有产品代码变化。

### 完成后停止

AI 应汇报基线结果，等待用户明确指示“执行 Task 02”。

---

## Task 02：修复桌面数据持久化路径

### 目标

确保开发版、PyInstaller Sidecar 和 Tauri 安装版都将用户数据写入稳定且可写的位置，应用升级或退出后数据库不会丢失。

### 当前风险

`backend/app/config.py` 在没有环境变量时，数据库默认指向项目目录。PyInstaller `--onefile` 运行时的源码目录可能是临时解压目录，不应作为用户数据库目录。

### 设计要求

生产环境统一使用：

```text
%LOCALAPPDATA%\BrandAtlas\
├── database\knowledge.db
├── documents\
├── vectors\
├── cache\
├── logs\
├── backups\
└── config\settings.json
```

其他系统继续使用各自标准用户数据目录。路径优先级固定为：

1. `BRAND_ATLAS_DATABASE_PATH`：只覆盖数据库文件；
2. `BRAND_ATLAS_DATA_DIR`：覆盖完整数据根目录；
3. 操作系统默认用户数据目录。

项目目录数据库只能由开发脚本显式指定，不能再作为生产默认值。

### 建议修改文件

- `backend/app/config.py`
- `desktop/src-tauri/src/main.rs`（仅在需要显式传递数据目录时修改）
- `scripts/dev/dev-desktop.ps1` 或相应开发脚本
- `README.md`
- `docs/architecture/LOCAL_APP.md`
- `desktop/README.md`
- `tests/test_config_paths.py` 或新增 `tests/test_app_paths.py`

### 测试要求

至少覆盖：

1. 未设置环境变量时，数据库位于用户数据根目录；
2. 设置 `BRAND_ATLAS_DATA_DIR` 时，全部路径在指定根目录下；
3. 设置 `BRAND_ATLAS_DATABASE_PATH` 时，只覆盖数据库位置；
4. `AppPaths.ensure()` 会创建必要目录；
5. 路径计算不依赖 `__file__` 所在的 PyInstaller 临时目录；
6. 测试不得真实写入用户的 `%LOCALAPPDATA%`。

### 验收标准

- 打包运行时不使用项目目录或临时解压目录保存数据库；
- README 与代码行为一致；
- 新增路径测试通过；
- 原有测试和前端构建不回归。

### 完成后停止

AI 应说明开发环境数据库位置是否发生变化，以及旧开发数据库如何手动迁移，但不要在本任务中自动移动用户数据。

---

## Task 03：统一运行时设置并支持热更新

### 目标

用户在设置界面保存 LLM 或 Embedding 配置后，无需重启，聊天、知识抽取和向量生成都使用同一份最新设置。

### 当前风险

应用启动时分别把 `RuntimeSettings` 传给 Agent、Ingestion、KnowledgeBuildPipeline 和 EmbeddingService。设置接口目前只更新 Agent 所持有的配置，其他长生命周期服务可能继续使用旧配置。

### 推荐方案

新增轻量的 `SettingsStore` 或 `RuntimeContext`，负责：

- 返回当前不可变 `RuntimeSettings` 快照；
- 原子替换非敏感设置；
- 持久化设置；
- 由各服务在每次用例开始时读取当前快照。

不要引入第三方依赖注入框架，也不要使用可在任意位置修改的全局变量。

### 建议修改文件

- 新增 `backend/app/runtime_settings.py`，或在 `config.py` 中增加职责清晰的小型 Store；
- `backend/app/factory.py`
- `backend/app/routes/system.py`
- `backend/app/application/services/agent.py`
- `backend/app/application/services/ingestion.py`
- `backend/app/application/services/knowledge_pipeline.py`
- `backend/app/infrastructure/providers/embedding.py`
- `tests/test_local_app.py`

### 额外约束

- API Key 继续保存在系统 Keyring，不写入 `settings.json`；
- 本任务暂不支持 LLM 和 Embedding 使用不同 API Key；可记录为后续需求；
- 保存失败时，内存设置和磁盘设置不能出现半更新状态；
- 测试中不得调用真实外部模型。

### 测试要求

至少覆盖：

1. 应用启动时 LLM 为 `none`；
2. 通过设置接口切换为 OpenAI-compatible；
3. 不重启应用，随后导入文档；
4. Mock 证明 KnowledgeBuildPipeline 读取了新配置；
5. Mock 证明 EmbeddingService 读取了新配置；
6. Agent 同样读取新配置；
7. `settings.json` 中不包含 API Key 明文。

### 验收标准

- 设置只有一个运行时事实源；
- 所有模型相关服务不再长期缓存过期配置；
- 热更新集成测试通过；
- 原有接口响应结构尽量保持兼容。

### 完成后停止

AI 应汇报设置对象的生命周期和线程安全边界，等待用户确认 Task 04。

---

## Task 04：建立正式的 SQLite Schema 迁移机制

### 目标

替换散落在 `LocalDatabase.initialize()` 中的临时 `ALTER TABLE`，让已安装用户可以安全升级数据库。

### 推荐目录

```text
backend/app/migrations/
├── __init__.py
├── runner.py
└── versions/
    ├── 0001_initial.sql
    └── 0002_runtime_fields.sql
```

如果直接移动当前完整 Schema 风险过大，可保留 `schema.sql` 作为新库快照，并先从后续版本开始建立迁移文件。但必须明确：

- 新数据库如何初始化；
- 旧数据库如何升级；
- `schema_versions` 保存的是哪些版本；
- 每个迁移是否在事务中执行；
- 迁移失败后是否回滚；
- 重复启动是否幂等。

### 建议修改文件

- `backend/app/infrastructure/database.py`
- `backend/app/schema.sql`
- 新增 `backend/app/migrations/`
- 新增 `tests/test_database_migrations.py`
- `docs/maintenance/DATABASE.md`

### 迁移规则

1. 已发布的迁移文件不得修改；
2. Schema 变化必须新建递增版本；
3. 迁移按编号排序；
4. 一次迁移对应一个明确目的；
5. 应用启动前完成迁移，失败则停止 Sidecar；
6. 禁止捕获迁移异常后继续运行；
7. 迁移前后不能自动删除用户数据库；
8. 破坏性迁移必须先产生备份，第一阶段原则上不做破坏性迁移。

### 测试要求

至少覆盖：

- 空数据库初始化；
- 模拟旧版数据库升级；
- 连续初始化两次结果一致；
- 中间迁移失败时事务回滚；
- 未知的未来版本应拒绝启动，而不是降级覆盖；
- `schema_versions` 顺序与实际文件一致。

### 验收标准

- `LocalDatabase.initialize()` 不再硬编码逐列补丁；
- 新旧数据库均可启动；
- 迁移行为有文档；
- 所有测试通过。

### 完成后停止

AI 应列出当前数据库版本和新增迁移版本，不得继续修改业务表模型。

---

## Task 05：保证文档重新处理的一致性

### 目标

同一文档重新抽取后，旧的证据、候选、关系和陈述不会残留；其他文档提供的知识不能被误删。

### 当前风险

`save_bundle()` 会清理部分文档级数据，但没有先完整定义“哪些图谱数据属于本次文档输出”。如果某次重新抽取不再产生旧关系，旧关系可能继续存在。

### 本任务首先要定义所有权

采用以下最小规则：

- `evidence_spans`、`evidence_units`、`knowledge_candidates`、`statements` 由 `document_id` 所有；
- `relations` 当前同样按 `document_id` 所有；
- `entities` 可以被多文档共享，不因单份文档重处理直接删除；
- 实体的来源不能只有一个会被覆盖的 `source_document_id`；第一阶段至少保证不会产生错误来源，完整的 `entity_mentions` 可放到第二阶段。

### 建议修改文件

- `backend/app/infrastructure/repositories.py`
- `backend/app/application/services/ingestion.py`
- 必要时新增一个 Schema 迁移；
- `tests/test_local_app.py`
- 新增 `tests/test_reprocessing.py`

### 推荐事务顺序

在同一个事务中：

1. Upsert 文档元数据；
2. 删除该文档原有 relations；
3. 删除该文档原有 statements；
4. 删除该文档原有 candidates、units、spans；
5. 写入新的 spans、units、candidates；
6. Upsert 实体；
7. 写入新的 relations、statements；
8. 提交事务。

任何一步失败必须整体回滚。

### 测试场景

1. 第一次处理文档产生实体 A、B 和关系 R；
2. 第二次处理同一文档只产生实体 A，不再产生 R；
3. 验证旧关系 R 被移除；
4. 验证另一个文档的关系没有被删除；
5. 模拟写入中途异常，验证旧版本仍完整存在；
6. 连续执行相同输入，行数不增长；
7. 更新实体时不丢失其他文档的来源信息。

### 验收标准

- 文档级重处理具有替换语义；
- 不残留旧关系；
- 不误删共享实体或其他文档数据；
- 重处理失败可完整回滚；
- 幂等测试通过。

### 完成后停止

AI 应明确说明实体来源的临时处理方式及第二阶段需要补充的结构化来源表。

---

## Task 06：补齐基础运维能力和文档

### 目标

让后续维护者知道数据在哪里、怎样备份、怎样恢复、怎样查看版本和怎样排查启动失败。

### 本任务内容

新增或完善：

```text
docs/maintenance/
├── BASELINE.md
├── DATABASE.md
├── BACKUP_AND_RESTORE.md
├── TROUBLESHOOTING.md
└── RELEASE_CHECKLIST.md
```

增加最小维护脚本：

```text
scripts/maintenance/
├── backup_database.py
├── verify_database.py
└── show_runtime_paths.py
```

### 脚本约束

- 只使用 Python 标准库和项目已有依赖；
- 备份 SQLite 时使用 SQLite Backup API，不能在数据库运行中直接复制主文件；
- 不自动删除旧备份；
- 恢复属于可能覆盖数据的操作，本阶段只写清流程；若实现恢复命令，必须要求显式目标和二次确认；
- 日志和输出不得包含 API Key、Bearer Token 或完整敏感文档内容。

### Release Checklist 至少包含

- Python 测试；
- 前端构建；
- Rust `cargo check`；
- Sidecar 构建；
- Tauri/NSIS 打包；
- 新安装启动；
- 旧数据库升级；
- 数据重启后仍存在；
- 设置修改后立即生效；
- 导入和重新处理；
- 备份可读取；
- 密钥未进入安装包、配置文件和日志。

### 验收标准

- 新维护者只阅读 `docs/maintenance/` 即可定位数据和完成基础排障；
- 备份与数据库校验脚本有测试；
- README 链接到维护文档；
- 文档命令与当前实现一致。

### 完成后停止

第一阶段到此结束。不要自动开始第二阶段。

## 5. 项目目录逻辑

### 5.1 推荐的长期目标结构

```text
Knowledge_Graph/
├── backend/                         # Python Sidecar：唯一后端进程
│   ├── main.py                      # 进程入口，只负责参数与启动
│   └── app/
│       ├── factory.py               # Composition Root：组装依赖
│       ├── config.py                # 路径与静态配置定义
│       ├── runtime_settings.py      # 运行期设置事实源
│       ├── api/                     # HTTP 传输层
│       │   ├── schemas.py
│       │   └── routes/
│       │       ├── agent.py
│       │       ├── documents.py
│       │       ├── graph.py
│       │       └── system.py
│       ├── application/             # 用例编排，不直接写 SQL
│       │   ├── jobs.py
│       │   └── services/
│       │       ├── agent.py
│       │       ├── ingestion.py
│       │       ├── knowledge_pipeline.py
│       │       └── retrieval.py
│       ├── infrastructure/          # 技术实现，可替换边界
│       │   ├── database.py
│       │   ├── repositories.py
│       │   ├── filesystem.py
│       │   └── providers/
│       │       ├── llm.py
│       │       └── embedding.py
│       └── migrations/              # SQLite 不可变版本迁移
│           ├── runner.py
│           └── versions/
├── shared/                          # 无数据库、HTTP、供应商依赖的知识领域内核
│   ├── extraction/                  # 证据解析、候选抽取、归一化
│   ├── knowledge/                   # 类型、策略、Profile、验证
│   └── ontology/                    # 本体读取与校验
├── common_knowledge/                # YAML 规则唯一事实源
│   ├── contracts/
│   ├── policies/
│   ├── schema_profiles/
│   ├── sources/
│   └── tasks/
├── frontend/                        # React 界面
│   └── src/
│       ├── app/                     # 应用入口和全局状态
│       ├── api/                     # 后端客户端与 DTO
│       ├── features/                # 按产品能力组织
│       │   ├── agent/
│       │   ├── documents/
│       │   ├── graph/
│       │   ├── review/
│       │   └── settings/
│       ├── components/              # 真正跨功能复用的组件
│       └── styles/
├── desktop/                         # Tauri 壳和 Sidecar 生命周期
│   └── src-tauri/
├── legacy/                          # 旧实现，只读参考，不进入新版运行时
├── tests/
│   ├── unit/                        # 纯函数和领域规则
│   ├── integration/                 # SQLite、Repository、API
│   ├── regression/                  # 旧版行为兼容样例
│   └── fixtures/                    # 固定文档和预期结果
├── scripts/
│   ├── dev/                         # 开发启动
│   ├── build/                       # Sidecar 与安装包构建
│   └── maintenance/                 # 备份、校验、路径诊断
├── docs/
│   ├── architecture/                # 当前架构和数据流
│   ├── decisions/                   # ADR 架构决策记录
│   ├── maintenance/                 # 运维、备份、排障、发布
│   └── migration/                   # 旧版能力迁移计划
├── requirements-desktop.txt
└── README.md
```

### 5.2 目录职责规则

| 目录 | 可以依赖 | 禁止依赖 |
|---|---|---|
| `common_knowledge/` | 无代码依赖 | Python 运行时、数据库、HTTP |
| `shared/` | `common_knowledge/`、轻量校验库 | `backend/`、`legacy/`、数据库客户端、模型客户端 |
| `backend/app/application/` | `shared/`、抽象 Repository/Provider | FastAPI Request、具体 SQL |
| `backend/app/infrastructure/` | SQLite、文件系统、外部模型 API | 前端、Tauri |
| `backend/app/routes/` | Application 用例、Pydantic | SQL 和知识抽取细节 |
| `frontend/` | HTTP API 契约 | Python 内部模块、SQLite |
| `desktop/` | 前端产物、Sidecar 可执行文件 | 业务抽取和知识规则 |
| `legacy/` | `shared/`（迁移核对期间） | 新版 `backend/` 运行时代码 |

依赖方向必须保持：

```text
frontend → backend api → application → shared
                              │
                              └→ infrastructure → SQLite / LLM / Embedding

desktop → 管理 frontend 窗口与 backend Sidecar 生命周期
legacy  → 只作为行为参考，不进入上述运行链
```

### 5.3 目录调整策略

第一阶段不要直接把现有文件全部移动到目标目录。建议：

1. Task 01—06 保持现有物理结构，以功能修复为主；
2. 第一阶段完成并发布一个稳定版本；
3. 另建“目录整理阶段”；
4. 每次只移动一个边界，例如先移动 routes，再移动 providers；
5. 每次移动只调整 import 和测试，不夹带业务修改；
6. 使用兼容导入或小步提交，保证每一步都能启动和回滚。

## 6. 运维与管理约定

### 6.1 配置分类

| 配置类型 | 保存位置 | 示例 |
|---|---|---|
| 非敏感用户设置 | `config/settings.json` | Base URL、模型名、Provider |
| 敏感密钥 | 系统 Keyring | API Key |
| 进程临时信息 | Tauri 与 Sidecar 启动参数 | 本地端口、会话 Token |
| 领域规则 | `common_knowledge/*.yaml` | 实体类型、关系、晋升策略 |
| 开发覆盖项 | 环境变量 | 测试数据目录、调试端口 |

不得把 API Key 写入 YAML、SQLite、日志、前端环境变量或 Git 仓库。

### 6.2 日志约定

后续日志至少区分：

- `app.log`：启动、退出、配置加载；
- `pipeline.log`：文档任务、阶段、耗时、结果数量；
- `error.log`：异常摘要和可诊断堆栈。

日志应记录 `job_id`、`document_id` 和阶段，但不得记录完整文档正文、API Key 或 Bearer Token。

### 6.3 数据库约定

- 所有写入经过 Repository；
- 多表写入必须使用事务；
- API Route 不直接写 SQL；
- Schema 修改必须新增迁移；
- 用户正式知识数据禁止由测试写入默认数据库；
- 测试统一使用临时目录；
- 数据删除和恢复操作必须有清晰目标，不接受模糊路径。

### 6.4 发布约定

- 应用版本、数据库版本和知识规则版本分别管理；
- Release 前必须执行 `RELEASE_CHECKLIST.md`；
- 安装包升级不得覆盖用户数据目录；
- 新版本首次启动先完成数据库迁移，再开放 API；
- 迁移失败必须阻止继续写入，并向用户显示可操作错误；
- `legacy/` 的变更不应进入桌面版依赖与安装包。

### 6.5 架构决策记录

建议在 `docs/decisions/` 使用简短 ADR：

```text
0001-local-first-sqlite.md
0002-python-sidecar.md
0003-no-neo4j-in-desktop.md
0004-settings-and-secret-storage.md
0005-schema-migration-policy.md
```

每份 ADR 只需包含：背景、决定、理由、后果、替代方案。这样后续 AI 不会反复推翻已经确认的技术选型。

## 7. 第一阶段完成定义

只有同时满足以下条件，第一阶段才算完成：

- [ ] 六个任务均分别完成和验收；
- [ ] 安装版数据保存在稳定用户目录；
- [ ] 应用重启后数据仍存在；
- [ ] 模型设置不重启即可生效；
- [ ] SQLite 有正式版本迁移机制；
- [ ] 文档重处理不会残留旧关系；
- [ ] 测试不接触用户真实数据库；
- [ ] 数据库可安全备份和校验；
- [ ] README、维护文档与代码一致；
- [ ] 未引入旧版运行时和额外基础设施。

## 8. 下一阶段预告（本阶段禁止执行）

第二阶段建议依次处理：

1. SQLite FTS5 全文检索；
2. Embedding 向量召回；
3. FTS + 向量的混合排序；
4. 证据级引用和文档定位；
5. Candidate → Gate → Review → Assertion；
6. 跨文档融合与冲突检测；
7. 审核工作台；
8. 图谱交互升级。

在第一阶段验收前，AI 不得以“顺便完善”为由实现以上内容。

## 9. 首次下发给 AI 的推荐指令

```text
请阅读《Brand Atlas 第一阶段修改框架与 AI 执行任务书》并执行 Task 01：建立修改基线。

本轮只允许执行 Task 01。不要修复产品代码，不要执行 Task 02，不要调整目录。完成基线文档和检查后，向我汇报结果并停止，等待我的下一条指令。
```
