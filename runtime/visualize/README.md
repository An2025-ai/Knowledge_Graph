# Brand Atlas — 交互式知识图谱查看

在 VSCode 里用 Jupyter + pyvis 渲染**可交互的知识图谱**，查看 L2/L3 阶段性结果。

## 1. 一次性安装

**VSCode 插件**（必装）：
- **Jupyter**（`ms-toolsai.jupyter`）— 官方插件，用于打开 .ipynb

**Python 包**：
```bash
pip install -r runtime/requirements.txt   # 含 jupyter, ipykernel, pyvis, networkx
```

## 2. 使用流程

```bash
# ① 确保数据库在跑、已跑过执行器（库里要有实体/关系）
cd runtime && docker compose up -d

# ② 导出图谱数据为 JSON（在项目根目录）
python -m runtime.visualize.export
#   可选局部导出：
#   python -m runtime.visualize.export --brand <brand_id> --tenant <tenant_id>
#   python -m runtime.visualize.export --industry <industry_id>

# ③ 在 VSCode 打开 notebook
#    打开 runtime/visualize/knowledge_graph.ipynb
#    右上角选择 Python 内核 → 点"运行全部"
```

## 3. 你会看到

- **交互式知识图**：可缩放、拖拽、按类型筛色（brand=蓝、product=绿、organization=橙等）
- **实体/关系统计表**：各类型节点数、关系数
- **Assertion/Statement 列表**：带证据的陈述

每次跑完新执行器，重导一次（步骤②）再跑 notebook 代码块 2-4 即可刷新。

## 4. 文件

| 文件 | 说明 |
|------|------|
| `knowledge_graph.ipynb` | Jupyter notebook（主查看入口） |
| `export.py` | PostgreSQL → JSON 导出脚本 |
| `output/` | 导出数据和生成的 HTML 图（自动生成） |

## 5. 备选：Neo4j Browser

如果 Neo4j 已启动（`docker compose up -d`），浏览器打开 `http://localhost:7474`，用自带的可视化看完整图谱（账号 `neo4j` / `neo4j_admin_password`）。Jupyter 方案不依赖 Neo4j，用 PostgreSQL 数据即可。