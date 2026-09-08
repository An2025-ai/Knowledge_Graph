import { useMemo, useState } from "react";
import type { GraphData, GraphNode } from "../../api/types";

const palette: Record<string, string> = {
  brand: "#f3b562",
  product: "#62c5b5",
  capability: "#74a8ff",
  audience: "#c88df2",
  organization: "#fb8f78",
  default: "#8ea1ad",
};

function color(type: string) {
  return palette[type] || palette.default;
}

export default function GraphView({ data, onSelect }: { data: GraphData; onSelect: (node: GraphNode) => void }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const positions = useMemo(() => {
    const width = 760;
    const height = 460;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(185, 68 + data.nodes.length * 10);
    return new Map(data.nodes.map((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(data.nodes.length, 1) - Math.PI / 2;
      return [node.id, { x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius }] as const;
    }));
  }, [data.nodes]);

  return (
    <div className="graph-canvas-wrap">
      <svg className="graph-canvas" viewBox="0 0 760 460" role="img" aria-label="知识图谱可视化">
        <defs>
          <filter id="soft-glow"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#56717d" /></marker>
        </defs>
        {data.edges.map((edge) => {
          const from = positions.get(edge.source);
          const to = positions.get(edge.target);
          if (!from || !to) return null;
          return <g key={edge.id} className="graph-edge"><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} markerEnd="url(#arrow)" /><text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 7}>{edge.type}</text></g>;
        })}
        {data.nodes.map((node) => {
          const point = positions.get(node.id);
          if (!point) return null;
          const active = hovered === node.id;
          return <g key={node.id} className={`graph-node ${active ? "is-hovered" : ""}`} transform={`translate(${point.x}, ${point.y})`} onMouseEnter={() => setHovered(node.id)} onMouseLeave={() => setHovered(null)} onClick={() => onSelect(node)}>
            <circle r={active ? 27 : 22} fill={color(node.type)} filter={active ? "url(#soft-glow)" : undefined} />
            <text className="node-type">{node.type}</text>
            <text className="node-name">{node.name.length > 14 ? `${node.name.slice(0, 14)}…` : node.name}</text>
          </g>;
        })}
        {!data.nodes.length && <text x="380" y="230" textAnchor="middle" className="empty-graph">导入一份资料后，这里会出现知识关系</text>}
      </svg>
      <div className="graph-legend">
        {Object.entries(palette).filter(([key]) => key !== "default").map(([key, value]) => <span key={key}><i style={{ background: value }} />{key}</span>)}
      </div>
    </div>
  );
}
