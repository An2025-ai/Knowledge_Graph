"""Render the exported Brand Atlas knowledge graph into interactive pyvis HTML.

Reads legacy/visualize/output/knowledge_graph.json (from legacy.visualize.export)
and produces:
  - a full graph (all nodes/edges, colored by entity type)
  - a focused subgraph around the e-commerce finance industry nodes

Usage:
    python scripts/render_graph.py [--focused]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from pyvis.network import Network

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "legacy" / "visualize" / "output" / "knowledge_graph.json"
OUT_DIR = ROOT / "legacy" / "visualize" / "output"

# Node color / shape by entity type (L1 labels projected into the graph).
TYPE_STYLE = {
    "industry": {"color": "#7C4DFF", "shape": "diamond"},
    "category": {"color": "#5C6BC0", "shape": "box"},
    "product": {"color": "#26A69A", "shape": "dot"},
    "brand": {"color": "#EF5350", "shape": "star"},
    "organization": {"color": "#AB47BC", "shape": "dot"},
    "competitor": {"color": "#FF7043", "shape": "triangle"},
    "capability": {"color": "#42A5F5", "shape": "dot"},
    "use_case": {"color": "#66BB6A", "shape": "dot"},
    "problem": {"color": "#FFCA28", "shape": "dot"},
    "audience": {"color": "#EC407A", "shape": "dot"},
    "decision_factor": {"color": "#8D6E63", "shape": "diamond"},
    "job_to_be_done": {"color": "#26C6DA", "shape": "dot"},
    "outcome": {"color": "#78909C", "shape": "triangle"},
    "product_version": {"color": "#9CCC65", "shape": "box"},
    "topic": {"color": "#3E8E41", "shape": "dot"},
}

# Relations to keep in the full view (drop very dense/noisy ones if needed).
REL_KEEP = None  # keep all in full view


def _style(node_type: str) -> dict:
    return TYPE_STYLE.get(node_type, {"color": "#90A4AE", "shape": "dot"})


def build_network() -> tuple[Network, dict, list]:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    nodes = data["nodes"]
    edges = data["edges"]
    node_by_id = {n["id"]: n for n in nodes}
    net = Network(
        height="92vh",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#1a1a2e",
    )
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=120, spring_strength=0.01)
    return net, node_by_id, edges


def shape_label(n: dict) -> str:
    return n.get("label") or n.get("canonical_name") or n.get("entity_id", "?")


def add_nodes(net: Network, node_ids: list[str], node_by_id: dict) -> None:
    for nid in node_ids:
        n = node_by_id[nid]
        st = _style(n.get("type", ""))
        title = (
            f"<b>{n.get('type')}</b><br/>"
            f"{shape_label(n)}<br/>"
            f"<code>{n.get('entity_id','')}</code>"
        )
        net.add_node(
            nid,
            label=shape_label(n),
            title=title,
            color=st["color"],
            shape=st["shape"],
            size=14,
        )


def add_edges_filtered(
    net: Network, node_ids: set[str], edges: list, node_by_id: dict
) -> int:
    added = 0
    for e in edges:
        if e["subject_id"] not in node_ids or e["object_id"] not in node_ids:
            continue
        label = e.get("type", "")
        net.add_edge(
            e["subject_id"],
            e["object_id"],
            title=label,
            label="" if len(node_ids) > 200 else label,
            arrows="to",
            color="#607D8B",
        )
        added += 1
    return added


def render_full() -> str:
    net, node_by_id, edges = build_network()
    add_nodes(net, list(node_by_id.keys()), node_by_id)
    add_edges_filtered(net, set(node_by_id.keys()), edges, node_by_id)
    out = OUT_DIR / "knowledge_graph_full.html"
    net.write_html(str(out), open_browser=False)
    return str(out)


def render_focused() -> str:
    """Subgraph around the e-commerce finance industry nodes (only entities whose
    entity_id mentions 电商业财, plus their direct neighbors)."""
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    nodes, edges = data["nodes"], data["edges"]
    node_by_id = {n["id"]: n for n in nodes}
    selected = set()
    for n in nodes:
        eid = n.get("entity_id", "")
        if "电商业财" in eid or "电商财务" in eid:
            selected.add(n["id"])
    if not selected:
        # fallback: industry + category nodes mentioning 财务/电商
        for n in nodes:
            if n.get("type") == "industry" and ("财务" in (n.get("canonical_name") or "")):
                selected.add(n["id"])
        if not selected:
            for n in nodes:
                if n.get("type") in ("industry", "category"):
                    selected.add(n["id"])
    # 1-hop neighbors (undirected reach)
    for e in edges:
        if e["subject_id"] in selected or e["object_id"] in selected:
            selected.add(e["subject_id"])
            selected.add(e["object_id"])
    net = Network(
        height="92vh", width="100%", directed=True, bgcolor="#ffffff", font_color="#1a1a2e"
    )
    net.barnes_hut(gravity=-2500, central_gravity=0.3, spring_length=130, spring_strength=0.015)
    add_nodes(net, list(selected), node_by_id)
    add_edges_filtered(net, selected, edges, node_by_id)
    out = OUT_DIR / "knowledge_graph_focused.html"
    net.write_html(str(out), open_browser=False)
    return str(out)


# Layer -> color for the layer-colored render (nodes carry a `layer` field from export).
LAYER_STYLE = {
    "L1": {"color": "#9E9E9E", "label": "L1 通用"},
    "L2": {"color": "#42A5F5", "label": "L2 行业"},
    "L3": {"color": "#EF5350", "label": "L3 品牌"},
}


def render_layers() -> str:
    """Render the graph colored by L1/L2/L3 layer, emphasizing cross-layer edges."""
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    nodes, edges = data["nodes"], data["edges"]
    node_by_id = {n["id"]: n for n in nodes}
    net = Network(
        height="92vh", width="100%", directed=True, bgcolor="#ffffff", font_color="#1a1a2e"
    )
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=120, spring_strength=0.01)
    for n in nodes:
        layer = n.get("layer", "L1")
        ls = LAYER_STYLE.get(layer, {"color": "#90A4AE"})
        net.add_node(
            n["id"],
            label=n.get("label", "?"),
            title=f"<b>{layer} · {n.get('type')}</b><br/>{n.get('label')}",
            color=ls["color"],
            shape="dot",
            size=13,
        )
    nids = set(node_by_id.keys())
    for e in edges:
        if e["subject_id"] not in nids or e["object_id"] not in nids:
            continue
        is_cross = e.get("cross_layer") or (
            node_by_id.get(e["subject_id"], {}).get("layer") != node_by_id.get(e["object_id"], {}).get("layer")
        )
        net.add_edge(
            e["subject_id"], e["object_id"],
            title=e.get("type", ""),
            label="" if len(nodes) > 200 else e.get("type", ""),
            arrows="to",
            color="#7B1FA2" if is_cross else "#B0BEC5",
            width=3.5 if is_cross else 1,
        )
    out = OUT_DIR / "knowledge_graph_layers.html"
    net.write_html(str(out), open_browser=False)
    return str(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--focused", action="store_true", help="render focused subgraph only")
    ap.add_argument("--layers", action="store_true", help="render layer-colored graph only")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.layers:
        p = render_layers()
        print(f"layers -> {p}")
        return
    if args.focused:
        p = render_focused()
        print(f"focused -> {p}")
    else:
        f = render_full()
        print(f"full    -> {f}")
        p = render_focused()
        print(f"focused -> {p}")


if __name__ == "__main__":
    main()
