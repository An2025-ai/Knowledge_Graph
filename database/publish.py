# Brand Atlas Knowledge Graph — YAML → PostgreSQL 发布脚本
# 版本: 1.1.0
# 用途: 将 common_knowledge/ 中的 YAML 文件同步到 PostgreSQL 数据库
# 依赖: pip install pyyaml psycopg2-binary
# 用法: python publish.py [--dry-run] [--file <path>]

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

import yaml

try:
    import psycopg2
    from psycopg2.extras import Json
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    print("警告: psycopg2 未安装，将仅验证 YAML 文件而不连接数据库。")
    print("安装: pip install psycopg2-binary")


# ============================================================================
# 配置
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)  # Knowledge_Graph 根目录
COMMON_KNOWLEDGE_DIR = os.path.join(PROJECT_DIR, "common_knowledge")

# 数据库连接（从环境变量读取）
DB_CONFIG = {
    "host": os.environ.get("KG_DB_HOST", "localhost"),
    "port": int(os.environ.get("KG_DB_PORT", "5432")),
    "dbname": os.environ.get("KG_DB_NAME", "brand_atlas_kg"),
    "user": os.environ.get("KG_DB_USER", "kg_admin"),
    "password": os.environ.get("KG_DB_PASSWORD", ""),
}

# 文件→表映射
FILE_TABLE_MAP = {
    "ontology/entities.yaml": {
        "table": "entity_type",
        "key_field": "type_code",
        "key_path": "type",
        "data_path": "entity_types",
        "extra_fields": {},
    },
    "ontology/relations.yaml": {
        "table": "relation_type",
        "key_field": "relation_code",
        "key_path": "relation",
        "data_path": "relation_types",
        "extra_fields": {
            "subject_types": "subject_types",
            "object_types": "object_types",
        },
    },
    "intents/intent_types.yaml": {
        "table": "intent_definition",
        "key_field": "intent_code",
        "key_path": "id",
        "data_path": "intent_types",
        "extra_fields": {},
    },
    "sources/source_types.yaml": {
        "table": "source_policy",
        "key_field": "source_type",
        "key_path": "type",
        "data_path": "source_types",
        "extra_fields": {},
    },
    "sources/authority_rules.yaml": {
        "table": "quality_rule",
        "key_field": "rule_code",
        "key_path": "id",
        "data_path": "rules",
        "extra_fields": {},
    },
    "tasks/brand_onboarding.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/prompt_generation.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/topic_planning.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/search_diagnosis.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/content_brief.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    # v1.1.0 新增任务
    "tasks/industry_knowledge_build.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/industry_knowledge_refresh.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/source_discovery.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "tasks/knowledge_promotion.yaml": {
        "table": "task_template",
        "key_field": "task_code",
        "key_path": "id",
        "data_path": None,
        "is_single": True,
        "record_key": "task",
        "extra_fields": {},
    },
    "examples/positive_examples.yaml": {
        "table": "example_case",
        "key_field": "case_code",
        "key_path": "id",
        "data_path": "examples",
        "extra_fields": {"case_type": "positive"},
    },
    "examples/negative_examples.yaml": {
        "table": "example_case",
        "key_field": "case_code",
        "key_path": "id",
        "data_path": None,
        "is_multi_group": True,
        "group_prefix": "task_",
        "group_suffix": "_examples",
        "extra_fields": {"case_type": "negative"},
    },
}

# 字段映射：YAML 字段 → 数据库列
FIELD_MAPPING = {
    "entity_type": {
        "type": "type_code",
        "canonical_name": "canonical_name",
        "canonical_name_en": "canonical_name_en",
        "definition": "definition",
        "examples": "examples",
        "required_fields": "required_fields",
        "optional_fields": "optional_fields",
        "constraints": "constraints",
        "version": "version",
        "status": "status",
        "source_refs": "source_refs",
    },
    "relation_type": {
        "relation": "relation_code",
        "description": "description",
        "description_en": "description_en",
        "subject_types": "subject_types",
        "object_types": "object_types",
        "cardinality": "cardinality",
        "bidirectional": "bidirectional",
        "inverse_relation": "inverse_relation",
        "confidence_required": "confidence_required",
        "source_refs_required": "source_refs_required",
        "examples": "examples",
        "version": "version",
        "status": "status",
    },
    "intent_definition": {
        "id": "intent_code",
        "name": "name",
        "name_en": "name_en",
        "decision_stage": "decision_stage",
        "description": "description",
        "question_patterns": "question_patterns",
        "expected_answer_blocks": "expected_answer_blocks",
        "preferred_evidence": "preferred_evidence",
        "content_types": "content_types",
        "quality_checks": "quality_checks",
        "version": "version",
        "status": "status",
    },
    "source_policy": {
        "type": "source_type",
        "name": "name",
        "name_en": "name_en",
        "definition": "definition",
        "authority_level": "authority_level",
        "suitable_for": "suitable_for",
        "not_suitable_for": "not_suitable_for",
        "examples": "examples",
        "validation_rules": "validation_rules",
        "version": "version",
        "status": "status",
    },
    "quality_rule": {
        "id": "rule_code",
        "rule": "rule",
        "category": "category",
        "applies_to": "applies_to",
        "priority": "priority",
        "description": "description",
        "positive_example": "positive_example",
        "negative_example": "negative_example",
        "version": "version",
        "status": "status",
    },
    "task_template": {
        "id": "task_code",
        "name": "name",
        "name_en": "name_en",
        "version": "version",
        "purpose": "purpose",
        "description": "description",
        "required_context": "required_context",
        "optional_context": "optional_context",
        "output_schema": "output_schema",
        "output_fields": "output_fields",
        "rules": "rules",
        "failure_mode": "failure_mode",
        "failure_handling": "failure_handling",
        "quality_checks": "quality_checks",
        "metric_refs": "metric_refs",
        "status": "status",
    },
    "example_case": {
        "id": "case_code",
        "task_id": "task_id",
        "name": "name",
        "scenario": "scenario",
        "input": "input_data",
        "expected_output": "expected_output",
        "wrong_approach": "wrong_approach",
        "why_wrong": "why_wrong",
        "violated_rule": "violated_rule",
        "correct_approach": "correct_approach",
        "demonstrates": "demonstrates",
        "severity": "severity",
        "tags": "tags",
        "source_refs": "source_refs",
        "version": "version",
        "status": "status",
    },
}


# ============================================================================
# 核心函数
# ============================================================================

def load_yaml(filepath):
    """加载 YAML 文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_hash(filepath):
    """计算文件 SHA-256"""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def get_nested(data, path):
    """通过点号路径获取嵌套值，如 'task.id'"""
    keys = path.split(".")
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def map_fields(data, table_name, extra_fields=None):
    """将 YAML 字段映射到数据库列"""
    mapping = FIELD_MAPPING.get(table_name, {})
    row = {}

    for yaml_field, db_column in mapping.items():
        value = data.get(yaml_field)
        if value is not None:
            # JSONB 字段保持为 dict/list
            if isinstance(value, (dict, list)):
                row[db_column] = Json(value)
            else:
                row[db_column] = value

    # 添加额外字段
    if extra_fields:
        for key, val in extra_fields.items():
            if key not in row:
                row[key] = val if not isinstance(val, (dict, list)) else Json(val)

    return row


def publish_file(conn, relpath, dry_run=False):
    """发布单个 YAML 文件到数据库"""
    filepath = os.path.join(COMMON_KNOWLEDGE_DIR, relpath)

    if not os.path.exists(filepath):
        print(f"  [SKIP] 文件不存在: {relpath}")
        return False

    config = FILE_TABLE_MAP.get(relpath)
    if not config:
        print(f"  [SKIP] 无映射配置: {relpath}")
        return False

    # 加载 YAML
    data = load_yaml(filepath)
    if not data:
        print(f"  [SKIP] 空文件: {relpath}")
        return False

    meta = data.get("meta", {})
    version = meta.get("version", "1.0.0")
    file_hash = compute_hash(filepath)

    table_name = config["table"]
    key_field = config["key_field"]
    key_path = config["key_path"]

    if dry_run:
        print(f"  [DRY-RUN] {relpath} → {table_name} (v{version})")
        return True

    # 更新 knowledge_definition
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_definition (file_path, file_name, category, version, description, content_hash, published_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (file_path) DO UPDATE SET
                   version = EXCLUDED.version,
                   content_hash = EXCLUDED.content_hash,
                   published_at = NOW(),
                   updated_at = NOW()""",
            (
                relpath,
                os.path.basename(relpath),
                relpath.split("/")[0],
                version,
                meta.get("description", ""),
                file_hash,
            ),
        )
        conn.commit()

    # 处理数据记录
    if config.get("is_single"):
        # 单文件单记录（如 task 文件）
        record_key = config.get("record_key", "task")
        record_data = data.get(record_key, data)
        key_value = get_nested(record_data, key_path)
        if not key_value:
            print(f"  [WARN] 无法提取 key: {key_path} from {relpath}")
            return False

        row = map_fields(record_data, table_name, config.get("extra_fields"))
        upsert_record(conn, table_name, key_field, key_value, row)
        print(f"  [OK] {relpath} → {table_name}.{key_field}={key_value}")
    elif config.get("is_multi_group"):
        # 多组文件（如 examples 文件，按 task 分组）
        prefix = config.get("group_prefix", "")
        suffix = config.get("group_suffix", "")
        total_items = 0
        for group_key, items in data.items():
            if isinstance(items, list) and group_key.startswith(prefix) and group_key.endswith(suffix):
                for item in items:
                    key_value = get_nested(item, key_path)
                    if not key_value:
                        print(f"  [WARN] 跳过无 key 的记录 in {relpath}/{group_key}")
                        continue
                    row = map_fields(item, table_name, config.get("extra_fields"))
                    upsert_record(conn, table_name, key_field, key_value, row)
                    total_items += 1
        print(f"  [OK] {relpath} → {table_name} ({total_items} 条记录)")
    else:
        # 多记录文件
        data_path = config["data_path"]
        items = data.get(data_path, [])
        if not items:
            print(f"  [WARN] 无数据: {relpath}.{data_path}")
            return False

        for item in items:
            key_value = get_nested(item, key_path)
            if not key_value:
                print(f"  [WARN] 跳过无 key 的记录 in {relpath}")
                continue

            row = map_fields(item, table_name, config.get("extra_fields"))
            upsert_record(conn, table_name, key_field, key_value, row)

        print(f"  [OK] {relpath} → {table_name} ({len(items)} 条记录)")

    return True


def upsert_record(conn, table, key_field, key_value, row):
    """插入或更新记录"""
    # 构建动态 SQL
    columns = [key_field] + [k for k in row.keys() if k != key_field]
    values = [key_value] + [row[k] for k in row.keys() if k != key_field]

    # 兼容旧版 psycopg2 的 JSON 处理
    safe_values = []
    for v in values:
        if isinstance(v, Json):
            safe_values.append(v)
        elif isinstance(v, (dict, list)):
            safe_values.append(Json(v))
        else:
            safe_values.append(v)

    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != key_field])

    sql = f"""
        INSERT INTO {table} ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT ({key_field}) DO UPDATE SET
            {updates},
            updated_at = NOW()
    """

    with conn.cursor() as cur:
        cur.execute(sql, safe_values)
    conn.commit()


def publish_all(dry_run=False):
    """发布所有文件"""
    print(f"\n{'='*60}")
    print(f"Brand Atlas Knowledge Graph — 发布脚本 v1.0.0")
    print(f"时间: {datetime.now(timezone.utc).isoformat()}")
    print(f"模式: {'DRY-RUN (仅验证)' if dry_run else 'LIVE (写入数据库)'}")
    print(f"{'='*60}\n")

    if not dry_run and not HAS_PSYCOPG2:
        print("错误: 未安装 psycopg2，无法连接数据库。")
        print("请运行: pip install psycopg2-binary")
        sys.exit(1)

    conn = None
    if not dry_run:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            print(f"数据库连接成功: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}\n")
        except Exception as e:
            print(f"数据库连接失败: {e}")
            print("请检查环境变量: KG_DB_HOST, KG_DB_PORT, KG_DB_NAME, KG_DB_USER, KG_DB_PASSWORD")
            sys.exit(1)

    try:
        success = 0
        failed = 0
        for relpath in sorted(FILE_TABLE_MAP.keys()):
            try:
                if publish_file(conn, relpath, dry_run):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"  [ERROR] {relpath}: {e}")
                failed += 1

        print(f"\n{'='*60}")
        print(f"发布完成: {success} 成功, {failed} 失败")
        print(f"{'='*60}\n")

    finally:
        if conn:
            conn.close()


# ============================================================================
# 验证模式（不需要数据库连接）
# ============================================================================

def validate_all():
    """验证所有 YAML 文件的可解析性和完整性"""
    print(f"\n{'='*60}")
    print(f"Brand Atlas Knowledge Graph — YAML 验证")
    print(f"{'='*60}\n")

    errors = []
    for relpath in sorted(FILE_TABLE_MAP.keys()):
        filepath = os.path.join(COMMON_KNOWLEDGE_DIR, relpath)
        if not os.path.exists(filepath):
            errors.append(f"文件不存在: {relpath}")
            continue

        try:
            data = load_yaml(filepath)
            if not data:
                errors.append(f"空文件: {relpath}")
                continue

            # 检查 meta
            meta = data.get("meta")
            if not meta:
                errors.append(f"缺少 meta 块: {relpath}")
            elif not meta.get("version"):
                errors.append(f"缺少 version: {relpath}")

            # 检查数据
            config = FILE_TABLE_MAP[relpath]
            if config.get("is_single"):
                record_key = config.get("record_key", "task")
                record = data.get(record_key, data)
                key = get_nested(record, config["key_path"])
                if not key:
                    errors.append(f"缺少 key '{config['key_path']}': {relpath}")
            elif config.get("is_multi_group"):
                prefix = config.get("group_prefix", "")
                suffix = config.get("group_suffix", "")
                total = 0
                for group_key, items in data.items():
                    if isinstance(items, list) and group_key.startswith(prefix) and group_key.endswith(suffix):
                        total += len(items)
                if total == 0:
                    errors.append(f"空数据（多组）: {relpath}")
            else:
                items = data.get(config["data_path"], [])
                if not items:
                    errors.append(f"空数据 '{config['data_path']}': {relpath}")

            print(f"  [OK] {relpath}")

        except yaml.YAMLError as e:
            errors.append(f"YAML 解析错误 {relpath}: {e}")
        except Exception as e:
            errors.append(f"未知错误 {relpath}: {e}")

    if errors:
        print(f"\n验证失败 ({len(errors)} 个错误):")
        for e in errors:
            print(f"  X {e}")
        return False
    else:
        print(f"\n全部 {len(FILE_TABLE_MAP)} 个文件验证通过!")
        return True


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Brand Atlas Knowledge Graph — YAML → PostgreSQL 发布工具"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证文件，不写入数据库",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="仅验证 YAML 文件的可解析性和完整性",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="仅发布指定的文件（相对路径）",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="初始化数据库 Schema（运行 schema.sql）",
    )
    args = parser.parse_args()

    if args.validate:
        valid = validate_all()
        sys.exit(0 if valid else 1)

    if args.init_db:
        if not HAS_PSYCOPG2:
            print("错误: 需要 psycopg2 来初始化数据库。")
            sys.exit(1)
        schema_path = os.path.join(BASE_DIR, "database", "schema.sql")
        if not os.path.exists(schema_path):
            print(f"错误: Schema 文件不存在: {schema_path}")
            sys.exit(1)
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()
            conn.close()
            print("数据库 Schema 初始化成功!")
        except Exception as e:
            print(f"Schema 初始化失败: {e}")
            sys.exit(1)
        sys.exit(0)

    if args.file:
        if not args.dry_run and not HAS_PSYCOPG2:
            print("错误: 需要 psycopg2 来写入数据库（或使用 --dry-run）。")
            sys.exit(1)
        conn = None if args.dry_run else psycopg2.connect(**DB_CONFIG)
        try:
            publish_file(conn, args.file, args.dry_run)
        finally:
            if conn:
                conn.close()
    else:
        publish_all(dry_run=args.dry_run)