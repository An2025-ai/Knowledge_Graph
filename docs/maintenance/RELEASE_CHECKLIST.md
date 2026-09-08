# 发布验收清单

每次生成桌面发布包前，在 Windows 工作区按顺序执行并记录结果。

## 自动检查

- [ ] 准备 `requirements-desktop.txt` 环境。
- [ ] Python 测试：

  ```powershell
  python -m unittest discover -s tests -p "test_*.py"
  ```

- [ ] 前端构建：

  ```powershell
  npm --prefix frontend run build
  ```

- [ ] Rust 检查：

  ```powershell
  cargo check --manifest-path desktop/src-tauri/Cargo.toml
  ```

- [ ] Sidecar 构建并暂存：

  ```powershell
  ./scripts/build/prepare-tauri-sidecar.ps1
  ```

- [ ] Tauri/NSIS 打包：

  ```powershell
  npm --prefix desktop run build
  ```

## 功能验收

- [ ] 在干净环境安装并启动新安装包。
- [ ] 使用临时旧数据库验证启动时迁移成功；确认 `schema_versions` 顺序正确。
- [ ] 退出并重新启动，确认文档、实体、关系和设置仍然存在。
- [ ] 修改 LLM/Embedding 设置后，不重启直接测试对话和文档导入。
- [ ] 导入文档，并重新处理同一文档；确认旧关系被替换、其他文档关系保留。
- [ ] 创建 SQLite 备份并运行 `verify_database.py`，确认备份可读取且完整性为 `ok`。

## 安全验收

- [ ] 安装包和 Sidecar 中没有 API Key 或 Bearer Token。
- [ ] `config/settings.json` 中没有 API Key 明文。
- [ ] 日志和诊断输出中没有 API Key、Bearer Token 或完整敏感文档内容。
- [ ] API Key 仅通过系统 Keyring 保存和读取。
- [ ] 发布版数据库不位于项目目录或 PyInstaller 临时解压目录。

## 产物记录

记录以下信息后再交付：

- 应用版本号；
- Git 提交号；
- Python、Node/npm、Rust/Cargo 版本；
- 测试和构建结果；
- NSIS 安装包路径；
- Sidecar 路径；
- 是否完成新安装、旧数据库升级和备份读取验证。
