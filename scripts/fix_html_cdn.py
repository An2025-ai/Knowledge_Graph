"""Rewrite vis-network CDN references to local assets/ paths in the rendered HTML."""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "engine" / "visualize" / "output"

CDN_JS = re.compile(
    r"<script\s+src=\"https://cdnjs\.cloudflare\.com/ajax/libs/vis-network/[^\"]*\"[^>]*>\s*</script>"
)
CDN_CSS = re.compile(
    r"<link\s+rel=\"stylesheet\"\s+href=\"https://cdnjs\.cloudflare\.com/ajax/libs/vis-network/[^\"]*\"[^>]*>"
)


def main() -> None:
    for f in ("knowledge_graph_focused.html", "knowledge_graph_full.html", "knowledge_graph_layers.html"):
        p = OUT / f
        content = p.read_text(encoding="utf-8")
        n_js = len(CDN_JS.findall(content))
        n_css = len(CDN_CSS.findall(content))
        content = CDN_JS.sub('<script src="assets/vis-network.min.js"></script>', content)
        content = CDN_CSS.sub('<link rel="stylesheet" href="assets/vis-network.min.css">', content)
        p.write_text(content, encoding="utf-8")
        print(f"{f}: replaced {n_js} JS + {n_css} CSS CDN refs; cdnjs residual={content.count('cdnjs.cloudflare')}")


if __name__ == "__main__":
    main()