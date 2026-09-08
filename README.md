# Brand Atlas Knowledge Graph

Brand Atlas 是一个本地优先的知识图谱与智能助手桌面应用。文档、知识图谱、对话记录和 Agent 运行时都在本机运行；只有 LLM 和 Embedding 在配置后通过 OpenAI-compatible API 调用外部服务。

当前产品主路径是 Tauri 独立桌面应用，不要求用户打开浏览器，也不要求安装 PostgreSQL、Neo4j 或 Docker。

## 当前框架

```text
Tauri 桌面窗口
        │
        ▼
React + TypeScript 前端工作台
        │ 本机 HTTP + 会话令牌
        ▼
FastAPI Python Sidecar
        │
        ├── SQLite：文档、证据、候选、实体、关系、对话和任务
        ├── 本地文件：原始文档、缓存、日志和备份
        ├── shared：知识规则、抽取和证据解析
        └── 外部 API：LLM / Embedding（可分别启用和测试）
```

## 目录结构

```text
Knowledge_Graph/
├── backend/                         # 本地 FastAPI 后端
│   ├── main.py                      # Sidecar 入口
│   └── app/
│       ├── factory.py               # 应用组装、本地鉴权、CORS
│       ├── config.py                # 本地路径和运行配置
│       ├── routes/                  # HTTP API：对话、文档、图谱、系统
│       ├── application/             # Job、Agent、导入和知识构建用例
│       │   └── services/
│       ├── infrastructure/          # SQLite、Repository 和模型 Provider
│       │   └── providers/
│       └── migrations/              # SQLite 版本迁移
├── frontend/                        # React + TypeScript + Vite UI
│   └── src/
│       ├── app/                      # 主工作台和运行时发现
│       ├── api/                      # 后端 API 客户端和 DTO
│       ├── features/                 # 对话、导入、图谱、设置功能
│       └── styles/                   # 全局样式
├── desktop/                         # Tauri 2 独立桌面壳
│   └── src-tauri/
│       ├── src/main.rs              # 窗口、Sidecar 和生命周期
│       ├── tauri.conf.json          # 桌面构建和安装包配置
│       └── capabilities/            # Tauri 权限声明
├── shared/                          # 跨运行时复用的纯领域能力
│   ├── knowledge/                   # L1 registry、策略、协议、规则
│   ├── extraction/                  # 证据解析、候选抽取、归一化和融合
│   └── ontology/                    # Profile 本体访问和校验
├── common_knowledge/                # YAML 知识规则唯一事实源
│   ├── ontology/                    # L2/L3 实体、关系、指标
│   ├── policies/                    # 证据、冲突、上下文、晋升策略
│   ├── contracts/                   # 治理和运行协议
│   └── schema_profiles/             # Profile 和抽取规则
├── legacy/                          # 已停用的旧实现，仅作迁移参考
│   ├── database/                    # 旧 PostgreSQL Schema 和 L1 发布器
│   ├── core/                        # PG DB、知识写入服务、旧持久化适配器
│   ├── clients/                     # 旧 Embedding / NER 客户端
│   ├── industry/                    # 旧 L2 行业 Pipeline
│   ├── brand/                       # 旧 L3 品牌 Pipeline
│   ├── fusion/                      # 旧跨文档融合
│   ├── promotion/                   # 旧门禁晋升
│   ├── neo4j/                       # 旧图谱投影和一致性检查
│   ├── migrations/                  # 旧 PG 迁移执行器
│   ├── visualize/                   # 旧 PG/Neo4j 可视化导出
│   └── docker-compose.yml           # 旧 PG + Neo4j 服务
├── tests/                           # 桌面版和 shared 运行时测试
├── scripts/                         # 开发、构建和维护脚本
│   ├── dev/                          # 桌面和浏览器开发启动
│   ├── build/                        # Sidecar、图谱和安装包构建
│   └── maintenance/                 # 数据库和生成物维护
├── docs/                            # 架构、迁移和运维说明
│   ├── architecture/
│   ├── migration/
│   ├── maintenance/
│   └── decisions/
├── requirements-desktop.txt         # 桌面版依赖
└── requirements.txt                 # 历史依赖清单，不用于桌面版
```

## 依赖方向

```text
frontend → backend api → application → infrastructure → SQLite / Model API
                              │
                              └── shared（纯规则/抽取）

shared extraction → backend knowledge pipeline → SQLite
```

`shared/` 不依赖 `backend/`、PostgreSQL、Neo4j 或模型客户端。桌面版运行时也不导入
`legacy/`；这样后续新增桌面模块或存储适配器时，边界保持清晰。

## 当前知识构建链路

桌面版已经重新实现旧版的核心处理思路，但实现位于新运行时，不复用旧源码：

```text
文档 → 证据 Span/Unit → 规则候选 + 可选 LLM 候选
     → 归一化 → 候选融合/去重 → 实体解析
     → 关系生成 → SQLite 候选、实体、关系和证据引用
```

- `shared/extraction/entity_rules.py`：依赖无关的实体与关系规则。
- `shared/extraction/normalization.py`：名称归一化、候选稳定键和证据融合。
- `backend/app/application/services/knowledge_pipeline.py`：桌面版知识构建编排，可选调用 LLM。
- `backend/app/application/services/ingestion.py`：负责文档导入、幂等和事务化落库。

规则抽取、图谱构建和对话不依赖 Embedding；LLM 和 Embedding 仍可独立配置、独立测试。

## 桌面版开发启动

```powershell
pip install -r requirements-desktop.txt
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run dev
```

命令会直接打开 Tauri 独立窗口。开发阶段由脚本自动启动 Vite 和本地 FastAPI Sidecar；用户不需要访问 Web 端口。

SQLite 数据库默认保存在操作系统的用户数据目录：

```text
%LOCALAPPDATA%\BrandAtlas\database\knowledge.db
```

文档、向量、缓存、日志、备份和设置也位于 `%LOCALAPPDATA%\BrandAtlas` 下。
`BRAND_ATLAS_DATABASE_PATH` 只覆盖数据库文件，`BRAND_ATLAS_DATA_DIR` 覆盖完整
数据根目录，前者优先。Tauri 开发模式为了便于查看项目数据，会显式使用项目目录
下的 `database\knowledge.db`；发布版不会设置这个开发覆盖路径。

模型配置在桌面端设置界面中填写。LLM 和 Embedding 有独立的测试按钮；Embedding 未配置时，规则抽取、图谱构建和对话仍可以继续运行。

更详细的桌面开发说明见 [docs/architecture/LOCAL_APP.md](docs/architecture/LOCAL_APP.md)，打包说明见 [desktop/README.md](desktop/README.md)。
数据备份、数据库校验、故障排查和发布验收见 [docs/maintenance/](docs/maintenance/)。

## legacy 目录状态

`legacy/` 是已停用的历史实现，仅用于核对迁移结果和保留历史资料，不再作为产品运行时，
也不再接受功能维护。新的桌面版不需要 PostgreSQL、Neo4j、Docker 或旧版依赖；后续功能
应添加到 `backend/`、`shared/`、`frontend/` 或 `desktop/` 的新边界中。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py"
npm --prefix frontend run build
```

测试重点覆盖桌面版本地 SQLite 链路和 `shared/` 纯规则能力；仓库中保留的历史回归测试
只用于迁移期间的行为校验。构建生成的 `build/`、`dist/`、Tauri `target/` 和 Sidecar
文件属于产物，不属于核心源码。
