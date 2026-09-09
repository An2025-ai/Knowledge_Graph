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
仍可通过 `./scripts/dev/dev-local.ps1` 用于前端调试。

## 数据与配置

- SQLite 数据库默认位于 `%LOCALAPPDATA%\BrandAtlas\database\knowledge.db`，保存文档、证据单元、候选、实体、关系和任务状态。
- `documents/`、`vectors/`、`cache/`、`logs/`、`backups/` 和 `config/` 也位于 `%LOCALAPPDATA%\BrandAtlas` 下。
- 设置 `BRAND_ATLAS_DATA_DIR` 会将完整数据根目录切换到指定位置；设置 `BRAND_ATLAS_DATABASE_PATH` 只切换数据库文件，且优先级更高。
- Tauri Debug 开发模式会显式将数据库指定为项目目录下的 `database/knowledge.db`，发布 Sidecar 不使用该路径。
- `config/settings.json` 只保存非敏感模型配置。
- API Key 通过 Python `keyring` 保存到 Windows Credential Manager。
- 本地 API 每个请求都要求 `Authorization: Bearer <token>`，健康检查除外。

## 可扩展边界

- `backend/app/infrastructure/repositories.py`：SQLite 数据访问边界；未来可增加服务器版仓储实现。
- `backend/app/application/services/ingestion.py`：文档处理用例；负责导入幂等和持久化边界。
- `backend/app/application/services/knowledge_pipeline.py`：新运行时的候选抽取、归一化、融合、实体解析和关系生成。
- `backend/app/application/services/agent.py`：本地检索与外部 LLM 编排。
- `backend/app/api/routes/`：按业务模块拆分的 HTTP 接口。
- `frontend/src/features/`：对话、导入、图谱和设置组件按功能独立演进。

当前桌面应用默认不启动 PostgreSQL、Neo4j、Docker、Redis 或本地大模型。

## 知识构建流程

导入文档时，桌面版会按以下顺序处理：

```text
内容解析 → 证据单元 → 规则候选 → 可选 LLM 候选 → 归一化/融合
→ 实体解析 → 关系生成 → SQLite 落库
```

候选会保留 `evidence_refs_json`，可追溯到证据单元；同一事实在同一文档内通过稳定
融合键去重，重新导入同一内容则直接返回重复结果。
## 证据级检索与引用

检索结果会保留 `citations` 字段。每条引用包含来源文档、证据单元、原始 Span 文本、标题路径和字符位置。关系的 `properties_json.evidence_refs` 先定位到 `evidence_units`，再通过 `source_span_ids_json` 展开到原文 Span；陈述则使用 `source_span_id`。

聊天来源卡片会展示原文证据，图谱中点击关系边可以展开对应引用；发送给外部 LLM 的本轮本地上下文也会带上受限长度的原文证据。若历史数据没有证据引用，则只显示关系或实体本身，不会猜测来源。
