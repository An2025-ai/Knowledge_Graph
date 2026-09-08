# ADR 0006：项目目录布局与模块边界

- 状态：Accepted for the R1 skeleton
- 日期：2026-09-08
- 范围：Brand Atlas 桌面版运行时、前端和维护工具

## 背景

Brand Atlas 当前已经是可运行的桌面版：Tauri 管理窗口，React 提供界面，
FastAPI Python Sidecar 提供本机 API，SQLite 保存本地数据，`shared/` 提供规则和
抽取能力。Phase 1 保持了原有物理结构以降低风险。随着功能增加，需要先建立目标
目录边界，再按边界逐步迁移现有模块。

## 决策

采用模块化单体（modular monolith）作为长期结构。后端仍然是一个可部署的
FastAPI Sidecar，内部按 API、Application、Infrastructure 和领域能力划分；前端按
产品功能组织；`shared/` 和 `common_knowledge/` 保持独立边界；`legacy/` 只作为
只读行为参考。

本轮 R1 只建立目录骨架和包初始化文件，不移动现有实现、不修改 import。后续迁移
必须以独立的小步提交完成。

## 为什么采用模块化单体

Brand Atlas 是本地优先的单用户桌面应用。模块化单体可以在一个进程边界内保持较低
的部署、升级和排障成本，同时用清晰的模块边界降低耦合。新增 Agent、文档、图谱或
设置能力时，可以在模块内部演进，并通过明确的应用服务和适配器连接外部实现，避免
过早拆分微服务带来的网络、进程和发布复杂度。

## 为什么 FastAPI Sidecar 是唯一后端进程

Tauri 是桌面壳，负责窗口和 Sidecar 生命周期；React 前端只通过本机 API 访问后端。
FastAPI Sidecar 统一负责 SQLite、文件系统、知识构建、Agent 运行时以及外部模型
调用。单一后端进程可以统一鉴权、数据库连接、迁移、日志和退出清理，避免多个后端
进程竞争同一个 SQLite 文件，也避免把业务逻辑复制到 Tauri 或前端中。

这不意味着所有代码都放在一个模块里：进程是单一的，内部依赖方向仍必须保持清晰。

## `shared/` 的纯领域边界

`shared/` 保存证据解析、候选抽取、归一化、本体和知识策略等可复用领域能力。它可以
读取 `common_knowledge/` 中的规则，但不能依赖 `backend/`、HTTP、SQLite、文件系统
服务或具体模型客户端。这样规则可以在单元测试、导入流水线和未来其他运行时中复用，
且不会因为更换存储或供应商而改变领域逻辑。

`common_knowledge/` 是 YAML 规则的事实源，不承载 Python 运行时代码。

## `legacy/` 的只读参考边界

`legacy/` 保留旧系统的实现、Schema 和历史资料，仅用于核对旧版行为、迁移结果和
兼容性样例。新版不得从 `legacy/` 导入运行时代码，也不把旧版数据库或常驻服务重新
引入桌面产品。需要兼容旧行为时，在新版 `shared/` 或后端边界内重新实现，并用测试
固定期望行为。

## API、Application、Infrastructure 的职责

依赖方向为：

```text
frontend → API → Application → shared
                       │
                       └→ Infrastructure → SQLite / 文件系统 / 外部模型 API
```

- `backend/app/routes/`：HTTP 路由、请求/响应 DTO、鉴权和协议适配。它不直接写 SQL，
  也不实现知识抽取细节。
- `backend/app/application/`：面向用户用例的编排和服务接口。它协调领域能力、
  Repository 与 Provider 抽象，不绑定 FastAPI Request，也不把具体 SQL 塞进用例。
- `backend/app/infrastructure/`：技术适配器，包括 SQLite、文件系统、LLM 和
  Embedding Provider。它可以依赖具体库，但不能反向依赖前端或 Tauri。
- `shared/`：无数据库、HTTP 和供应商依赖的纯领域内核。
- `frontend/`：只依赖稳定的 HTTP API 契约，不导入 Python 内部模块或 SQLite。
- `desktop/`：只负责桌面窗口、前端产物和 Sidecar 生命周期，不承载业务抽取规则。

当前 HTTP 路由实现仍位于 `backend/app/routes/`；Application 和 Infrastructure 已按
目标职责分别位于 `backend/app/application/` 与 `backend/app/infrastructure/`。R8
已清理 `services/`、`jobs.py`、`database.py` 和 `repositories.py` 等临时兼容入口，
后续若迁移 HTTP 路由，应单独调整 import、请求边界和测试，不能把这次清理当作 API
目录迁移。

## 为什么目录移动必须分批完成

目录移动会同时影响 Python import、PyInstaller 收集、测试发现、Tauri 构建和文档命令。
一次性移动全部目录会让行为变化与路径变化混在一起，失败时难以判断原因，也难以回滚。

因此后续按一个边界一个提交推进，例如先迁移 API routes，再迁移 application services，
最后迁移 infrastructure providers。每批只调整 import、构建收集路径和对应测试；每批
都必须通过 Python 测试、前端构建、`cargo check`，必要时重新验证 Sidecar，再进入下一批。
在迁移期间保留可回滚的兼容导入，但不让 `legacy/` 进入新版运行链。

## R1 结果与后续约束

本轮只创建目标目录、Python 包标记文件和本 ADR。没有移动现有业务文件，没有修改
数据库 Schema、依赖或运行逻辑。R2 只能在本分支经用户确认后开始，并应继续遵守
“单边界、小提交、可验证、可回滚”的迁移策略。
