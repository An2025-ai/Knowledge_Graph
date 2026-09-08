# SQLite 数据库迁移维护说明

Brand Atlas 的本地数据库由 `backend/app/migrations/versions/` 中的编号迁移文件维护。
应用启动时，`LocalDatabase.initialize()` 会先完成迁移；迁移失败会直接抛出异常，Sidecar 不会继续启动。

## 当前版本

当前迁移按文件名排序执行：

1. `0001_initial.sql`：建立本地 SQLite 的初始表、索引和 `schema_versions` 表。
2. `0002_runtime_fields.sql`：增加运行时需要的 `entities.status`、`pipeline_jobs.payload_json`、`knowledge_candidates.evidence_refs_json` 和 `chat_messages.mode`。

`schema_versions.version` 保存迁移文件的完整版本 ID，例如 `0001_initial`，并按迁移执行顺序写入。`schema.sql` 保留为当前完整 Schema 快照，便于人工检查和备份；应用启动使用编号迁移，不再执行其中的临时补丁。

## 新数据库和旧数据库

- 空数据库从 `0001_initial` 开始，随后执行 `0002_runtime_fields`。
- 早期开发版可能写入 `desktop-1.0.0`。Runner 将它识别为初始基线，继续执行缺失的后续迁移；已存在的运行时列会被安全跳过。
- 已记录的迁移不会重复执行。未知的未来版本会拒绝启动，不会删除或覆盖数据库。

## 事务和失败处理

每个迁移独立运行在一个 SQLite 事务中。迁移文件按语句执行，避免 `executescript()` 自动提交导致的事务失效；任何语句失败都会回滚该迁移，且不会写入该迁移的 `schema_versions` 记录。当前迁移只增加表、索引或列，不做破坏性删除和重建。

已发布的迁移文件不得修改。Schema 变化必须新增更大的编号文件，并在 `tests/test_database_migrations.py` 中增加空库、旧库、幂等和失败回滚测试。

## 运维入口

- 查看路径：`python scripts/maintenance/show_runtime_paths.py`
- 创建备份：`python scripts/maintenance/backup_database.py --output <backup.db>`
- 校验数据库或备份：`python scripts/maintenance/verify_database.py --database <database.db>`

备份与恢复流程见 [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)，启动故障排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
