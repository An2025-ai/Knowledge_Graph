# 启动与运行故障排查

## 第一步：确认路径

```powershell
python scripts/maintenance/show_runtime_paths.py
```

重点确认数据库是否位于预期位置，以及 `database_exists` 是否为 `true`。如果发布版路径指向项目目录或临时目录，先检查 `BRAND_ATLAS_DATABASE_PATH`、`BRAND_ATLAS_DATA_DIR` 和 Tauri Debug 配置。

## Sidecar 无法启动

按以下顺序检查：

1. 直接运行 `python -m unittest discover -s tests -p "test_*.py"`。
2. 确认 `backend/app/migrations/` 已随 Sidecar 打包；重新执行 `scripts/build/prepare-tauri-sidecar.ps1`。
3. 检查 Python/Sidecar 输出中的迁移错误。迁移失败会阻止启动，不会自动删除数据库。
4. 检查数据库：

   ```powershell
   python scripts/maintenance/verify_database.py
   ```

   如果提示 `unknown` 或 `invalid` schema version，不要手工删除 `schema_versions`，先备份并保留错误信息。

## 数据库被占用或 locked

- 先关闭桌面窗口。
- 在任务管理器中确认 `knowledge-engine.exe` 已退出。
- 确认没有并行运行开发版和安装版。
- 不要删除 `-wal` 或 `-shm` 文件来解决锁问题；先完成进程排查并备份数据库。

## 数据损坏或外键错误

运行：

```powershell
python scripts/maintenance/verify_database.py
```

如果 `integrity_check` 不是 `ok`，或 `foreign_key_errors` 大于 0，立即保留原数据库并创建备份，不要继续导入新文档。恢复流程见 [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)。

## 模型连接失败

- 设置页面中的 LLM 和 Embedding 测试按钮是独立的。
- Embedding 失败不应阻止规则抽取、图谱构建和对话。
- 检查 Base URL、模型名和系统 Keyring 配置。
- `settings.json` 只保存非敏感配置，API Key 不应出现在配置文件、安装包或日志中。

排查时不要把包含 Authorization、API Key 或完整敏感文档的日志粘贴到工单或聊天中。

## 导入或重新处理异常

文档重新处理采用替换语义：当前文档的证据、候选、关系和陈述会在同一事务内更新，其他文档的关系和共享实体不会删除。发生异常时先运行数据库校验，再保留原数据库和错误时间点，不要手工清理关系表。

## 需要收集的安全诊断信息

可以提供：

- 操作系统和应用版本；
- `show_runtime_paths.py` 的路径字段；
- `verify_database.py` 的状态、表缺失列表和迁移版本；
- 错误类型和时间。

不要提供：API Key、Bearer Token、Keyring 内容、完整文档正文或未经脱敏的数据库文件。
