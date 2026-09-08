# -*- coding: utf-8 -*-
"""Build the self-contained layered 2D graph prototype.

Reads legacy/visualize/output/l1_graph.json, l2_graph.json, l3_graph.json
(produced by `python -m legacy.visualize.export --layer L1/L2/L3`) and writes a
single self-contained HTML (legacy/visualize/output/layered_2d.html) that opens
directly via file:// (data is inlined, vis-network is loaded from the local
assets/ directory — no CDN, no fetch).

Features:
  - L1 / L2 / L3 tabs (progressive presentation)
  - 2D vis-network rendering, nodes colored by entity type
  - click node -> detail panel (label/type/layer/status/…)
  - search box to filter current layer's nodes
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "legacy" / "visualize" / "output"

LAYER_NAMES = {"l1": "L1 通用定义层", "l2": "L2 行业实例层", "l3": "L3 品牌实例层"}

# Node color / shape by entity type (mirrors scripts/build/render_graph.py TYPE_STYLE).
TYPE_STYLE = {
    "industry": "#7C4DFF", "category": "#5C6BC0", "product": "#26A69A",
    "brand": "#EF5350", "organization": "#AB47BC", "competitor": "#FF7043",
    "capability": "#42A5F5", "use_case": "#66BB6A", "problem": "#FFCA28",
    "audience": "#EC407A", "decision_factor": "#8D6E63",
    "job_to_be_done": "#26C6DA", "outcome": "#78909C",
    "product_version": "#9CCC65", "topic": "#3E8E41", "entity_type": "#7E57C2",
    "relation_type": "#29B6F6",
}
DEFAULT_COLOR = "#90A4AE"


def _load(layer: str) -> dict:
    p = OUT_DIR / f"{layer}_graph.json"
    if not p.exists():
        return {"nodes": [], "edges": [], "statements": [], "stats": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _color(t: str) -> str:
    return TYPE_STYLE.get(t, DEFAULT_COLOR)


def _build_html() -> str:
    layers = {k: _load(k) for k in ("l1", "l2", "l3")}
    data_json = json.dumps(layers, ensure_ascii=False)

    tabs = "".join(
        f'<button class="tab {"active" if k=="l2" else ""}" data-layer="{k}" '
        f'onclick="setLayer(\'{k}\')">{LAYER_NAMES[k]}</button>'
        for k in ("l1", "l2", "l3")
    )
    counts = "".join(
        f'<span class="chips" id="chip-{k}">{LAYER_NAMES[k][:2]}: {len(layers[k]["nodes"])}</span>'
        for k in ("l1", "l2", "l3")
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Brand Atlas 分层知识图谱 · 2D 展示原型</title>
<link rel="stylesheet" href="assets/vis-network.min.css">
<style>
  body {{ margin:0; font-family: "Microsoft YaHei", system-ui, sans-serif; background:#0f1222; color:#e6e8f0; }}
  header {{ padding:14px 20px; background:#171a2e; border-bottom:1px solid #2a2f4a; }}
  h1 {{ margin:0 0 10px; font-size:18px; }}
  .tabs button {{ margin-right:8px; padding:8px 16px; border:none; border-radius:6px;
                  background:#262b47; color:#cfd4f0; cursor:pointer; font-size:14px; }}
  .tabs button.active {{ background:#3f57e8; color:#fff; }}
  .chips {{ margin-left:10px; font-size:12px; color:#8e94b8; }}
  .layout {{ display:flex; height:calc(100vh - 96px); }}
  #cy {{ flex:1; }}
  #detail {{ width:290px; background:#171a2e; border-left:1px solid #2a2f4a; padding:14px; overflow:auto; font-size:13px; }}
  #detail h3 {{ margin:0 0 10px; font-size:15px; }}
  #detail .kv {{ margin:4px 0; }}
  #detail .k {{ color:#8e94b8; }}
  #empty {{ padding:40px; color:#8e94b8; text-align:center; font-size:15px; }}
  input#q {{ margin-bottom:8px; width:100%; padding:8px; border:1px solid #2a2f4a;
             border-radius:6px; background:#262b47; color:#e6e8f0; }}
</style>
</head>
<body>
<header>
  <h1>Brand Atlas 分层知识图谱 · 2D 展示原型</h1>
  <div class="tabs">{tabs}{counts}</div>
</header>
<div class="layout">
  <div id="cy"></div>
  <div id="detail"><input id="q" placeholder="🔍 搜索当前层节点…" oninput="onSearch(this.value)"><div id="det-content">点击节点查看详情</div></div>
</div>
<div id="empty" style="display:none"></div>

<script src="assets/vis-network.min.js"></script>
<script>
window.LAYERS = {data_json};

var TYPE_STYLE = {json.dumps(TYPE_STYLE, ensure_ascii=False)};
var LAYER_NAMES = {json.dumps(LAYER_NAMES, ensure_ascii=False)};
var DEFAULT_COLOR = "{DEFAULT_COLOR}";
var network = null;

function colorFor(t) {{ return TYPE_STYLE[t] || DEFAULT_COLOR; }}

function blanksToUndefined(v) {{ return (v===null||v===undefined||v==="") ? undefined : v; }}

function render(layerKey) {{
  var data = window.LAYERS[layerKey] || {{nodes:[],edges:[]}};
  var emptyEl = document.getElementById('empty');
  var cy = document.getElementById('cy');
  if (!data.nodes || data.nodes.length === 0) {{
    if (network) {{ network.destroy(); network = null; }}
    cy.style.display = 'none';
    emptyEl.style.display = 'block';
    emptyEl.textContent = '「' + LAYER_NAMES[layerKey] + '」当前暂无数据';
    return;
  }}
  cy.style.display = '';
  emptyEl.style.display = 'none';

  var nodeMap = {{}};
  var nodes = data.nodes.map(function(n) {{
    nodeMap[n.id] = n;
    return {{
      id: String(n.id),
      label: n.label || n.canonical_name || n.entity_id,
      color: {{ background: colorFor(n.type), border: '#ffffff' }},
      title: (n.layer ? n.layer + ' · ' : '') + (n.type || '') + '\\n' + (n.label || ''),
      font: {{ color: '#e6e8f0', size: 12 }}
    }};
  }});
  var ids = new Set(nodes.map(function(n){{ return n.id; }}));
  var edges = [];
  (data.edges || []).forEach(function(e) {{
    if (!ids.has(String(e.subject_id)) || !ids.has(String(e.object_id))) return;
    edges.push({{
      id: String(e.id || (e.subject_id + '_' + e.object_id)),
      from: String(e.subject_id),
      to: String(e.object_id),
      label: e.type || '',
      font: {{ color: '#9aa0c0', size: 10 }},
      arrows: 'to',
      color: '#5a6090'
    }});
  }});

  var container = document.getElementById('cy');
  network = new vis.Network(container, {{nodes:new vis.DataSet(nodes), edges:new vis.DataSet(edges)}}, {{
    nodes: {{ shape:'dot', size:16 }},
    layout: {{ improvedLayout: false }},
    physics: {{ solver:'barnesHut', barnesHut: {{ gravitationalConstant:-8000, centralGravity:0.3, springLength:110, springConstant:0.04 }} }},
    interaction: {{ hover:true, tooltipDelay:120 }}
  }});
  network.on('click', function(params) {{
    if (params.nodes && params.nodes.length) showDetail(nodeMap[params.nodes[0]]);
  }});
}}

function showDetail(n) {{
  if (!n) return;
  var c = document.getElementById('det-content');
  var rows = ['label','type','layer','canonical_name','status','scope','entity_id','industry_id','brand_id']
    .filter(function(k){{ return n[k]!==undefined && n[k]!==null && n[k]!==''; }})
    .map(function(k){{ return '<div class="kv"><span class="k">'+k+'</span>: '+String(n[k])+'</div>'; }})
    .join('');
  c.innerHTML = '<h3>' + (n.label||'') + '</h3>' + rows;
}}

function onSearch(q) {{
  q = (q||'').trim().toLowerCase();
  if (!q) {{ if (network) network.setOptions({{}}); return; }}
  // Highlight matching nodes by re-rendering is heavy; instead filter edges to
  // matched nodes is complex — we do a simple size emphasis via existing nodes.
  if (!network) return;
  var data = window.LAYERS[currentLayer] || {{nodes:[]}};
  var matched = new Set(data.nodes.filter(function(n){{
    return String(n.label||'').toLowerCase().indexOf(q) >= 0 ||
           String(n.canonical_name||'').toLowerCase().indexOf(q) >= 0;
  }}).map(function(n){{ return String(n.id); }}));
  var nodes = network.body.data.nodes;
  nodes.forEach(function(n){{
    var hit = matched.has(String(n.id));
    n.size = hit ? 26 : 13;
  }});
  network.setOptions({{}});
}}

var currentLayer = 'l2';
function setLayer(k) {{
  currentLayer = k;
  document.querySelectorAll('.tab').forEach(function(b){{ b.classList.toggle('active', b.dataset.layer===k); }});
  document.getElementById('q').value = '';
  render(k);
}}

// init
render('l2');
</script>
</body>
</html>
"""
    return html


def main() -> None:
    out = OUT_DIR / "layered_2d.html"
    out.write_text(_build_html(), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
