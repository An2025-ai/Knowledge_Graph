"""Clean up stale/absent script references so the vis-network graph renders offline.

Fixes two 404s that break script execution in the pyvis HTML:
  1. assets/bindings/utils.js  -> create a minimal empty one (avoids 404).
  2. ../node_modules/vis/dist/vis.js -> remove (vis-network.min.js in assets/ is the real core).
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "legacy" / "visualize" / "output"
LIB = OUT / "assets"


def main() -> None:
    bindings = LIB / "bindings"
    bindings.mkdir(parents=True, exist_ok=True)
    utils_js = bindings / "utils.js"
    if not utils_js.exists():
        utils_js.write_text("// minimal placeholder to avoid 404\n", encoding="utf-8")
        print("created", utils_js)

    node_modules_ref = re.compile(
        r"<script[^>]*src=[\"']\.\./node_modules/vis/dist/vis\.js[\"'][^>]*>\s*</script>"
    )
    for f in ("knowledge_graph_focused.html", "knowledge_graph_full.html", "knowledge_graph_layers.html"):
        p = OUT / f
        content = p.read_text(encoding="utf-8")
        n = len(node_modules_ref.findall(content))
        content = node_modules_ref.sub("", content)
        p.write_text(content, encoding="utf-8")
        print(f"{f}: removed {n} node_modules/vis.js refs; 404 candidates left="
              f"{content.count('node_modules') + content.count('assets/bindings/utils.js')}")


if __name__ == "__main__":
    main()
