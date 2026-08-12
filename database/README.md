# Brand Atlas Knowledge Graph — 数据库初始化指南

> **版本**: 1.0.0  
> **创建日期**: 2026-08-07  

## 概述

本目录包含第一层通用知识层的数据库相关文件：
- `schema.sql` — PostgreSQL 数据库 Schema（9 张核心表 + `decision_stage` 辅助表）
- `publish.py` — YAML → PostgreSQL 发布脚本

## 前置条件

### 1. PostgreSQL 数据库

```bash
# 安装 PostgreSQL（如未安装）
# Ubuntu/Debian: sudo apt install postgresql
# macOS: brew install postgresql
# Windows: https://www.postgresql.org/download/windows/
```

### 2. Python 依赖

```bash
pip install -r requirements.txt
```

## 快速开始

### 步骤 1：创建数据库

```sql
CREATE DATABASE brand_atlas_kg;
CREATE USER kg_admin WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE brand_atlas_kg TO kg_admin;
```

### 步骤 2：设置环境变量

```bash
# Linux/macOS
export KG_DB_HOST=localhost
export KG_DB_PORT=5432
export KG_DB_NAME=brand_atlas_kg
export KG_DB_USER=kg_admin
export KG_DB_PASSWORD=your_password

# Windows PowerShell
$env:KG_DB_HOST = "localhost"
$env:KG_DB_PORT = "5432"
$env:KG_DB_NAME = "brand_atlas_kg"
$env:KG_DB_USER = "kg_admin"
$env:KG_DB_PASSWORD = "your_password"
```

### 步骤 3：初始化数据库 Schema

```bash
cd "d:\Brand Atlas\Knowledge_Graph"
python database/publish.py --init-db
```

### 步骤 4：验证全项目数据契约

```bash
python database/publish.py --validate
```

### 步骤 5：发布到数据库

```bash
# 先 dry-run 验证
python database/publish.py --dry-run

# 正式发布
python database/publish.py
```

## 数据库表结构

| 表名 | 说明 | 对应 YAML |
|------|------|-----------|
| `knowledge_definition` | 知识定义文件元数据 | 所有文件的 meta 信息 |
| `knowledge_version` | 版本变更历史 | 自动记录 |
| `entity_type` | 实体类型注册表 | `ontology/entities.yaml` |
| `relation_type` | 关系类型注册表 | `ontology/relations.yaml` |
| `intent_definition` | 意图定义 | `intents/intent_types.yaml` |
| `task_template` | 任务模板 | `tasks/*.yaml` |
| `source_policy` | 来源策略 | `sources/source_types.yaml` |
| `quality_rule` | 质量规则 | `sources/authority_rules.yaml` |
| `example_case` | 示例案例 | `examples/*.yaml` |
| `decision_stage` | 决策阶段（辅助表） | `intents/intent_types.yaml` |

## 字段类型说明

- **JSONB 字段**：存储结构化数据（数组、对象），如 `required_fields`、`question_patterns`、`rules` 等
- **TEXT 字段**：存储长文本，如 `definition`、`description`、`purpose` 等
- **VARCHAR 字段**：存储短标识符，如 `type_code`、`version`、`status` 等

## 发布脚本用法

```bash
# 验证所有 YAML/JSON、Schema 示例、交叉引用和发布映射（不连接数据库）
python database/publish.py --validate

# Dry-run 模式（验证但不写入）
python database/publish.py --dry-run

# 发布所有文件
python database/publish.py

# 仅发布单个文件
python database/publish.py --file ontology/entities.yaml

# 初始化数据库
python database/publish.py --init-db
```

## 版本管理

发布脚本自动处理版本管理：
1. 每次发布时，`knowledge_definition` 表更新 `content_hash` 和 `published_at`
2. 已发布文件的版本号变化时，在 `knowledge_version` 表追加变更历史
3. 使用 `ON CONFLICT ... DO UPDATE` 实现 upsert 语义

`publish.py` 只把 L1 注册数据写入数据库。L2/L3 的 Pipeline YAML 是执行契约，不是可执行程序；当前仓库也没有 L2 基础表 migration 或 Neo4j 投影服务。

## 未来扩展

- **图数据库投影**：实现 L2/L3 权威业务表后，再从 PostgreSQL 投影到 Neo4j；当前仅有设计说明
- **指标计算层**：`task_template.metric_refs` 字段预留了指标集成接口
- **L2/L3 层接入**：`knowledge_definition` 表的 `category` 字段支持扩展为 `industry` 和 `brand` 类别
