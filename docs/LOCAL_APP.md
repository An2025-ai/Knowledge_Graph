# Brand Atlas 本地应用

本目录新增的 `backend/`、`frontend/` 和 `desktop/` 组成独立桌面应用：

```text
Tauri 独立窗口 ── 内嵌 React UI ── 本地 sidecar ── FastAPI
                                               ├── SQLite（唯一事实源）
                                               ├── 本地文档目录
                                               └── 可选外部 LLM API
```

## 快速启动（桌面窗口）

```powershell
pip install -r requirements-desktop.txt
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run dev
```

这会直接打开 Brand Atlas 桌面窗口。开发脚本会在窗口背后启动 Vite 和
仅监听 `127.0.0.1` 的 Python API；不需要用户访问 Web 端口。浏览器模式
仍可通过 `./scripts/dev-local.ps1` 用于前端调试。

## 数据与配置

- 数据默认位于 `%LOCALAPPDATA%\BrandAtlas`。
- `%LOCALAPPDATA%/BrandAtlas/database/knowledge.db` 保存文档、证据单元、候选、实体、关系和任务状态。
- `documents/`、`vectors/`、`cache/`、`logs/`、`backups/` 预留给后续模块。
- `config/settings.json` 只保存非敏感模型配置。
- API Key 通过 Python `keyring` 保存到 Windows Credential Manager。
- 本地 API 每个请求都要求 `Authorization: Bearer <token>`，健康检查除外。

## 可扩展边界

- `backend/app/repositories.py`：SQLite 数据访问边界；未来可增加服务器版仓储实现。
- `backend/app/services/ingestion.py`：文档处理用例；复用 `shared/extraction/` 和 `shared/knowledge/` 中的纯规则。
- `backend/app/services/agent.py`：本地检索与外部 LLM 编排。
- `backend/app/routes/`：按业务模块拆分的 HTTP 接口。
- `frontend/src/components/`：对话、导入、图谱和设置组件独立演进。

当前桌面应用默认不启动 PostgreSQL、Neo4j、Docker、Redis 或本地大模型；旧的
服务器链路整体保留在 `legacy/`，跨运行时的纯领域能力集中在 `shared/`。
