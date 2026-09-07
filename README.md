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
│       ├── database.py              # SQLite 连接和初始化
│       ├── repositories.py          # 数据访问层
│       ├── jobs.py                  # 导入任务管理
│       ├── routes/                  # HTTP API：对话、文档、图谱、系统
│       └── services/                # Agent、导入、LLM、Embedding 用例
├── frontend/                        # React + TypeScript + Vite UI
│   └── src/
│       ├── App.tsx                  # 主工作台和对话状态
│       ├── api.ts                   # 后端 API 客户端
│       ├── runtime.ts               # Tauri 本地运行时发现
│       └── components/              # 图谱、导入、设置等模块
├── desktop/                         # Tauri 2 独立桌面壳
│   └── src-tauri/
│       ├── src/main.rs              # 窗口、Sidecar 和生命周期
│       ├── tauri.conf.json          # 桌面构建和安装包配置
│       └── capabilities/            # Tauri 权限声明
├── shared/                          # 跨运行时复用的纯领域能力
│   ├── knowledge/                   # L1 registry、策略、协议、规则
│   ├── extraction/                  # 证据解析、候选抽取、候选行构造
│   └── ontology/                    # Profile 本体访问和校验
├── common_knowledge/                # YAML 知识规则唯一事实源
│   ├── ontology/                    # L2/L3 实体、关系、指标
│   ├── policies/                    # 证据、冲突、上下文、晋升策略
│   ├── contracts/                   # 治理和运行协议
│   └── schema_profiles/             # Profile 和抽取规则
├── legacy/                          # 旧 PostgreSQL/Neo4j 服务端运行时
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
├── tests/                           # 新桌面版和旧运行时回归测试
├── scripts/                         # 桌面开发、Sidecar 和构建脚本
├── docs/                            # 架构、启动和本地应用说明
├── requirements-desktop.txt         # 桌面版依赖
└── requirements.txt                 # legacy 旧服务端依赖
```

## 依赖方向

```text
frontend → backend routes → backend services → repositories → SQLite
                                      │
                                      └── shared（纯规则/抽取）

legacy pipelines → shared + legacy persistence → PostgreSQL / Neo4j
```

`shared/` 不依赖 `backend/`、PostgreSQL、Neo4j 或旧模型客户端。旧运行时可以依赖 `shared/`，但桌面版不会反向依赖 `legacy/`。这样后续新增桌面模块、服务器适配器或其他存储实现时，边界保持清晰。

## 桌面版开发启动

```powershell
pip install -r requirements-desktop.txt
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run dev
```

命令会直接打开 Tauri 独立窗口。开发阶段由脚本自动启动 Vite 和本地 FastAPI Sidecar；用户不需要访问 Web 端口。

本地应用数据默认保存在：

```text
%LOCALAPPDATA%\BrandAtlas
```

模型配置在桌面端设置界面中填写。LLM 和 Embedding 有独立的测试按钮；Embedding 未配置时，规则抽取、图谱构建和对话仍可以继续运行。

更详细的桌面开发说明见 [docs/LOCAL_APP.md](docs/LOCAL_APP.md)，打包说明见 [desktop/README.md](desktop/README.md)。

## legacy 旧运行时

`legacy/` 只用于兼容旧的 PostgreSQL/Neo4j 知识工程流程，不是桌面版启动必需项。若需要运行旧链路：

```powershell
pip install -r requirements.txt
cd legacy
docker compose up -d
cd ..

python -m legacy.migrations --only l1
python -m legacy.migrations --only l2_l3
python -m legacy.industry.executor --all --file <doc.md>
python -m legacy.brand.executor --all --file <doc.md> --brand <brand_id>
```

旧链路的数据定义位于 `legacy/database/`，旧图谱投影位于 `legacy/neo4j/`。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py"
npm --prefix frontend run build
```

测试同时覆盖桌面版本地 SQLite 链路、`shared/` 纯规则能力和 `legacy/` 旧运行时的兼容性。构建生成的 `build/`、`dist/`、Tauri `target/` 和 Sidecar 文件属于产物，不属于核心源码。
