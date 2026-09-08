# 数据备份与恢复

## 数据位置

先查看当前运行时实际解析到的路径：

```powershell
python scripts/maintenance/show_runtime_paths.py
```

发布版默认使用：

```text
%LOCALAPPDATA%\BrandAtlas\database\knowledge.db
%LOCALAPPDATA%\BrandAtlas\backups\
```

`BRAND_ATLAS_DATABASE_PATH` 只覆盖数据库文件，`BRAND_ATLAS_DATA_DIR` 覆盖完整数据根目录；前者优先。Tauri Debug 模式可能显式使用项目目录下的 `database\knowledge.db`，执行备份前应以路径脚本输出为准。

## 创建备份

备份前不要求关闭应用。脚本调用 SQLite Backup API，能够在数据库运行和 WAL 开启时生成一致副本，不直接复制正在使用的主数据库文件：

```powershell
$backup = Join-Path $env:LOCALAPPDATA ("BrandAtlas\backups\knowledge-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".db")
python scripts/maintenance/backup_database.py --output $backup
```

也可以显式指定源数据库：

```powershell
python scripts/maintenance/backup_database.py `
  --database "D:\path\to\knowledge.db" `
  --output "D:\backup\knowledge.db"
```

脚本不会自动删除旧备份。备份文件应放在应用数据目录之外或再复制到受控的备份介质中；备份本身可能包含用户文档和知识内容，应按敏感数据管理。

## 校验备份

```powershell
python scripts/maintenance/verify_database.py --database $backup
```

校验包括 SQLite 完整性、外键错误、必要表和迁移版本。输出只包含路径、数量和版本，不包含文档正文、API Key 或 Bearer Token。`status` 为 `ok` 才表示数据库已经处于当前迁移版本；`migration_pending` 表示可读取但需要让应用启动完成迁移。

## 恢复流程（本阶段不提供自动恢复命令）

恢复可能覆盖用户数据，必须人工确认：

1. 完全退出桌面应用，并确认 Sidecar 进程已经结束、数据库文件不再被占用。
2. 使用 `show_runtime_paths.py` 确认目标数据库路径。
3. 先按上面的流程备份当前数据库，保留原文件，不要直接删除。
4. 检查待恢复备份的 `verify_database.py` 结果为 `ok`。
5. 在明确确认目标路径和备份文件后，再由维护人员使用系统文件工具将备份恢复到目标位置。
6. 启动应用，让迁移机制完成必要升级，再次运行 `verify_database.py`。

不要把恢复文件写入 PyInstaller 临时解压目录，也不要在应用运行时覆盖数据库。
