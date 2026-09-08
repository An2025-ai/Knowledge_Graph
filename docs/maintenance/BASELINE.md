# Brand Atlas Task 01 基线记录

> 记录日期：2026-09-08
>
> 目的：记录修改前的真实环境和运行状态，避免把依赖问题误判为代码回归。

## 当前维护入口（2026-09-08）

Task 01 的原始记录保留在下文；后续任务已经更新了运行路径和测试数量。当前维护时以以下规则为准：

- 发布版默认数据根目录：`%LOCALAPPDATA%\BrandAtlas\`
- 发布版数据库：`%LOCALAPPDATA%\BrandAtlas\database\knowledge.db`
- 开发版可由 `BRAND_ATLAS_DATABASE_PATH` 或 `BRAND_ATLAS_DATA_DIR` 显式覆盖。
- 当前数据库迁移说明见 [DATABASE.md](DATABASE.md)。
- 路径、备份和校验入口见 [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) 及 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
- 当前全量 Python 测试为 93 项；具体发布验收以 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) 为准。

## 基线范围

本次按 `requirements-desktop.txt` 准备 `kgnew` 环境，并检查：

- Python 全部测试
- 前端 TypeScript/Vite 生产构建
- Windows/Tauri Rust `cargo check`
- 默认数据库路径
- 当前开发启动链路和打包链路

本任务没有修改产品代码、测试代码或依赖版本。

## 当前工作区状态

基线建立时工作区并非完全干净，以下两项是任务开始前已经存在的用户改动，本任务未处理：

- 删除：`docs_AUDIT_ACTION_PLAN.md`
- 新增但未跟踪（当时）：`Brand_Atlas_Phase1_AI_Task_Plan.md`；当前任务书已归档到 `docs/migration/Brand_Atlas_Phase1_AI_Task_Plan.md`

本任务只新增本文件。

## 工具链版本

系统可用版本：

- Conda：`26.1.1`
- Python（当前系统环境）：`3.13.9`
- Python（新版测试环境 `kgnew`）：`3.12.14`
- Node.js：`v24.18.0`
- npm：`11.16.0`
- Rust：`rustc 1.97.1 (8bab26f4f 2026-07-14)`
- Cargo：`cargo 1.97.1 (c980f4866 2026-06-30)`

## 依赖准备

执行：

```powershell
conda run -n kgnew python -m pip install -r requirements-desktop.txt
```

结果：`requirements-desktop.txt` 中声明的依赖均已满足，未发生版本升级。Conda 提示环境目录不可写并采用 user installation，但当前所需包均已存在于 `kgnew` 环境中。

`kgnew` 中抽查到的关键版本：

- FastAPI `0.141.1`
- Uvicorn `0.52.4`
- Pydantic `2.13.5`
- keyring `25.7.0`
- PyYAML `6.0.3`
- jsonschema `4.26.0`
- PyMuPDF `1.28.2`
- python-docx `1.2.0`
- openpyxl `3.1.5`
- PyInstaller `6.22.2`

## Python 测试结果

### `kgnew` 新版测试环境

直接使用 `D:\anaconda\envs\kgnew\python.exe` 执行：

```powershell
D:\anaconda\envs\kgnew\python.exe -m unittest discover -s tests -p "test_*.py"
```

结果：

- 发现并执行 63 项测试
- 62 项通过
- 1 项导入错误
- 错误发生在 `tests/test_local_app.py` 导入阶段
- 原因是 `kgnew` 中没有安装 Starlette TestClient 当前要求的 `httpx2`
- 该依赖未声明在 `requirements-desktop.txt` 中
- 没有发现业务断言失败

第一次使用 `conda run` 包装器执行时，Conda 自身因 Windows GBK 输出编码无法打印子进程中的字符，抛出 `UnicodeEncodeError`。改为直接调用 `kgnew` 的 Python 可执行文件后，问题被准确区分为上述缺失测试依赖。

### 当前系统基础环境补充结果

使用当前系统 Python 执行相同命令：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

结果：

- 71 项测试全部通过
- `OK`

这说明当前代码的既有测试在基础环境中可以通过；`kgnew` 的失败属于测试环境依赖缺失，不属于当前产品代码回归。

## 前端构建结果

执行：

```powershell
npm --prefix frontend run build
```

结果：通过。

- TypeScript 编译通过
- Vite 构建通过
- 输出目录：`frontend/dist/`
- 构建产物包含 `index.html`、CSS 和 JavaScript bundle

## Tauri 检查结果

执行：

```powershell
cargo check --manifest-path desktop/src-tauri/Cargo.toml
```

结果：通过。

```text
Finished `dev` profile [unoptimized + debuginfo]
```

这只验证 Rust/Tauri 工程可以编译检查，不等同于已经生成并安装 Windows NSIS 安装包。

## Task 01 时的默认数据库路径（历史记录）

当前默认路径为：

```text
D:\work\agent\Knowledge_Graph\database\knowledge.db
```

路径规则来自 `backend/app/config.py`：

- 未设置环境变量时，使用项目根目录下的 `database\knowledge.db`
- 设置 `BRAND_ATLAS_DATABASE_PATH` 时，使用该绝对路径
- 设置 `BRAND_ATLAS_DATA_DIR` 且未指定数据库绝对路径时，使用 `<data_dir>\database\knowledge.db`
- 其他运行数据默认位于 `%LOCALAPPDATA%\BrandAtlas`

SQLite 连接当前启用 WAL、外键和 30 秒 busy timeout；连接在查询或事务结束后关闭。

## 当前开发启动链路

桌面开发入口：

```powershell
pip install -r requirements-desktop.txt
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run dev
```

实际链路如下：

```text
npm --prefix desktop run dev
    → Tauri CLI
        → scripts/dev/dev-desktop.ps1
            → 启动 frontend Vite
        → desktop/src-tauri/src/main.rs
            → 启动 backend.main Python 进程
            → 打开 Tauri 窗口
```

开发模式下由 Tauri 进程持有 Python 后端生命周期，关闭窗口时会停止后端并释放 SQLite。`scripts/dev/dev-local.ps1` 仍可用于浏览器模式的前端调试，但不是产品桌面启动路径。

## 当前打包链路

Windows 安装包文档路径为：

```powershell
pip install -r requirements-desktop.txt
./scripts/build/prepare-tauri-sidecar.ps1
npm --prefix frontend install
npm --prefix desktop install
npm --prefix desktop run build
```

其中：

1. `scripts/build/prepare-tauri-sidecar.ps1` 调用 `scripts/build/build-sidecar.ps1`
2. `build-sidecar.ps1` 使用 PyInstaller 将 `backend/main.py` 打包为 one-file、no-console 的 `knowledge-engine.exe`
3. 打包时嵌入 `backend/app/schema.sql`、`backend/app/migrations/` 和 `common_knowledge/`
4. `prepare-tauri-sidecar.ps1` 根据 Rust target triple 将 sidecar 放入 `desktop/src-tauri/binaries/`
5. Tauri 的 `beforeBuildCommand` 构建 `frontend/dist/`
6. Tauri 根据 `desktop/src-tauri/tauri.conf.json` 生成 NSIS 安装包
7. 当前桌面应用版本为 `0.1.0`

## 当前未在本任务中验证的项目

以下项目没有作为本次基线的必需执行项，或当前无法据此确认完整可用：

- 未执行完整的 `npm --prefix desktop run build` NSIS 安装包构建
- 未启动最终打包后的 `knowledge-engine.exe` 做 sidecar 黑盒测试
- 未启动 Tauri 桌面窗口执行导入、对话和关闭生命周期的端到端测试
- 未调用真实外部 LLM 或 Embedding API
- 未验证 Windows Credential Manager 中 keyring 的实际读写
- `kgnew` 测试环境仍缺少 `httpx2`，因此该环境的 `test_local_app.py` 尚未运行

以上未验证项属于测试范围或环境依赖限制，不构成对产品代码的修复。

## 本任务结论

- 依赖准备：通过，声明依赖已满足
- Python 测试：基础环境 71 项通过；`kgnew` 因缺少未声明的 `httpx2` 有 1 项导入错误
- 前端构建：通过
- Tauri `cargo check`：通过
- 默认数据库路径：项目根目录 `database\knowledge.db`
- 产品代码变更：无
- 新增文件：`docs/maintenance/BASELINE.md`
